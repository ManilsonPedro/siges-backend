"""Serviço de domínio para Estoque.

Centraliza as **invariantes** do módulo:

- Toda alteração de saldo passa por um StockMovimentoModel persistido.
- ``qtd_actual`` não pode ficar negativa excepto em ``saida_ajuste``
  (com motivo obrigatório).
- Transferência exige armazéns origem ≠ destino, ambos não nulos.
- Movimentos são imutáveis — correcções fazem-se por estorno
  (movimento inverso com ``estornado_de`` preenchido).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    StockMovimentoModel,
    StockSaldoModel,
)


TIPOS_ENTRADA = {"entrada_compra", "entrada_producao", "entrada_ajuste"}
TIPOS_SAIDA = {"saida_venda", "saida_perda", "saida_ajuste"}
TIPOS_VALIDOS = TIPOS_ENTRADA | TIPOS_SAIDA | {"transferencia"}


async def _get_or_create_saldo(
    db: AsyncSession,
    *,
    company_id: UUID,
    produto_id: UUID,
    armazem_id: UUID,
) -> StockSaldoModel:
    r = await db.execute(
        select(StockSaldoModel)
        .where(StockSaldoModel.produto_id == produto_id)
        .where(StockSaldoModel.armazem_id == armazem_id)
    )
    s = r.scalar_one_or_none()
    if s:
        return s
    s = StockSaldoModel(
        id=uuid4(),
        company_id=company_id,
        produto_id=produto_id,
        armazem_id=armazem_id,
        qtd_actual=Decimal("0"),
        qtd_reservada=Decimal("0"),
        stock_minimo=Decimal("0"),
    )
    db.add(s)
    await db.flush()
    return s


async def registar_movimento(
    db: AsyncSession,
    *,
    company_id: UUID,
    produto_id: UUID,
    tipo: str,
    quantidade: Decimal,
    armazem_origem_id: Optional[UUID] = None,
    armazem_destino_id: Optional[UUID] = None,
    custo_unitario: Optional[Decimal] = None,
    documento_ref_tipo: Optional[str] = None,
    documento_ref_id: Optional[str] = None,
    motivo: Optional[str] = None,
    created_by: Optional[UUID] = None,
    estornado_de: Optional[UUID] = None,
    permitir_negativo: bool = False,
) -> StockMovimentoModel:
    """Regista movimento + ajusta saldos atomicamente.

    Valida invariantes e devolve o StockMovimentoModel persistido.
    """
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"Tipo de movimento inválido: {tipo}")
    if quantidade <= 0:
        raise HTTPException(400, "Quantidade tem de ser > 0")

    if tipo in TIPOS_ENTRADA:
        if not armazem_destino_id:
            raise HTTPException(400, "Entrada exige armazém destino")
        if armazem_origem_id:
            raise HTTPException(400, "Entrada não pode ter armazém origem")
        if tipo == "entrada_ajuste" and not motivo:
            raise HTTPException(400, "Ajuste de entrada exige motivo")
    elif tipo in TIPOS_SAIDA:
        if not armazem_origem_id:
            raise HTTPException(400, "Saída exige armazém origem")
        if armazem_destino_id:
            raise HTTPException(400, "Saída não pode ter armazém destino")
        if tipo == "saida_ajuste" and not motivo:
            raise HTTPException(400, "Ajuste de saída exige motivo")
    elif tipo == "transferencia":
        if not armazem_origem_id or not armazem_destino_id:
            raise HTTPException(400, "Transferência exige origem e destino")
        if armazem_origem_id == armazem_destino_id:
            raise HTTPException(400, "Origem e destino têm de ser diferentes")

    # Sai do origem
    if armazem_origem_id:
        s_origem = await _get_or_create_saldo(
            db, company_id=company_id, produto_id=produto_id,
            armazem_id=armazem_origem_id,
        )
        novo_actual = Decimal(s_origem.qtd_actual) - quantidade
        if novo_actual < 0 and not permitir_negativo and tipo != "saida_ajuste":
            raise HTTPException(
                409,
                f"Stock insuficiente: actual={s_origem.qtd_actual}, "
                f"pedido={quantidade}",
            )
        s_origem.qtd_actual = novo_actual

    # Entra no destino
    if armazem_destino_id:
        s_destino = await _get_or_create_saldo(
            db, company_id=company_id, produto_id=produto_id,
            armazem_id=armazem_destino_id,
        )
        s_destino.qtd_actual = Decimal(s_destino.qtd_actual) + quantidade

    mov = StockMovimentoModel(
        id=uuid4(),
        company_id=company_id,
        produto_id=produto_id,
        armazem_origem_id=armazem_origem_id,
        armazem_destino_id=armazem_destino_id,
        tipo=tipo,
        quantidade=quantidade,
        custo_unitario=custo_unitario,
        documento_ref_tipo=documento_ref_tipo,
        documento_ref_id=documento_ref_id,
        motivo=motivo,
        estornado_de=estornado_de,
        created_by=created_by,
    )
    db.add(mov)
    await db.flush()
    return mov


async def reservar(
    db: AsyncSession,
    *,
    produto_id: UUID,
    armazem_id: UUID,
    quantidade: Decimal,
    company_id: UUID,
) -> None:
    """Incrementa qtd_reservada. Falha se disponível < quantidade."""
    s = await _get_or_create_saldo(
        db, company_id=company_id, produto_id=produto_id, armazem_id=armazem_id,
    )
    disponivel = Decimal(s.qtd_actual) - Decimal(s.qtd_reservada)
    if disponivel < quantidade:
        raise HTTPException(
            409,
            f"Stock disponível insuficiente: {disponivel} < {quantidade}",
        )
    s.qtd_reservada = Decimal(s.qtd_reservada) + quantidade


async def libertar(
    db: AsyncSession,
    *,
    produto_id: UUID,
    armazem_id: UUID,
    quantidade: Decimal,
) -> None:
    r = await db.execute(
        select(StockSaldoModel)
        .where(StockSaldoModel.produto_id == produto_id)
        .where(StockSaldoModel.armazem_id == armazem_id)
    )
    s = r.scalar_one_or_none()
    if not s:
        return
    novo = Decimal(s.qtd_reservada) - quantidade
    s.qtd_reservada = novo if novo >= 0 else Decimal("0")


__all__ = [
    "registar_movimento",
    "reservar",
    "libertar",
    "TIPOS_ENTRADA",
    "TIPOS_SAIDA",
    "TIPOS_VALIDOS",
]
