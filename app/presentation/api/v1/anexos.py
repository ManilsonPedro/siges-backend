"""Anexos genéricos com versionamento — reutilizável por qualquer entidade
via (entity_type, entity_id). Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fase 4.

Endpoints:
  GET    /anexos/{entity_type}/{entity_id}
  POST   /anexos/{entity_type}/{entity_id}
  DELETE /anexos/{id}
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.database import get_db
from app.infrastructure.database.models import AnexoModel
from app.infrastructure.storage import get_storage_provider

router = APIRouter()


def resolver_url_anexo(storage, file_path: str, *, base_url: str = "") -> str:
    """URL consumível pelo frontend para um file_path de storage — presigned
    no B2, ou caminho local servido pela app. Reutilizável por qualquer
    módulo que precise expor um AnexoModel (ex. fotos de ordem_lavagem)."""
    if hasattr(storage, "presigned_url"):
        return storage.presigned_url(file_path)
    return f"{base_url}/uploads/{file_path}" if base_url else f"/uploads/{file_path}"


async def listar_anexos_por_tipo(
    db: AsyncSession, *, company_id: UUID, entity_type: str, entity_id: UUID, tipo_documento: str, base_url: str = "",
) -> List[str]:
    """Devolve as URLs dos anexos mais recentes (por versão) de um tipo de
    documento — usado por get_fotos (ordem_lavagem) para não duplicar a
    query de listagem já feita em list_anexos."""
    storage = get_storage_provider()
    r = await db.execute(
        select(AnexoModel)
        .where(AnexoModel.company_id == company_id)
        .where(AnexoModel.entity_type == entity_type)
        .where(AnexoModel.entity_id == entity_id)
        .where(AnexoModel.tipo_documento == tipo_documento)
        .where(AnexoModel.deleted_at.is_(None))
        .order_by(AnexoModel.versao.desc())
    )
    return [resolver_url_anexo(storage, a.file_path, base_url=base_url) for a in r.scalars().all()]


_ALLOWED_MIME = {
    "application/pdf",
    "image/png", "image/jpeg", "image/jpg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

_TIPOS_DOCUMENTO = {
    "proforma", "fatura", "fatura_recibo", "recibo", "ordem_recepcao", "guia_transporte",
    "comprovativo_pagamento", "comprovativo_bancario", "fotografia", "foto_antes", "foto_depois", "outro",
}
_TIPOS_IMAGEM = {"image/png", "image/jpeg", "image/jpg"}


class AnexoResponseDTO(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    tipo_documento: str
    versao: int
    file_path: str
    file_name: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_by: UUID
    uploaded_at: datetime

    class Config:
        from_attributes = True


@router.get("/{entity_type}/{entity_id}", response_model=List[AnexoResponseDTO])
async def list_anexos(
    entity_type: str,
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(AnexoModel)
        .where(AnexoModel.company_id == current_user.company_id)
        .where(AnexoModel.entity_type == entity_type)
        .where(AnexoModel.entity_id == entity_id)
        .where(AnexoModel.deleted_at.is_(None))
        .order_by(AnexoModel.tipo_documento, AnexoModel.versao.desc())
    )
    return list(r.scalars().all())


@router.post("/{entity_type}/{entity_id}", response_model=AnexoResponseDTO, status_code=201)
async def upload_anexo(
    entity_type: str,
    entity_id: UUID,
    req: Request,
    tipo_documento: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if tipo_documento not in _TIPOS_DOCUMENTO:
        raise HTTPException(400, f"Tipo de documento inválido: {tipo_documento}")
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(400, f"Tipo de ficheiro não suportado: {file.content_type}")
    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(400, "Ficheiro maior que 10 MB")

    versao_r = await db.execute(
        select(func.max(AnexoModel.versao))
        .where(AnexoModel.company_id == current_user.company_id)
        .where(AnexoModel.entity_type == entity_type)
        .where(AnexoModel.entity_id == entity_id)
        .where(AnexoModel.tipo_documento == tipo_documento)
    )
    versao = (versao_r.scalar() or 0) + 1

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    file_key = f"anexos/{entity_type}/{entity_id}/{tipo_documento}_v{versao}_{uuid4().hex[:8]}.{ext}"

    storage = get_storage_provider()
    await storage.upload(file_key, io.BytesIO(content), content_type=file.content_type or "application/octet-stream")

    a = AnexoModel(
        id=uuid4(), company_id=current_user.company_id,
        entity_type=entity_type, entity_id=entity_id,
        tipo_documento=tipo_documento, versao=versao,
        file_path=file_key, file_name=file.filename or file_key,
        mime_type=file.content_type, size_bytes=len(content),
        uploaded_by=current_user.id,
    )
    db.add(a)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "anexo_upload", entity_type, entity_id,
        dados_novos={"tipo_documento": tipo_documento, "versao": versao, "file_name": a.file_name},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return a


@router.delete("/{id}", status_code=204)
async def delete_anexo(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(AnexoModel).where(AnexoModel.id == id))
    a = r.scalar_one_or_none()
    if not a or a.company_id != current_user.company_id or a.deleted_at is not None:
        raise HTTPException(404, "Anexo não encontrado")

    a.deleted_at = datetime.utcnow()
    a.deleted_by = current_user.id
    await write_audit(
        db, current_user.id, current_user.company_id,
        "anexo_remover", a.entity_type, a.entity_id,
        dados_anteriores={"file_name": a.file_name, "versao": a.versao},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


__all__ = ["router"]
