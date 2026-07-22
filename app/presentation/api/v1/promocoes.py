"""Promoções de produtos/categorias (domínio Comércio / Loja).

Não substitui o mecanismo de desconto por linha já existente no Caixa
(venda_linhas.desconto_pct) — apenas calcula, a partir das promoções
activas, qual desconto_pct sugerir para um produto num dado momento.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import ProdutoModel, PromocaoModel


router = APIRouter()


class PromocaoCreateDTO(BaseModel):
    produto_id: Optional[UUID] = None
    categoria_id: Optional[str] = None
    tipo: str = Field(..., pattern="^(percentual|valor_fixo)$")
    valor: Decimal = Field(..., gt=0)
    data_inicio: datetime
    data_fim: datetime
    activo: bool = True

    @model_validator(mode="after")
    def _valida_alvo(self):
        if not self.produto_id and not self.categoria_id:
            raise ValueError("Indique produto_id ou categoria_id")
        if self.data_fim <= self.data_inicio:
            raise ValueError("data_fim tem de ser posterior a data_inicio")
        return self


class PromocaoUpdateDTO(BaseModel):
    valor: Optional[Decimal] = Field(None, gt=0)
    data_inicio: Optional[datetime] = None
    data_fim: Optional[datetime] = None
    activo: Optional[bool] = None


class PromocaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    produto_id: Optional[UUID] = None
    categoria_id: Optional[str] = None
    tipo: str
    valor: Decimal
    data_inicio: datetime
    data_fim: datetime
    activo: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[PromocaoResponseDTO])
async def list_promocoes(
    activo: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("loja.view")),
):
    stmt = (
        select(PromocaoModel)
        .where(PromocaoModel.company_id == current_user.company_id)
        .where(PromocaoModel.deleted_at.is_(None))
    )
    if activo is not None:
        stmt = stmt.where(PromocaoModel.activo == activo)
    stmt = stmt.order_by(PromocaoModel.data_inicio.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("", response_model=PromocaoResponseDTO, status_code=201)
async def create_promocao(
    req: Request,
    body: PromocaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("loja.gerir_promocoes")),
):
    if body.produto_id:
        pr = await db.execute(
            select(ProdutoModel)
            .where(ProdutoModel.id == body.produto_id)
            .where(ProdutoModel.company_id == current_user.company_id)
        )
        if not pr.scalar_one_or_none():
            raise HTTPException(404, "Produto não encontrado")

    m = PromocaoModel(
        id=uuid4(), company_id=current_user.company_id,
        produto_id=body.produto_id, categoria_id=body.categoria_id,
        tipo=body.tipo, valor=body.valor,
        data_inicio=body.data_inicio, data_fim=body.data_fim, activo=body.activo,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "promocao", m.id,
        dados_novos={"tipo": body.tipo, "valor": str(body.valor)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.patch("/{id}", response_model=PromocaoResponseDTO)
async def update_promocao(
    id: UUID,
    body: PromocaoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("loja.gerir_promocoes")),
):
    r = await db.execute(select(PromocaoModel).where(PromocaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Promoção não encontrada")

    if body.valor is not None:
        m.valor = body.valor
    if body.data_inicio is not None:
        m.data_inicio = body.data_inicio
    if body.data_fim is not None:
        m.data_fim = body.data_fim
    if body.activo is not None:
        m.activo = body.activo
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


@router.delete("/{id}", status_code=204)
async def delete_promocao(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("loja.gerir_promocoes")),
):
    r = await db.execute(select(PromocaoModel).where(PromocaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Promoção não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


@router.get("/desconto-sugerido/{produto_id}")
async def desconto_sugerido(
    produto_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("loja.view")),
):
    """Consulta usada pelo Caixa para sugerir desconto_pct/valor a aplicar
    a partir das promoções activas no momento, para o produto ou sua
    categoria. Não aplica nada automaticamente — devolve a sugestão."""
    pr = await db.execute(
        select(ProdutoModel)
        .where(ProdutoModel.id == produto_id)
        .where(ProdutoModel.company_id == current_user.company_id)
    )
    prod = pr.scalar_one_or_none()
    if not prod:
        raise HTTPException(404, "Produto não encontrado")

    agora = datetime.utcnow()
    stmt = (
        select(PromocaoModel)
        .where(PromocaoModel.company_id == current_user.company_id)
        .where(PromocaoModel.deleted_at.is_(None))
        .where(PromocaoModel.activo.is_(True))
        .where(PromocaoModel.data_inicio <= agora)
        .where(PromocaoModel.data_fim >= agora)
        .where(or_(
            PromocaoModel.produto_id == produto_id,
            PromocaoModel.categoria_id == prod.categoria_id,
        ))
        .order_by(PromocaoModel.valor.desc())
    )
    r = await db.execute(stmt)
    melhor = r.scalars().first()
    if not melhor:
        return {"tem_promocao": False, "desconto_pct": 0}

    if melhor.tipo == "percentual":
        return {"tem_promocao": True, "promocao_id": str(melhor.id), "desconto_pct": float(melhor.valor)}
    # valor_fixo: converte para percentagem equivalente sobre o preço base
    preco_base = Decimal(prod.preco_base) or Decimal("1")
    pct = min(Decimal("100"), (Decimal(melhor.valor) / preco_base) * Decimal("100"))
    return {"tem_promocao": True, "promocao_id": str(melhor.id), "desconto_pct": float(pct.quantize(Decimal("0.01")))}


__all__ = ["router"]
