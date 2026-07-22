"""Avaliação (domínio Capital Humano): Objetivos, Competências, Avaliações, Formação."""
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
    AvaliacaoRHModel,
    ColaboradorModel,
    CompetenciaModel,
    FormacaoModel,
    ObjetivoModel,
)


router = APIRouter()


# ─── Objetivos ───────────────────────────────────────────────────────


class ObjetivoCreateDTO(BaseModel):
    colaborador_id: UUID
    periodo: str = Field(..., min_length=1, max_length=10)
    descricao: str = Field(..., min_length=1)
    meta: Optional[str] = None


class ObjetivoUpdateDTO(BaseModel):
    progresso_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    estado: Optional[str] = Field(None, pattern="^(em_curso|atingido|nao_atingido)$")


class ObjetivoResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    periodo: str
    descricao: str
    meta: Optional[str] = None
    progresso_pct: Decimal
    estado: str

    class Config:
        from_attributes = True


@router.get("/objetivos", response_model=List[ObjetivoResponseDTO])
async def list_objetivos(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(ObjetivoModel)
    if colaborador_id:
        stmt = stmt.where(ObjetivoModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/objetivos", response_model=ObjetivoResponseDTO, status_code=201)
async def create_objetivo(
    body: ObjetivoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_objetivos")),
):
    m = ObjetivoModel(id=uuid4(), progresso_pct=Decimal("0"), estado="em_curso", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/objetivos/{id}", response_model=ObjetivoResponseDTO)
async def update_objetivo(
    id: UUID,
    body: ObjetivoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_objetivos")),
):
    r = await db.execute(select(ObjetivoModel).where(ObjetivoModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Objetivo não encontrado")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.commit()
    return m


# ─── Competências ────────────────────────────────────────────────────


class CompetenciaCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    descricao: Optional[str] = None


class CompetenciaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    descricao: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/competencias", response_model=List[CompetenciaResponseDTO])
async def list_competencias(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    r = await db.execute(select(CompetenciaModel).where(CompetenciaModel.company_id == current_user.company_id))
    return list(r.scalars().all())


@router.post("/competencias", response_model=CompetenciaResponseDTO, status_code=201)
async def create_competencia(
    body: CompetenciaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_objetivos")),
):
    m = CompetenciaModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/competencias/{id}", status_code=204)
async def delete_competencia(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_objetivos")),
):
    r = await db.execute(select(CompetenciaModel).where(CompetenciaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Competência não encontrada")
    await db.delete(m)
    await db.commit()


# ─── Avaliações ──────────────────────────────────────────────────────


class AvaliacaoCreateDTO(BaseModel):
    colaborador_id: UUID
    periodo: str = Field(..., min_length=1, max_length=10)
    nota_geral: Decimal = Field(..., ge=0, le=5)
    pontos_fortes: Optional[str] = None
    pontos_melhorar: Optional[str] = None


class AvaliacaoResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    periodo: str
    avaliador_id: Optional[UUID] = None
    nota_geral: Decimal
    pontos_fortes: Optional[str] = None
    pontos_melhorar: Optional[str] = None
    data: datetime

    class Config:
        from_attributes = True


@router.get("/avaliacoes", response_model=List[AvaliacaoResponseDTO])
async def list_avaliacoes(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(AvaliacaoRHModel)
    if colaborador_id:
        stmt = stmt.where(AvaliacaoRHModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.get("/avaliacoes/{id}", response_model=AvaliacaoResponseDTO)
async def get_avaliacao(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    r = await db.execute(select(AvaliacaoRHModel).where(AvaliacaoRHModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Avaliação não encontrada")
    return m


@router.post("/avaliacoes", response_model=AvaliacaoResponseDTO, status_code=201)
async def create_avaliacao(
    body: AvaliacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.avaliar")),
):
    m = AvaliacaoRHModel(id=uuid4(), avaliador_id=current_user.id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


# ─── Formações ───────────────────────────────────────────────────────


class FormacaoCreateDTO(BaseModel):
    colaborador_id: UUID
    nome: str = Field(..., min_length=1, max_length=150)
    instituicao: Optional[str] = None
    data_inicio: Optional[datetime] = None
    data_fim: Optional[datetime] = None
    certificado_url: Optional[str] = None


class FormacaoResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    nome: str
    instituicao: Optional[str] = None
    data_inicio: Optional[datetime] = None
    data_fim: Optional[datetime] = None
    certificado_url: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/formacoes", response_model=List[FormacaoResponseDTO])
async def list_formacoes(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(FormacaoModel)
    if colaborador_id:
        stmt = stmt.where(FormacaoModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/formacoes", response_model=FormacaoResponseDTO, status_code=201)
async def create_formacao(
    body: FormacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_formacoes")),
):
    m = FormacaoModel(id=uuid4(), **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.get("/indicadores/produtividade")
async def indicador_produtividade(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = select(ObjetivoModel)
    if colaborador_id:
        stmt = stmt.where(ObjetivoModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    objetivos = list(r.scalars().all())
    if not objetivos:
        return {"media_progresso_pct": 0, "n_objetivos": 0}
    media = sum((Decimal(o.progresso_pct) for o in objetivos), Decimal("0")) / len(objetivos)
    return {"media_progresso_pct": float(media.quantize(Decimal("0.01"))), "n_objetivos": len(objetivos)}


__all__ = ["router"]
