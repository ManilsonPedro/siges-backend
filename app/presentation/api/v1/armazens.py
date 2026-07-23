"""CRUD de Armazéns (multi-armazém — decisão D3 docs/05)."""
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
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.database import get_db
from app.infrastructure.database.models import ArmazemModel


router = APIRouter()


class ArmazemCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=20)
    nome: str = Field(..., min_length=1, max_length=120)
    morada: Optional[str] = None
    activo: bool = True


class ArmazemUpdateDTO(BaseModel):
    codigo: Optional[str] = Field(None, min_length=1, max_length=20)
    nome: Optional[str] = Field(None, min_length=1, max_length=120)
    morada: Optional[str] = None
    activo: Optional[bool] = None


class ArmazemResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    nome: str
    morada: Optional[str] = None
    activo: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[ArmazemResponseDTO])
async def list_armazens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(ArmazemModel)
        .where(ArmazemModel.company_id == current_user.company_id)
        .where(ArmazemModel.deleted_at.is_(None))
        .order_by(ArmazemModel.codigo)
    )
    return list(r.scalars().all())


@router.post("", response_model=ArmazemResponseDTO, status_code=201)
async def create_armazem(
    req: Request,
    body: ArmazemCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    clash = await db.execute(
        select(ArmazemModel)
        .where(ArmazemModel.company_id == current_user.company_id)
        .where(ArmazemModel.codigo == body.codigo)
        .where(ArmazemModel.deleted_at.is_(None))
    )
    if clash.scalar_one_or_none():
        raise HTTPException(409, f"Já existe armazém com código '{body.codigo}'")

    m = ArmazemModel(
        id=uuid4(), company_id=current_user.company_id,
        codigo=body.codigo, nome=body.nome,
        morada=body.morada, activo=body.activo,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "armazem", m.id,
        dados_novos={"codigo": m.codigo, "nome": m.nome},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.patch("/{id}", response_model=ArmazemResponseDTO)
async def update_armazem(
    id: UUID,
    body: ArmazemUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ArmazemModel).where(ArmazemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Armazém não encontrado")

    if body.codigo is not None:
        m.codigo = body.codigo
    if body.nome is not None:
        m.nome = body.nome
    if body.morada is not None:
        m.morada = body.morada
    if body.activo is not None:
        m.activo = body.activo
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


@router.delete("/{id}", status_code=204)
async def delete_armazem(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ArmazemModel).where(ArmazemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Armazém não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


__all__ = ["router"]
