"""Recursos Humanos (domínio Capital Humano): Departamentos, Colaboradores,
Contratos, Organograma."""
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
from app.infrastructure.database.models import ColaboradorModel, ContratoRHModel, DepartamentoModel


router = APIRouter()


# ─── Departamentos ───────────────────────────────────────────────────


class DepartamentoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    responsavel_id: Optional[UUID] = None


class DepartamentoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    responsavel_id: Optional[UUID] = None

    class Config:
        from_attributes = True


@router.get("/departamentos", response_model=List[DepartamentoResponseDTO])
async def list_departamentos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    r = await db.execute(
        select(DepartamentoModel)
        .where(DepartamentoModel.company_id == current_user.company_id)
        .where(DepartamentoModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/departamentos", response_model=DepartamentoResponseDTO, status_code=201)
async def create_departamento(
    body: DepartamentoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_departamentos")),
):
    m = DepartamentoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/departamentos/{id}", status_code=204)
async def delete_departamento(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_departamentos")),
):
    r = await db.execute(select(DepartamentoModel).where(DepartamentoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Departamento não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Colaboradores ───────────────────────────────────────────────────


class ColaboradorCreateDTO(BaseModel):
    user_id: Optional[UUID] = None
    nome: str = Field(..., min_length=1, max_length=150)
    cargo: Optional[str] = None
    departamento_id: Optional[UUID] = None
    data_admissao: datetime
    salario_base: Decimal = Field(default=Decimal("0"), ge=0)
    superior_id: Optional[UUID] = None
    telefone: Optional[str] = None
    email_pessoal: Optional[str] = None


class ColaboradorUpdateDTO(BaseModel):
    cargo: Optional[str] = None
    departamento_id: Optional[UUID] = None
    salario_base: Optional[Decimal] = None
    estado: Optional[str] = Field(None, pattern="^(ativo|ferias|licenca|desligado)$")
    superior_id: Optional[UUID] = None
    data_desligamento: Optional[datetime] = None


class ColaboradorResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    user_id: Optional[UUID] = None
    nome: str
    cargo: Optional[str] = None
    departamento_id: Optional[UUID] = None
    data_admissao: datetime
    data_desligamento: Optional[datetime] = None
    salario_base: Decimal
    estado: str
    superior_id: Optional[UUID] = None
    telefone: Optional[str] = None
    email_pessoal: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/colaboradores", response_model=List[ColaboradorResponseDTO])
async def list_colaboradores(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    stmt = (
        select(ColaboradorModel)
        .where(ColaboradorModel.company_id == current_user.company_id)
        .where(ColaboradorModel.deleted_at.is_(None))
    )
    if estado:
        stmt = stmt.where(ColaboradorModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/colaboradores", response_model=ColaboradorResponseDTO, status_code=201)
async def create_colaborador(
    body: ColaboradorCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_colaboradores")),
):
    m = ColaboradorModel(id=uuid4(), company_id=current_user.company_id, estado="ativo", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/colaboradores/{id}", response_model=ColaboradorResponseDTO)
async def update_colaborador(
    id: UUID,
    body: ColaboradorUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_colaboradores")),
):
    r = await db.execute(select(ColaboradorModel).where(ColaboradorModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Colaborador não encontrado")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.commit()
    return m


@router.delete("/colaboradores/{id}", status_code=204)
async def delete_colaborador(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_colaboradores")),
):
    r = await db.execute(select(ColaboradorModel).where(ColaboradorModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Colaborador não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


@router.get("/organograma")
async def organograma(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    r = await db.execute(
        select(ColaboradorModel)
        .where(ColaboradorModel.company_id == current_user.company_id)
        .where(ColaboradorModel.deleted_at.is_(None))
    )
    colaboradores = list(r.scalars().all())
    by_id = {str(c.id): {"id": str(c.id), "nome": c.nome, "cargo": c.cargo, "subordinados": []} for c in colaboradores}
    raizes = []
    for c in colaboradores:
        node = by_id[str(c.id)]
        if c.superior_id and str(c.superior_id) in by_id:
            by_id[str(c.superior_id)]["subordinados"].append(node)
        else:
            raizes.append(node)
    return raizes


# ─── Contratos ───────────────────────────────────────────────────────


class ContratoCreateDTO(BaseModel):
    tipo: str = Field(..., pattern="^(efetivo|termo|estagio|prestacao_servico)$")
    data_inicio: datetime
    data_fim: Optional[datetime] = None
    arquivo_url: Optional[str] = None


class ContratoResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    tipo: str
    data_inicio: datetime
    data_fim: Optional[datetime] = None
    arquivo_url: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/colaboradores/{colaborador_id}/contratos", response_model=List[ContratoResponseDTO])
async def list_contratos(
    colaborador_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.view")),
):
    r = await db.execute(select(ContratoRHModel).where(ContratoRHModel.colaborador_id == colaborador_id))
    return list(r.scalars().all())


@router.post("/colaboradores/{colaborador_id}/contratos", response_model=ContratoResponseDTO, status_code=201)
async def create_contrato(
    colaborador_id: UUID,
    body: ContratoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.gerir_contratos")),
):
    cr = await db.execute(
        select(ColaboradorModel).where(ColaboradorModel.id == colaborador_id).where(ColaboradorModel.company_id == current_user.company_id)
    )
    if not cr.scalar_one_or_none():
        raise HTTPException(404, "Colaborador não encontrado")
    m = ContratoRHModel(id=uuid4(), colaborador_id=colaborador_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


__all__ = ["router"]
