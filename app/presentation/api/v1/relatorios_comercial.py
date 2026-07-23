"""Relatórios Comerciais — Vendas e Compras.

Agregações reais sobre VendaModel/VendaLinhaModel e PedidoCompraModel/
PedidoCompraLinhaModel. Sem inventar dimensões que não existem no schema
(região/província do cliente, margem/custo de produto — ver
PROMPT_SISTEMA_SIGES_SPRINTS.md, Sprint 4, para o que falta modelar
antes de suportar essas dimensões).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    ClienteModel,
    FornecedorModel,
    PedidoCompraLinhaModel,
    PedidoCompraModel,
    ProdutoModel,
    VendaLinhaModel,
    VendaModel,
)

router = APIRouter()


# ─── Vendas por Produto ────────────────────────────────────────────────


class VendaPorProdutoDTO(BaseModel):
    produto_id: Optional[UUID] = None
    sku: str
    nome: str
    quantidade: Decimal
    total: Decimal


@router.get("/vendas/por-produto", response_model=List[VendaPorProdutoDTO])
async def vendas_por_produto(
    data_de: Optional[datetime] = None,
    data_ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(VendaLinhaModel, VendaModel.data)
        .join(VendaModel, VendaModel.id == VendaLinhaModel.venda_id)
        .where(VendaModel.company_id == current_user.company_id)
        .where(VendaModel.estado == "concluida")
    )
    if data_de:
        stmt = stmt.where(VendaModel.data >= data_de)
    if data_ate:
        stmt = stmt.where(VendaModel.data <= data_ate)
    r = await db.execute(stmt)

    agregados: dict[str, dict] = {}
    for ln, _data in r.all():
        chave = ln.sku_snapshot
        if chave not in agregados:
            agregados[chave] = {
                "produto_id": ln.produto_id, "sku": ln.sku_snapshot,
                "nome": ln.nome_snapshot, "quantidade": Decimal("0"), "total": Decimal("0"),
            }
        agregados[chave]["quantidade"] += Decimal(ln.quantidade)
        agregados[chave]["total"] += Decimal(ln.subtotal)

    out = [VendaPorProdutoDTO(**v) for v in agregados.values()]
    out.sort(key=lambda x: x.total, reverse=True)
    return out


# ─── Vendas por Cliente ────────────────────────────────────────────────


class VendaPorClienteDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    cliente_nome: str
    n_vendas: int
    total: Decimal


@router.get("/vendas/por-cliente", response_model=List[VendaPorClienteDTO])
async def vendas_por_cliente(
    data_de: Optional[datetime] = None,
    data_ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(VendaModel)
        .where(VendaModel.company_id == current_user.company_id)
        .where(VendaModel.estado == "concluida")
        .where(VendaModel.cliente_id.isnot(None))
    )
    if data_de:
        stmt = stmt.where(VendaModel.data >= data_de)
    if data_ate:
        stmt = stmt.where(VendaModel.data <= data_ate)
    r = await db.execute(stmt)
    vendas = list(r.scalars().all())

    if not vendas:
        return []

    cr = await db.execute(
        select(ClienteModel)
        .where(ClienteModel.company_id == current_user.company_id)
        .where(ClienteModel.id.in_([UUID(v.cliente_id) for v in vendas]))
    )
    nomes = {str(c.id): c.nome for c in cr.scalars().all()}

    agregados: dict[str, dict] = {}
    for v in vendas:
        chave = v.cliente_id
        if chave not in agregados:
            agregados[chave] = {
                "cliente_id": chave, "cliente_nome": nomes.get(chave, "Cliente sem registo"),
                "n_vendas": 0, "total": Decimal("0"),
            }
        agregados[chave]["n_vendas"] += 1
        agregados[chave]["total"] += Decimal(v.total_liquido)

    out = [VendaPorClienteDTO(**v) for v in agregados.values()]
    out.sort(key=lambda x: x.total, reverse=True)
    return out


# ─── Compras por Fornecedor ────────────────────────────────────────────


class CompraPorFornecedorDTO(BaseModel):
    fornecedor_id: UUID
    fornecedor_nome: str
    n_pedidos: int
    total: Decimal


@router.get("/compras/por-fornecedor", response_model=List[CompraPorFornecedorDTO])
async def compras_por_fornecedor(
    data_de: Optional[datetime] = None,
    data_ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(PedidoCompraModel)
        .where(PedidoCompraModel.company_id == current_user.company_id)
        .where(PedidoCompraModel.estado != "cancelado")
    )
    if data_de:
        stmt = stmt.where(PedidoCompraModel.data >= data_de)
    if data_ate:
        stmt = stmt.where(PedidoCompraModel.data <= data_ate)
    r = await db.execute(stmt)
    pedidos = list(r.scalars().all())

    if not pedidos:
        return []

    fr = await db.execute(
        select(FornecedorModel)
        .where(FornecedorModel.company_id == current_user.company_id)
        .where(FornecedorModel.id.in_([p.fornecedor_id for p in pedidos]))
    )
    nomes = {f.id: f.nome for f in fr.scalars().all()}

    agregados: dict[UUID, dict] = {}
    for p in pedidos:
        if p.fornecedor_id not in agregados:
            agregados[p.fornecedor_id] = {
                "fornecedor_id": p.fornecedor_id,
                "fornecedor_nome": nomes.get(p.fornecedor_id, "Fornecedor sem registo"),
                "n_pedidos": 0, "total": Decimal("0"),
            }
        agregados[p.fornecedor_id]["n_pedidos"] += 1
        agregados[p.fornecedor_id]["total"] += Decimal(p.total)

    out = [CompraPorFornecedorDTO(**v) for v in agregados.values()]
    out.sort(key=lambda x: x.total, reverse=True)
    return out


# ─── Compras por Produto ───────────────────────────────────────────────


class CompraPorProdutoDTO(BaseModel):
    produto_id: UUID
    produto_nome: str
    quantidade: Decimal
    total: Decimal


@router.get("/compras/por-produto", response_model=List[CompraPorProdutoDTO])
async def compras_por_produto(
    data_de: Optional[datetime] = None,
    data_ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(PedidoCompraLinhaModel, PedidoCompraModel.data)
        .join(PedidoCompraModel, PedidoCompraModel.id == PedidoCompraLinhaModel.pedido_id)
        .where(PedidoCompraModel.company_id == current_user.company_id)
        .where(PedidoCompraModel.estado != "cancelado")
    )
    if data_de:
        stmt = stmt.where(PedidoCompraModel.data >= data_de)
    if data_ate:
        stmt = stmt.where(PedidoCompraModel.data <= data_ate)
    r = await db.execute(stmt)
    rows = r.all()

    if not rows:
        return []

    produto_ids = {ln.produto_id for ln, _ in rows}
    pr = await db.execute(
        select(ProdutoModel)
        .where(ProdutoModel.company_id == current_user.company_id)
        .where(ProdutoModel.id.in_(produto_ids))
    )
    nomes = {p.id: p.nome for p in pr.scalars().all()}

    agregados: dict[UUID, dict] = {}
    for ln, _data in rows:
        if ln.produto_id not in agregados:
            agregados[ln.produto_id] = {
                "produto_id": ln.produto_id,
                "produto_nome": nomes.get(ln.produto_id, "Produto sem registo"),
                "quantidade": Decimal("0"), "total": Decimal("0"),
            }
        agregados[ln.produto_id]["quantidade"] += Decimal(ln.quantidade)
        agregados[ln.produto_id]["total"] += Decimal(ln.quantidade) * Decimal(ln.preco_unitario)

    out = [CompraPorProdutoDTO(**v) for v in agregados.values()]
    out.sort(key=lambda x: x.total, reverse=True)
    return out


__all__ = ["router"]
