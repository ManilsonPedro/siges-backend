"""Pedidos de Compra (Ordens de Compra) a fornecedores."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import PedidoCompraLinhaModel, PedidoCompraModel


router = APIRouter()


class PedidoLinhaResponseDTO(BaseModel):
    id: UUID
    produto_id: UUID
    quantidade: Decimal
    quantidade_recebida: Decimal
    preco_unitario: Decimal

    class Config:
        from_attributes = True


class PedidoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    requisicao_id: Optional[UUID] = None
    fornecedor_id: UUID
    numero: str
    data: datetime
    estado: str
    total: Decimal
    ref_externa: Optional[str] = None
    linhas: List[PedidoLinhaResponseDTO] = []
    created_at: datetime

    class Config:
        from_attributes = True


async def _to_response(db: AsyncSession, p: PedidoCompraModel) -> PedidoResponseDTO:
    lr = await db.execute(select(PedidoCompraLinhaModel).where(PedidoCompraLinhaModel.pedido_id == p.id))
    dto = PedidoResponseDTO.model_validate(p)
    dto.linhas = [PedidoLinhaResponseDTO.model_validate(l) for l in lr.scalars().all()]
    return dto


@router.get("", response_model=List[PedidoResponseDTO])
async def list_pedidos(
    estado: Optional[str] = None,
    fornecedor_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.ver")),
):
    stmt = (
        select(PedidoCompraModel)
        .where(PedidoCompraModel.company_id == current_user.company_id)
        .where(PedidoCompraModel.deleted_at.is_(None))
    )
    if estado:
        stmt = stmt.where(PedidoCompraModel.estado == estado)
    if fornecedor_id:
        stmt = stmt.where(PedidoCompraModel.fornecedor_id == fornecedor_id)
    stmt = stmt.order_by(PedidoCompraModel.created_at.desc())
    r = await db.execute(stmt)
    return [await _to_response(db, p) for p in r.scalars().all()]


@router.get("/{id}", response_model=PedidoResponseDTO)
async def get_pedido(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.ver")),
):
    r = await db.execute(select(PedidoCompraModel).where(PedidoCompraModel.id == id))
    p = r.scalar_one_or_none()
    if not p or p.company_id != current_user.company_id:
        raise HTTPException(404, "Pedido não encontrado")
    return await _to_response(db, p)


@router.post("/{id}/confirmar", response_model=PedidoResponseDTO)
async def confirmar_pedido(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.gerir_pedidos")),
):
    r = await db.execute(select(PedidoCompraModel).where(PedidoCompraModel.id == id))
    p = r.scalar_one_or_none()
    if not p or p.company_id != current_user.company_id:
        raise HTTPException(404, "Pedido não encontrado")
    if p.estado != "enviado":
        raise HTTPException(400, "Só é possível confirmar pedidos enviados")
    p.estado = "confirmado"
    p.updated_at = datetime.utcnow()
    await db.commit()
    return await _to_response(db, p)


__all__ = ["router"]
