"""Implementação local do `ErpGateway`: usa as próprias tabelas do CRM.

Esta é a implementação activa enquanto não houver API do Primavera.
O LocalErpGateway delega:

- ``upsert_artigo``      → ProdutoModel
- ``consultar_stock``    → StockSaldoModel
- ``reservar_stock``     → stock_service.reservar
- ``libertar_reserva``   → stock_service.libertar
- ``emitir_documento_venda`` → gera número sequencial de proforma
- ``registar_recebimento`` → ref interna LOCAL-REC-…
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services import stock_service
from app.domain.services.erp_gateway import DocumentoEmitido
from app.infrastructure.database.models import (
    ProdutoModel,
    StockSaldoModel,
    VendaModel,
)


class LocalErpGateway:
    """Gateway "ERP local" — usa o próprio CRM como ERP."""

    name = "local"

    async def upsert_artigo(self, db: AsyncSession, *, company_id: UUID, sku: str,
                            nome: str, preco: Decimal, iva_pct: Decimal,
                            unidade: str, correlation_id: str) -> str:
        # A criação/actualização real passa pelo router /produtos.
        # Aqui só devolvemos a ref. estável.
        return f"LOCAL-ART-{sku}"

    async def consultar_stock(self, db: AsyncSession, *, company_id: UUID,
                              produto_id: UUID, armazem_id: UUID) -> Decimal:
        r = await db.execute(
            select(StockSaldoModel)
            .where(StockSaldoModel.produto_id == produto_id)
            .where(StockSaldoModel.armazem_id == armazem_id)
        )
        s = r.scalar_one_or_none()
        if not s:
            return Decimal("0")
        return Decimal(s.qtd_actual) - Decimal(s.qtd_reservada)

    async def reservar_stock(self, db: AsyncSession, *, company_id: UUID,
                             produto_id: UUID, armazem_id: UUID,
                             quantidade: Decimal, correlation_id: str) -> None:
        await stock_service.reservar(
            db, produto_id=produto_id, armazem_id=armazem_id,
            quantidade=quantidade, company_id=company_id,
        )

    async def libertar_reserva(self, db: AsyncSession, *, company_id: UUID,
                               produto_id: UUID, armazem_id: UUID,
                               quantidade: Decimal, correlation_id: str) -> None:
        await stock_service.libertar(
            db, produto_id=produto_id, armazem_id=armazem_id,
            quantidade=quantidade,
        )

    async def emitir_documento_venda(self, db: AsyncSession, *, company_id: UUID,
                                     venda_id: UUID, correlation_id: str) -> DocumentoEmitido:
        # Gera nº sequencial de proforma por company e ano.
        r = await db.execute(select(VendaModel).where(VendaModel.id == venda_id))
        v = r.scalar_one_or_none()
        if not v:
            raise ValueError(f"Venda {venda_id} não encontrada")

        # Idempotência: se já tem nº, devolve esse.
        if v.numero_proforma:
            return DocumentoEmitido(
                numero=v.numero_proforma, serie="PRF",
                data=v.data or datetime.utcnow(),
                total=Decimal(v.total_liquido),
                ref_externa=f"LOCAL-{correlation_id}",
            )

        ano = (v.data or datetime.utcnow()).strftime("%Y")
        # Contar quantas vendas concluídas existem este ano nesta company
        count_r = await db.execute(
            select(func.count(VendaModel.id))
            .where(VendaModel.company_id == company_id)
            .where(VendaModel.numero_proforma.isnot(None))
            .where(func.to_char(VendaModel.data, "YYYY") == ano)
        )
        try:
            n = (count_r.scalar() or 0) + 1
        except Exception:
            # Fallback p/ SQLite (sem to_char) — usa contador absoluto
            count_r = await db.execute(
                select(func.count(VendaModel.id))
                .where(VendaModel.company_id == company_id)
                .where(VendaModel.numero_proforma.isnot(None))
            )
            n = (count_r.scalar() or 0) + 1

        numero = f"PRF-{ano}-{n:05d}"
        v.numero_proforma = numero
        return DocumentoEmitido(
            numero=numero, serie="PRF",
            data=v.data or datetime.utcnow(),
            total=Decimal(v.total_liquido),
            ref_externa=f"LOCAL-{correlation_id}",
        )

    async def registar_recebimento(self, db: AsyncSession, *, company_id: UUID,
                                   venda_id: UUID, valor: Decimal, forma: str,
                                   correlation_id: str) -> str:
        return f"LOCAL-REC-{correlation_id}"
