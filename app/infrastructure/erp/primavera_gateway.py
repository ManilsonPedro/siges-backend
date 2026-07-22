"""Stub do `ErpGateway` para o Primavera ERP.

A integração real depende da disponibilização da API/SDK pelo parceiro
Primavera (ver `docs/05_INTEGRACAO_PRIMAVERA_E_ROADMAP.md`). Enquanto isso,
este stub permite trocar ``ERP_PROVIDER=primavera`` em ambientes de teste:
o backend arranca normalmente e só falha quando um método é *invocado*.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services.erp_gateway import DocumentoEmitido


_NOT_READY = (
    "Adaptador Primavera ainda não implementado. "
    "Aguardar resposta do parceiro à secção 2 de docs/05_INTEGRACAO_PRIMAVERA_E_ROADMAP.md "
    "ou usar ERP_PROVIDER=local."
)


class PrimaveraErpGateway:
    """Stub que arranca limpo mas levanta `NotImplementedError` quando chamado."""

    name = "primavera"

    async def upsert_artigo(self, db: AsyncSession, *, company_id: UUID, sku: str,
                            nome: str, preco: Decimal, iva_pct: Decimal,
                            unidade: str, correlation_id: str) -> str:
        raise NotImplementedError(_NOT_READY)

    async def consultar_stock(self, db: AsyncSession, *, company_id: UUID,
                              produto_id: UUID, armazem_id: UUID) -> Decimal:
        raise NotImplementedError(_NOT_READY)

    async def reservar_stock(self, db: AsyncSession, *, company_id: UUID,
                             produto_id: UUID, armazem_id: UUID,
                             quantidade: Decimal, correlation_id: str) -> None:
        raise NotImplementedError(_NOT_READY)

    async def libertar_reserva(self, db: AsyncSession, *, company_id: UUID,
                               produto_id: UUID, armazem_id: UUID,
                               quantidade: Decimal, correlation_id: str) -> None:
        raise NotImplementedError(_NOT_READY)

    async def emitir_documento_venda(self, db: AsyncSession, *, company_id: UUID,
                                     venda_id: UUID, correlation_id: str) -> DocumentoEmitido:
        raise NotImplementedError(_NOT_READY)

    async def registar_recebimento(self, db: AsyncSession, *, company_id: UUID,
                                   venda_id: UUID, valor: Decimal, forma: str,
                                   correlation_id: str) -> str:
        raise NotImplementedError(_NOT_READY)
