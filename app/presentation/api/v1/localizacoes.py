"""CRUD de Localizações físicas dentro de armazéns (domínio Supply Chain)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import get_current_user, require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import ArmazemModel, LocalizacaoModel


router = APIRouter()


class LocalizacaoCreateDTO(BaseModel):
    armazem_id: UUID
    codigo: str = Field(..., min_length=1, max_length=30)
    corredor: Optional[str] = Field(None, max_length=30)
    prateleira: Optional[str] = Field(None, max_length=30)
    activo: bool = True


class LocalizacaoUpdateDTO(BaseModel):
    codigo: Optional[str] = Field(None, min_length=1, max_length=30)
    corredor: Optional[str] = Field(None, max_length=30)
    prateleira: Optional[str] = Field(None, max_length=30)
    activo: Optional[bool] = None


class LocalizacaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    armazem_id: UUID
    codigo: str
    corredor: Optional[str] = None
    prateleira: Optional[str] = None
    activo: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[LocalizacaoResponseDTO])
async def list_localizacoes(
    armazem_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.ver")),
):
    stmt = (
        select(LocalizacaoModel)
        .where(LocalizacaoModel.company_id == current_user.company_id)
        .where(LocalizacaoModel.deleted_at.is_(None))
    )
    if armazem_id:
        stmt = stmt.where(LocalizacaoModel.armazem_id == armazem_id)
    stmt = stmt.order_by(LocalizacaoModel.codigo)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("", response_model=LocalizacaoResponseDTO, status_code=201)
async def create_localizacao(
    req: Request,
    body: LocalizacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.gerir_localizacoes")),
):
    arm = await db.execute(
        select(ArmazemModel)
        .where(ArmazemModel.id == body.armazem_id)
        .where(ArmazemModel.company_id == current_user.company_id)
        .where(ArmazemModel.deleted_at.is_(None))
    )
    if not arm.scalar_one_or_none():
        raise HTTPException(404, "Armazém não encontrado")

    clash = await db.execute(
        select(LocalizacaoModel)
        .where(LocalizacaoModel.armazem_id == body.armazem_id)
        .where(LocalizacaoModel.codigo == body.codigo)
        .where(LocalizacaoModel.deleted_at.is_(None))
    )
    if clash.scalar_one_or_none():
        raise HTTPException(409, f"Já existe localização com código '{body.codigo}' neste armazém")

    m = LocalizacaoModel(
        id=uuid4(), company_id=current_user.company_id,
        armazem_id=body.armazem_id, codigo=body.codigo,
        corredor=body.corredor, prateleira=body.prateleira,
        activo=body.activo,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "localizacao", m.id,
        dados_novos={"codigo": m.codigo, "armazem_id": str(m.armazem_id)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.patch("/{id}", response_model=LocalizacaoResponseDTO)
async def update_localizacao(
    id: UUID,
    body: LocalizacaoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.gerir_localizacoes")),
):
    r = await db.execute(select(LocalizacaoModel).where(LocalizacaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Localização não encontrada")

    if body.codigo is not None:
        m.codigo = body.codigo
    if body.corredor is not None:
        m.corredor = body.corredor
    if body.prateleira is not None:
        m.prateleira = body.prateleira
    if body.activo is not None:
        m.activo = body.activo
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


@router.delete("/{id}", status_code=204)
async def delete_localizacao(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.gerir_localizacoes")),
):
    r = await db.execute(select(LocalizacaoModel).where(LocalizacaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Localização não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


__all__ = ["router"]
