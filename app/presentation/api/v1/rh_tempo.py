"""Gestão de Tempo (domínio Capital Humano): Horários, Ponto, Faltas,
Férias, Horas Extra, Indicadores de Assiduidade."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    ColaboradorModel,
    FaltaModel,
    FeriasModel,
    HoraExtraModel,
    HorarioColaboradorModel,
    RegistoPontoModel,
)


router = APIRouter()


# ─── Horários ────────────────────────────────────────────────────────


class HorarioSetDTO(BaseModel):
    dia_semana: int = Field(..., ge=0, le=6)
    hora_entrada: str = Field(..., pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    hora_saida: str = Field(..., pattern="^([01]\\d|2[0-3]):[0-5]\\d$")


class HorarioResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    dia_semana: int
    hora_entrada: str
    hora_saida: str

    class Config:
        from_attributes = True


@router.get("/horarios/{colaborador_id}", response_model=List[HorarioResponseDTO])
async def get_horarios(
    colaborador_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    r = await db.execute(select(HorarioColaboradorModel).where(HorarioColaboradorModel.colaborador_id == colaborador_id))
    return list(r.scalars().all())


@router.patch("/horarios/{colaborador_id}", response_model=List[HorarioResponseDTO])
async def set_horarios(
    colaborador_id: UUID,
    horarios: List[HorarioSetDTO],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_colaboradores")),
):
    r = await db.execute(select(HorarioColaboradorModel).where(HorarioColaboradorModel.colaborador_id == colaborador_id))
    for existente in r.scalars().all():
        await db.delete(existente)
    novos = [HorarioColaboradorModel(id=uuid4(), colaborador_id=colaborador_id, **h.model_dump()) for h in horarios]
    for n in novos:
        db.add(n)
    await db.commit()
    return novos


# ─── Ponto ───────────────────────────────────────────────────────────


class PontoCreateDTO(BaseModel):
    colaborador_id: UUID
    tipo: str = Field(..., pattern="^(entrada|saida)$")


class PontoResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    data_hora: datetime
    tipo: str
    origem: str

    class Config:
        from_attributes = True


@router.get("/ponto", response_model=List[PontoResponseDTO])
async def list_ponto(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(RegistoPontoModel)
    if colaborador_id:
        stmt = stmt.where(RegistoPontoModel.colaborador_id == colaborador_id)
    stmt = stmt.order_by(RegistoPontoModel.data_hora.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/ponto", response_model=PontoResponseDTO, status_code=201)
async def registar_ponto(
    body: PontoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.registar_ponto")),
):
    m = RegistoPontoModel(id=uuid4(), colaborador_id=body.colaborador_id, tipo=body.tipo, origem="manual")
    db.add(m)
    await db.commit()
    return m


# ─── Faltas ──────────────────────────────────────────────────────────


class FaltaCreateDTO(BaseModel):
    colaborador_id: UUID
    data: datetime
    tipo: str = Field(..., pattern="^(justificada|injustificada)$")
    motivo: Optional[str] = None


class FaltaResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    data: datetime
    tipo: str
    motivo: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/faltas", response_model=List[FaltaResponseDTO])
async def list_faltas(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(FaltaModel)
    if colaborador_id:
        stmt = stmt.where(FaltaModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/faltas", response_model=FaltaResponseDTO, status_code=201)
async def create_falta(
    body: FaltaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_colaboradores")),
):
    m = FaltaModel(id=uuid4(), **body.model_dump())
    db.add(m)
    await db.commit()
    return m


# ─── Férias ──────────────────────────────────────────────────────────


class FeriasCreateDTO(BaseModel):
    colaborador_id: UUID
    data_inicio: datetime
    data_fim: datetime
    dias: int = Field(..., gt=0)


class FeriasResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    data_inicio: datetime
    data_fim: datetime
    dias: int
    estado: str
    aprovador_id: Optional[UUID] = None
    motivo_rejeicao: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/ferias", response_model=List[FeriasResponseDTO])
async def list_ferias(
    colaborador_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(FeriasModel)
    if colaborador_id:
        stmt = stmt.where(FeriasModel.colaborador_id == colaborador_id)
    if estado:
        stmt = stmt.where(FeriasModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/ferias", response_model=FeriasResponseDTO, status_code=201)
async def create_ferias(
    body: FeriasCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    m = FeriasModel(id=uuid4(), estado="solicitada", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.post("/ferias/{id}/aprovar", response_model=FeriasResponseDTO)
async def aprovar_ferias(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.aprovar_ferias")),
):
    r = await db.execute(select(FeriasModel).where(FeriasModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Pedido de férias não encontrado")
    if m.estado != "solicitada":
        raise HTTPException(400, "Só é possível aprovar pedidos solicitados")
    m.estado = "aprovada"
    m.aprovador_id = current_user.id
    colr = await db.execute(select(ColaboradorModel).where(ColaboradorModel.id == m.colaborador_id))
    colaborador = colr.scalar_one_or_none()
    if colaborador:
        colaborador.estado = "ferias"
    await db.commit()
    return m


class RejeitarFeriasDTO(BaseModel):
    motivo: str = Field(..., min_length=1)


@router.post("/ferias/{id}/rejeitar", response_model=FeriasResponseDTO)
async def rejeitar_ferias(
    id: UUID,
    body: RejeitarFeriasDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.aprovar_ferias")),
):
    r = await db.execute(select(FeriasModel).where(FeriasModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Pedido de férias não encontrado")
    if m.estado != "solicitada":
        raise HTTPException(400, "Só é possível rejeitar pedidos solicitados")
    m.estado = "rejeitada"
    m.aprovador_id = current_user.id
    m.motivo_rejeicao = body.motivo
    await db.commit()
    return m


# ─── Horas Extra ─────────────────────────────────────────────────────


class HoraExtraCreateDTO(BaseModel):
    colaborador_id: UUID
    data: datetime
    horas: Decimal = Field(..., gt=0)
    tipo: str = Field(default="normal", pattern="^(normal|feriado|noturna)$")


class HoraExtraResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    data: datetime
    horas: Decimal
    tipo: str
    aprovado: bool

    class Config:
        from_attributes = True


@router.get("/horas-extra", response_model=List[HoraExtraResponseDTO])
async def list_horas_extra(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(HoraExtraModel)
    if colaborador_id:
        stmt = stmt.where(HoraExtraModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/horas-extra", response_model=HoraExtraResponseDTO, status_code=201)
async def create_hora_extra(
    body: HoraExtraCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    m = HoraExtraModel(id=uuid4(), aprovado=False, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.post("/horas-extra/{id}/aprovar", response_model=HoraExtraResponseDTO)
async def aprovar_hora_extra(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.aprovar_horas_extra")),
):
    r = await db.execute(select(HoraExtraModel).where(HoraExtraModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Registo de hora extra não encontrado")
    m.aprovado = True
    m.aprovador_id = current_user.id
    await db.commit()
    return m


# ─── Indicadores ─────────────────────────────────────────────────────


@router.get("/indicadores/assiduidade")
async def indicador_assiduidade(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(ColaboradorModel).where(ColaboradorModel.company_id == current_user.company_id).where(ColaboradorModel.deleted_at.is_(None))
    if colaborador_id:
        stmt = stmt.where(ColaboradorModel.id == colaborador_id)
    r = await db.execute(stmt)
    colaboradores = list(r.scalars().all())

    resultado = []
    for c in colaboradores:
        fr = await db.execute(select(FaltaModel).where(FaltaModel.colaborador_id == c.id))
        n_faltas = len(list(fr.scalars().all()))
        resultado.append({"colaborador_id": str(c.id), "nome": c.nome, "faltas_registadas": n_faltas})
    return resultado


__all__ = ["router"]
