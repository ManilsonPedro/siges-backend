"""Receção de mercadoria de um Pedido de Compra.

Confirmar uma receção gera StockMovimento(s) de entrada_compra via
app.domain.services.stock_service — nunca escreve directamente em
StockSaldoModel (mesma invariante já validada no módulo Estoque).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.domain.services import stock_service
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    ArmazemModel,
    PedidoCompraLinhaModel,
    PedidoCompraModel,
    RecepcaoLinhaModel,
    RecepcaoModel,
)


router = APIRouter()


class RecepcaoLinhaInDTO(BaseModel):
    pedido_linha_id: UUID
    quantidade_recebida: Decimal = Field(..., ge=0)


class RecepcaoCreateDTO(BaseModel):
    pedido_id: UUID
    armazem_id: UUID
    linhas: List[RecepcaoLinhaInDTO] = Field(..., min_length=1)


class RecepcaoLinhaResponseDTO(BaseModel):
    id: UUID
    pedido_linha_id: UUID
    produto_id: UUID
    quantidade_esperada: Decimal
    quantidade_recebida: Decimal

    class Config:
        from_attributes = True


class RecepcaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    pedido_id: UUID
    armazem_id: UUID
    data: datetime
    estado: str
    linhas: List[RecepcaoLinhaResponseDTO] = []
    created_at: datetime

    class Config:
        from_attributes = True


async def _to_response(db: AsyncSession, r: RecepcaoModel) -> RecepcaoResponseDTO:
    lr = await db.execute(select(RecepcaoLinhaModel).where(RecepcaoLinhaModel.recepcao_id == r.id))
    dto = RecepcaoResponseDTO.model_validate(r)
    dto.linhas = [RecepcaoLinhaResponseDTO.model_validate(l) for l in lr.scalars().all()]
    return dto


@router.get("", response_model=List[RecepcaoResponseDTO])
async def list_recepcoes(
    pedido_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.ver")),
):
    stmt = select(RecepcaoModel).where(RecepcaoModel.company_id == current_user.company_id)
    if pedido_id:
        stmt = stmt.where(RecepcaoModel.pedido_id == pedido_id)
    stmt = stmt.order_by(RecepcaoModel.created_at.desc())
    r = await db.execute(stmt)
    return [await _to_response(db, x) for x in r.scalars().all()]


@router.post("", response_model=RecepcaoResponseDTO, status_code=201)
async def create_recepcao(
    req: Request,
    body: RecepcaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.receber")),
):
    pedido_r = await db.execute(
        select(PedidoCompraModel)
        .where(PedidoCompraModel.id == body.pedido_id)
        .where(PedidoCompraModel.company_id == current_user.company_id)
    )
    pedido = pedido_r.scalar_one_or_none()
    if not pedido:
        raise HTTPException(404, "Pedido não encontrado")
    if pedido.estado not in ("confirmado", "parcialmente_recebido"):
        raise HTTPException(400, "Pedido tem de estar confirmado para receber")

    arm_r = await db.execute(
        select(ArmazemModel)
        .where(ArmazemModel.id == body.armazem_id)
        .where(ArmazemModel.company_id == current_user.company_id)
        .where(ArmazemModel.deleted_at.is_(None))
    )
    if not arm_r.scalar_one_or_none():
        raise HTTPException(404, "Armazém não encontrado")

    rec = RecepcaoModel(
        id=uuid4(), company_id=current_user.company_id, pedido_id=pedido.id,
        armazem_id=body.armazem_id, estado="rascunho", responsavel_id=current_user.id,
    )
    db.add(rec)
    await db.flush()

    for linha_in in body.linhas:
        pl_r = await db.execute(
            select(PedidoCompraLinhaModel).where(PedidoCompraLinhaModel.id == linha_in.pedido_linha_id)
        )
        pl = pl_r.scalar_one_or_none()
        if not pl or pl.pedido_id != pedido.id:
            raise HTTPException(400, f"Linha de pedido inválida: {linha_in.pedido_linha_id}")
        pendente = Decimal(pl.quantidade) - Decimal(pl.quantidade_recebida)
        if linha_in.quantidade_recebida > pendente:
            raise HTTPException(400, f"Quantidade recebida excede pendente ({pendente}) para produto {pl.produto_id}")

        db.add(RecepcaoLinhaModel(
            id=uuid4(), recepcao_id=rec.id, pedido_linha_id=pl.id, produto_id=pl.produto_id,
            quantidade_esperada=pl.quantidade, quantidade_recebida=linha_in.quantidade_recebida,
        ))
    await db.flush()
    await db.commit()
    return await _to_response(db, rec)


@router.post("/{id}/confirmar", response_model=RecepcaoResponseDTO)
async def confirmar_recepcao(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.receber")),
):
    """Gera StockMovimento entrada_compra por linha e actualiza o pedido."""
    r = await db.execute(select(RecepcaoModel).where(RecepcaoModel.id == id))
    rec = r.scalar_one_or_none()
    if not rec or rec.company_id != current_user.company_id:
        raise HTTPException(404, "Receção não encontrada")
    if rec.estado != "rascunho":
        raise HTTPException(400, "Receção já foi confirmada")

    linhas_r = await db.execute(select(RecepcaoLinhaModel).where(RecepcaoLinhaModel.recepcao_id == rec.id))
    linhas = list(linhas_r.scalars().all())

    pedido_r = await db.execute(select(PedidoCompraModel).where(PedidoCompraModel.id == rec.pedido_id))
    pedido = pedido_r.scalar_one()

    for linha in linhas:
        if linha.quantidade_recebida <= 0:
            continue
        await stock_service.registar_movimento(
            db, company_id=current_user.company_id, produto_id=linha.produto_id,
            tipo="entrada_compra", quantidade=Decimal(linha.quantidade_recebida),
            armazem_destino_id=rec.armazem_id, created_by=current_user.id,
            documento_ref_tipo="recepcao", documento_ref_id=str(rec.id),
        )
        pl_r = await db.execute(
            select(PedidoCompraLinhaModel).where(PedidoCompraLinhaModel.id == linha.pedido_linha_id)
        )
        pl = pl_r.scalar_one()
        pl.quantidade_recebida = Decimal(pl.quantidade_recebida) + Decimal(linha.quantidade_recebida)

    todas_linhas_r = await db.execute(
        select(PedidoCompraLinhaModel).where(PedidoCompraLinhaModel.pedido_id == pedido.id)
    )
    todas_linhas = list(todas_linhas_r.scalars().all())
    total_recebido = all(Decimal(l.quantidade_recebida) >= Decimal(l.quantidade) for l in todas_linhas)
    pedido.estado = "recebido" if total_recebido else "parcialmente_recebido"
    pedido.updated_at = datetime.utcnow()

    rec.estado = "confirmada"
    await write_audit(
        db, current_user.id, current_user.company_id,
        "confirmada", "recepcao", rec.id,
        dados_novos={"pedido_id": str(pedido.id), "n_linhas": len(linhas)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, rec)


__all__ = ["router"]
