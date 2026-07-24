"""Catálogo de referência de Veículo: Marca, Modelo, Cor (domínio
Operações · Lavagem). Alimenta os dropdowns de Viatura no backoffice e
no portal do cliente — ViaturaModel.marca/modelo/cor continuam a ser
texto livre (compatibilidade), este catálogo só sugere/preenche esses
campos, não é FK obrigatória.
"""
from __future__ import annotations

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
from app.infrastructure.database.models import (
    CorVeiculoModel,
    MarcaVeiculoModel,
    ModeloVeiculoModel,
)

router = APIRouter()


# ─── Marcas ───────────────────────────────────────────────────────────


class MarcaVeiculoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    activo: bool = True


class MarcaVeiculoUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=60)
    activo: Optional[bool] = None


class MarcaVeiculoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    activo: bool

    class Config:
        from_attributes = True


@router.get("/marcas", response_model=List[MarcaVeiculoResponseDTO])
async def list_marcas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    r = await db.execute(
        select(MarcaVeiculoModel)
        .where(MarcaVeiculoModel.company_id == current_user.company_id)
        .where(MarcaVeiculoModel.deleted_at.is_(None))
        .order_by(MarcaVeiculoModel.nome)
    )
    return list(r.scalars().all())


@router.post("/marcas", response_model=MarcaVeiculoResponseDTO, status_code=201)
async def create_marca(
    body: MarcaVeiculoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = MarcaVeiculoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/marcas/{id}", response_model=MarcaVeiculoResponseDTO)
async def update_marca(
    id: UUID,
    body: MarcaVeiculoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(MarcaVeiculoModel).where(MarcaVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Marca não encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await db.commit()
    return m


@router.delete("/marcas/{id}", status_code=204)
async def delete_marca(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(MarcaVeiculoModel).where(MarcaVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Marca não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Modelos ──────────────────────────────────────────────────────────


class ModeloVeiculoCreateDTO(BaseModel):
    marca_id: UUID
    nome: str = Field(..., min_length=1, max_length=60)
    activo: bool = True


class ModeloVeiculoUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=60)
    activo: Optional[bool] = None


class ModeloVeiculoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    marca_id: UUID
    nome: str
    activo: bool

    class Config:
        from_attributes = True


@router.get("/modelos", response_model=List[ModeloVeiculoResponseDTO])
async def list_modelos(
    marca_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    stmt = (
        select(ModeloVeiculoModel)
        .where(ModeloVeiculoModel.company_id == current_user.company_id)
        .where(ModeloVeiculoModel.deleted_at.is_(None))
    )
    if marca_id:
        stmt = stmt.where(ModeloVeiculoModel.marca_id == marca_id)
    stmt = stmt.order_by(ModeloVeiculoModel.nome)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/modelos", response_model=ModeloVeiculoResponseDTO, status_code=201)
async def create_modelo(
    body: ModeloVeiculoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    mr = await db.execute(select(MarcaVeiculoModel).where(MarcaVeiculoModel.id == body.marca_id))
    marca = mr.scalar_one_or_none()
    if not marca or marca.company_id != current_user.company_id:
        raise HTTPException(404, "Marca não encontrada")

    m = ModeloVeiculoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/modelos/{id}", response_model=ModeloVeiculoResponseDTO)
async def update_modelo(
    id: UUID,
    body: ModeloVeiculoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(ModeloVeiculoModel).where(ModeloVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Modelo não encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await db.commit()
    return m


@router.delete("/modelos/{id}", status_code=204)
async def delete_modelo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(ModeloVeiculoModel).where(ModeloVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Modelo não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Cores ────────────────────────────────────────────────────────────


class CorVeiculoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=30)
    hex: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    activo: bool = True


class CorVeiculoUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=30)
    hex: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    activo: Optional[bool] = None


class CorVeiculoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    hex: Optional[str] = None
    activo: bool

    class Config:
        from_attributes = True


@router.get("/cores", response_model=List[CorVeiculoResponseDTO])
async def list_cores(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    r = await db.execute(
        select(CorVeiculoModel)
        .where(CorVeiculoModel.company_id == current_user.company_id)
        .where(CorVeiculoModel.deleted_at.is_(None))
        .order_by(CorVeiculoModel.nome)
    )
    return list(r.scalars().all())


@router.post("/cores", response_model=CorVeiculoResponseDTO, status_code=201)
async def create_cor(
    body: CorVeiculoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = CorVeiculoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/cores/{id}", response_model=CorVeiculoResponseDTO)
async def update_cor(
    id: UUID,
    body: CorVeiculoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(CorVeiculoModel).where(CorVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Cor não encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await db.commit()
    return m


@router.delete("/cores/{id}", status_code=204)
async def delete_cor(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(CorVeiculoModel).where(CorVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Cor não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


__all__ = ["router"]
