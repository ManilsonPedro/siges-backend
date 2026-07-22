"""Marketing (domínio Gestão Comercial): Segmentos e Campanhas.

Envio de campanhas: adaptador local (grava log/simulação) hoje; real
via SMS/WhatsApp/Email gateway quando confirmado — mesmo padrão de
porta já usado no projeto (ex.: SMTP de recuperação de senha).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import CampanhaModel, ClienteModel, SegmentoClienteModel


router = APIRouter()


# ─── Segmentos ───────────────────────────────────────────────────────


class SegmentoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    criterios: dict = Field(default_factory=dict)


class SegmentoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    criterios: dict = {}

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, m: SegmentoClienteModel) -> "SegmentoResponseDTO":
        return cls(id=m.id, company_id=m.company_id, nome=m.nome, criterios=json.loads(m.criterios) if m.criterios else {})


@router.get("/segmentos", response_model=List[SegmentoResponseDTO])
async def list_segmentos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.view")),
):
    r = await db.execute(
        select(SegmentoClienteModel)
        .where(SegmentoClienteModel.company_id == current_user.company_id)
        .where(SegmentoClienteModel.deleted_at.is_(None))
    )
    return [SegmentoResponseDTO.from_model(m) for m in r.scalars().all()]


@router.post("/segmentos", response_model=SegmentoResponseDTO, status_code=201)
async def create_segmento(
    body: SegmentoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.gerir_segmentos")),
):
    m = SegmentoClienteModel(id=uuid4(), company_id=current_user.company_id, nome=body.nome, criterios=json.dumps(body.criterios))
    db.add(m)
    await db.commit()
    return SegmentoResponseDTO.from_model(m)


@router.delete("/segmentos/{id}", status_code=204)
async def delete_segmento(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.gerir_segmentos")),
):
    r = await db.execute(select(SegmentoClienteModel).where(SegmentoClienteModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Segmento não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


@router.get("/segmentos/{id}/preview")
async def preview_segmento(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.view")),
):
    """Aplica os critérios simples do segmento (comparações directas
    sobre campos de Cliente) e devolve os clientes correspondentes."""
    sr = await db.execute(select(SegmentoClienteModel).where(SegmentoClienteModel.id == id))
    segmento = sr.scalar_one_or_none()
    if not segmento or segmento.company_id != current_user.company_id:
        raise HTTPException(404, "Segmento não encontrado")

    criterios = json.loads(segmento.criterios) if segmento.criterios else {}
    stmt = (
        select(ClienteModel)
        .where(ClienteModel.company_id == current_user.company_id)
        .where(ClienteModel.deleted_at.is_(None))
    )
    if criterios.get("estado"):
        stmt = stmt.where(ClienteModel.estado == criterios["estado"])
    r = await db.execute(stmt)
    clientes = list(r.scalars().all())
    return {"total": len(clientes), "clientes": [{"id": str(c.id), "nome": c.nome} for c in clientes]}


# ─── Campanhas ───────────────────────────────────────────────────────


class CampanhaCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=150)
    tipo: str = Field(..., pattern="^(sms|whatsapp|email|promocao)$")
    segmento_id: Optional[UUID] = None
    conteudo: str = Field(..., min_length=1)
    data_agendada: Optional[datetime] = None


class CampanhaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    tipo: str
    segmento_id: Optional[UUID] = None
    conteudo: str
    data_agendada: Optional[datetime] = None
    estado: str
    enviados_count: int
    entregues_count: int
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/campanhas", response_model=List[CampanhaResponseDTO])
async def list_campanhas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.view")),
):
    r = await db.execute(select(CampanhaModel).where(CampanhaModel.company_id == current_user.company_id))
    return list(r.scalars().all())


@router.post("/campanhas", response_model=CampanhaResponseDTO, status_code=201)
async def create_campanha(
    body: CampanhaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.gerir_campanhas")),
):
    m = CampanhaModel(id=uuid4(), company_id=current_user.company_id, estado="rascunho", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/campanhas/{id}", response_model=CampanhaResponseDTO)
async def update_campanha(
    id: UUID,
    body: CampanhaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.gerir_campanhas")),
):
    r = await db.execute(select(CampanhaModel).where(CampanhaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Campanha não encontrada")
    if m.estado != "rascunho":
        raise HTTPException(400, "Só é possível editar campanhas em rascunho")
    for field, value in body.model_dump().items():
        setattr(m, field, value)
    await db.commit()
    return m


@router.post("/campanhas/{id}/enviar", response_model=CampanhaResponseDTO)
async def enviar_campanha(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.enviar_campanhas")),
):
    r = await db.execute(select(CampanhaModel).where(CampanhaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Campanha não encontrada")
    if m.estado not in ("rascunho", "agendada"):
        raise HTTPException(400, "Campanha já foi enviada ou cancelada")

    destinatarios = []
    if m.segmento_id:
        preview = await preview_segmento(m.segmento_id, db, current_user)
        destinatarios = preview["clientes"]
    else:
        cr = await db.execute(
            select(ClienteModel)
            .where(ClienteModel.company_id == current_user.company_id)
            .where(ClienteModel.deleted_at.is_(None))
        )
        destinatarios = [{"id": str(c.id), "nome": c.nome} for c in cr.scalars().all()]

    # Adaptador local: regista envio simulado (sem gateway real de SMS/WhatsApp configurado).
    m.enviados_count = len(destinatarios)
    m.entregues_count = len(destinatarios)
    m.estado = "enviada"
    await db.commit()
    return m


@router.post("/campanhas/{id}/cancelar", response_model=CampanhaResponseDTO)
async def cancelar_campanha(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("marketing.gerir_campanhas")),
):
    r = await db.execute(select(CampanhaModel).where(CampanhaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Campanha não encontrada")
    if m.estado == "enviada":
        raise HTTPException(400, "Não é possível cancelar campanha já enviada")
    m.estado = "cancelada"
    await db.commit()
    return m


__all__ = ["router"]
