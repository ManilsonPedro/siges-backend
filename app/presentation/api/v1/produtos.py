"""CRUD de Produtos e Categorias de Produto."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.database import get_db
from app.infrastructure.database.models import ProdutoCategoriaModel, ProdutoModel


router = APIRouter()


# ─── DTOs ────────────────────────────────────────────────────────────

UNIDADES = "^(L|kg|m3|un|cx)$"


class CategoriaCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    ordem: int = 0
    estado: str = Field(default="ativo", pattern="^(ativo|inativo)$")


class CategoriaUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=120)
    ordem: Optional[int] = None
    estado: Optional[str] = Field(None, pattern="^(ativo|inativo)$")


class CategoriaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    ordem: int
    estado: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProdutoCreateDTO(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    nome: str = Field(..., min_length=1, max_length=255)
    marca: Optional[str] = Field(None, max_length=100)
    categoria_id: Optional[UUID] = None
    unidade_medida: str = Field(default="un", pattern=UNIDADES)
    preco_base: Decimal = Field(default=Decimal("0"), ge=0)
    iva_pct: Decimal = Field(default=Decimal("14"), ge=0, le=100)
    descricao: Optional[str] = None
    activo: bool = True


class ProdutoUpdateDTO(BaseModel):
    sku: Optional[str] = Field(None, min_length=1, max_length=50)
    nome: Optional[str] = Field(None, min_length=1, max_length=255)
    marca: Optional[str] = Field(None, max_length=100)
    categoria_id: Optional[UUID] = None
    unidade_medida: Optional[str] = Field(None, pattern=UNIDADES)
    preco_base: Optional[Decimal] = Field(None, ge=0)
    iva_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    descricao: Optional[str] = None
    activo: Optional[bool] = None


class ProdutoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    sku: str
    nome: str
    marca: Optional[str] = None
    categoria_id: Optional[UUID] = None
    unidade_medida: str
    preco_base: Decimal
    iva_pct: Decimal
    descricao: Optional[str] = None
    activo: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─── Helpers ─────────────────────────────────────────────────────────


def _prod_dict(p: ProdutoModel) -> dict:
    return {
        "id": str(p.id), "sku": p.sku, "nome": p.nome, "marca": p.marca,
        "categoria_id": str(p.categoria_id) if p.categoria_id else None,
        "unidade_medida": p.unidade_medida, "preco_base": str(p.preco_base),
        "iva_pct": str(p.iva_pct), "activo": p.activo,
    }


# ─── Categorias ──────────────────────────────────────────────────────


@router.get("/categorias", response_model=List[CategoriaResponseDTO])
async def list_categorias(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(ProdutoCategoriaModel)
        .where(ProdutoCategoriaModel.company_id == current_user.company_id)
        .where(ProdutoCategoriaModel.deleted_at.is_(None))
        .order_by(ProdutoCategoriaModel.ordem, ProdutoCategoriaModel.nome)
    )
    return list(r.scalars().all())


@router.post("/categorias", response_model=CategoriaResponseDTO, status_code=201)
async def create_categoria(
    req: Request,
    body: CategoriaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = ProdutoCategoriaModel(
        id=uuid4(), company_id=current_user.company_id,
        nome=body.nome, ordem=body.ordem, estado=body.estado,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "produto_categoria", m.id,
        dados_novos={"nome": m.nome},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.patch("/categorias/{id}", response_model=CategoriaResponseDTO)
async def update_categoria(
    id: UUID,
    body: CategoriaUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ProdutoCategoriaModel).where(ProdutoCategoriaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Categoria não encontrada")
    if body.nome is not None:
        m.nome = body.nome
    if body.ordem is not None:
        m.ordem = body.ordem
    if body.estado is not None:
        m.estado = body.estado
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


@router.delete("/categorias/{id}", status_code=204)
async def delete_categoria(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ProdutoCategoriaModel).where(ProdutoCategoriaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Categoria não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Produtos ────────────────────────────────────────────────────────


@router.get("", response_model=List[ProdutoResponseDTO])
async def list_produtos(
    q: Optional[str] = Query(None, description="Busca por nome, sku ou marca"),
    categoria_id: Optional[UUID] = None,
    activo: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(ProdutoModel)
        .where(ProdutoModel.company_id == current_user.company_id)
        .where(ProdutoModel.deleted_at.is_(None))
    )
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(ProdutoModel.nome).like(like),
                func.lower(ProdutoModel.sku).like(like),
                func.lower(ProdutoModel.marca).like(like),
            )
        )
    if categoria_id is not None:
        stmt = stmt.where(ProdutoModel.categoria_id == str(categoria_id))
    if activo is not None:
        stmt = stmt.where(ProdutoModel.activo == activo)
    stmt = stmt.order_by(ProdutoModel.nome).offset((page - 1) * page_size).limit(page_size)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.get("/{id}", response_model=ProdutoResponseDTO)
async def get_produto(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ProdutoModel).where(ProdutoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Produto não encontrado")
    return m


@router.post("", response_model=ProdutoResponseDTO, status_code=201)
async def create_produto(
    req: Request,
    body: ProdutoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = await db.execute(
        select(ProdutoModel)
        .where(ProdutoModel.company_id == current_user.company_id)
        .where(ProdutoModel.sku == body.sku)
        .where(ProdutoModel.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Já existe produto com SKU '{body.sku}'")

    m = ProdutoModel(
        id=uuid4(),
        company_id=current_user.company_id,
        sku=body.sku, nome=body.nome, marca=body.marca,
        categoria_id=str(body.categoria_id) if body.categoria_id else None,
        unidade_medida=body.unidade_medida,
        preco_base=body.preco_base, iva_pct=body.iva_pct,
        descricao=body.descricao, activo=body.activo,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "produto", m.id,
        dados_novos=_prod_dict(m),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.patch("/{id}", response_model=ProdutoResponseDTO)
async def update_produto(
    id: UUID,
    req: Request,
    body: ProdutoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ProdutoModel).where(ProdutoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Produto não encontrado")

    dados_ant = _prod_dict(m)
    if body.sku is not None and body.sku != m.sku:
        clash = await db.execute(
            select(ProdutoModel)
            .where(ProdutoModel.company_id == current_user.company_id)
            .where(ProdutoModel.sku == body.sku)
            .where(ProdutoModel.id != id)
            .where(ProdutoModel.deleted_at.is_(None))
        )
        if clash.scalar_one_or_none():
            raise HTTPException(409, f"Já existe outro produto com SKU '{body.sku}'")
        m.sku = body.sku
    if body.nome is not None:
        m.nome = body.nome
    if body.marca is not None:
        m.marca = body.marca
    if body.categoria_id is not None:
        m.categoria_id = str(body.categoria_id)
    if body.unidade_medida is not None:
        m.unidade_medida = body.unidade_medida
    if body.preco_base is not None:
        m.preco_base = body.preco_base
    if body.iva_pct is not None:
        m.iva_pct = body.iva_pct
    if body.descricao is not None:
        m.descricao = body.descricao
    if body.activo is not None:
        m.activo = body.activo
    m.updated_at = datetime.utcnow()

    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizado", "produto", m.id,
        dados_anteriores=dados_ant, dados_novos=_prod_dict(m),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.delete("/{id}", status_code=204)
async def delete_produto(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ProdutoModel).where(ProdutoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Produto não encontrado")
    dados_ant = _prod_dict(m)
    m.deleted_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "eliminado", "produto", m.id,
        dados_anteriores=dados_ant,
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


@router.post("/{id}/restore", response_model=ProdutoResponseDTO)
async def restore_produto(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(ProdutoModel).where(ProdutoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Produto não encontrado")
    m.deleted_at = None
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


__all__ = ["router"]
