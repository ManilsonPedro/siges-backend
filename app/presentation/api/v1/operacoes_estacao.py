"""Gestão da Estação (domínio Operações): áreas de serviço, equipamentos, turnos."""
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
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    AreaServicoModel,
    EquipamentoModel,
    TurnoOperacionalModel,
)


router = APIRouter()


# ─── Áreas de Serviço ────────────────────────────────────────────────


class AreaServicoCreateDTO(BaseModel):
    filial_id: Optional[UUID] = None
    nome: str = Field(..., min_length=1, max_length=120)
    tipo: str = Field(..., pattern="^(bomba|lavagem|loja|restauracao)$")
    activo: bool = True


class AreaServicoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    filial_id: Optional[UUID] = None
    nome: str
    tipo: str
    activo: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/areas-servico", response_model=List[AreaServicoResponseDTO])
async def list_areas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.view")),
):
    r = await db.execute(
        select(AreaServicoModel)
        .where(AreaServicoModel.company_id == current_user.company_id)
        .where(AreaServicoModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/areas-servico", response_model=AreaServicoResponseDTO, status_code=201)
async def create_area(
    req: Request,
    body: AreaServicoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.gerir_equipamentos")),
):
    m = AreaServicoModel(
        id=uuid4(), company_id=current_user.company_id, filial_id=body.filial_id,
        nome=body.nome, tipo=body.tipo, activo=body.activo,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "area_servico", m.id, dados_novos={"nome": body.nome, "tipo": body.tipo},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.delete("/areas-servico/{id}", status_code=204)
async def delete_area(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.gerir_equipamentos")),
):
    r = await db.execute(select(AreaServicoModel).where(AreaServicoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Área de serviço não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Equipamentos ────────────────────────────────────────────────────


class EquipamentoCreateDTO(BaseModel):
    area_servico_id: Optional[UUID] = None
    nome: str = Field(..., min_length=1, max_length=120)
    tipo: str = Field(..., pattern="^(maquina_lavagem|outro)$")


class EquipamentoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    area_servico_id: Optional[UUID] = None
    nome: str
    tipo: str
    estado: str
    ultima_manutencao: Optional[datetime] = None
    proxima_manutencao_prevista: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/equipamentos", response_model=List[EquipamentoResponseDTO])
async def list_equipamentos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.view")),
):
    r = await db.execute(
        select(EquipamentoModel)
        .where(EquipamentoModel.company_id == current_user.company_id)
        .where(EquipamentoModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/equipamentos", response_model=EquipamentoResponseDTO, status_code=201)
async def create_equipamento(
    req: Request,
    body: EquipamentoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.gerir_equipamentos")),
):
    m = EquipamentoModel(
        id=uuid4(), company_id=current_user.company_id, area_servico_id=body.area_servico_id,
        nome=body.nome, tipo=body.tipo, estado="operacional",
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "equipamento", m.id, dados_novos={"nome": body.nome},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.post("/equipamentos/{id}/registar-manutencao", response_model=EquipamentoResponseDTO)
async def registar_manutencao(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.gerir_equipamentos")),
):
    r = await db.execute(select(EquipamentoModel).where(EquipamentoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Equipamento não encontrado")
    m.ultima_manutencao = datetime.utcnow()
    m.estado = "operacional"
    await db.commit()
    return m


# ─── Turnos ──────────────────────────────────────────────────────────


class TurnoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    hora_inicio: str = Field(..., pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    hora_fim: str = Field(..., pattern="^([01]\\d|2[0-3]):[0-5]\\d$")


class TurnoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    hora_inicio: str
    hora_fim: str

    class Config:
        from_attributes = True


@router.get("/turnos", response_model=List[TurnoResponseDTO])
async def list_turnos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.view")),
):
    r = await db.execute(
        select(TurnoOperacionalModel)
        .where(TurnoOperacionalModel.company_id == current_user.company_id)
        .where(TurnoOperacionalModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/turnos", response_model=TurnoResponseDTO, status_code=201)
async def create_turno(
    body: TurnoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.gerir_turnos")),
):
    m = TurnoOperacionalModel(
        id=uuid4(), company_id=current_user.company_id,
        nome=body.nome, hora_inicio=body.hora_inicio, hora_fim=body.hora_fim,
    )
    db.add(m)
    await db.commit()
    return m


@router.delete("/turnos/{id}", status_code=204)
async def delete_turno(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.estacao.gerir_turnos")),
):
    r = await db.execute(select(TurnoOperacionalModel).where(TurnoOperacionalModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Turno não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


__all__ = ["router"]
