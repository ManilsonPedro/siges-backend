"""Porta para o sistema ERP fiscal/logístico (hoje Primavera).

A interface é única; a implementação é trocável via ``ERP_PROVIDER``:

- ``local``      → ``LocalErpGateway`` (usa as próprias tabelas do CRM)
- ``primavera``  → ``PrimaveraErpGateway`` (stub enquanto a API não chega)

Todos os métodos que mutam estado recebem um ``correlation_id`` para
garantir idempotência: chamar duas vezes com o mesmo id é equivalente a
chamar uma só vez.

Os métodos são ``async`` para se integrarem com a stack async (SQLAlchemy
AsyncSession). O ``PrimaveraErpGateway`` real fará I/O HTTP/SQL e
beneficia também de ``async``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DocumentoEmitido:
    """Resultado da emissão de um documento de venda no ERP."""
    numero: str
    serie: Optional[str]
    data: datetime
    total: Decimal
    pdf_url: Optional[str] = None
    ref_externa: Optional[str] = None  # nº interno no ERP


@runtime_checkable
class ErpGateway(Protocol):
    """Contrato mínimo entre o CRM e o sistema ERP fiscal."""

    name: str

    async def upsert_artigo(self, db: AsyncSession, *, company_id: UUID, sku: str,
                            nome: str, preco: Decimal, iva_pct: Decimal,
                            unidade: str, correlation_id: str) -> str:
        """Cria/actualiza um artigo no ERP. Devolve a referência externa."""
        ...

    async def consultar_stock(self, db: AsyncSession, *, company_id: UUID,
                              produto_id: UUID, armazem_id: UUID) -> Decimal:
        """Saldo disponível (qtd_actual − reservada) no armazém indicado."""
        ...

    async def reservar_stock(self, db: AsyncSession, *, company_id: UUID,
                             produto_id: UUID, armazem_id: UUID,
                             quantidade: Decimal, correlation_id: str) -> None:
        """Reserva quantidade para uma venda em curso."""
        ...

    async def libertar_reserva(self, db: AsyncSession, *, company_id: UUID,
                               produto_id: UUID, armazem_id: UUID,
                               quantidade: Decimal, correlation_id: str) -> None:
        """Liberta uma reserva (anulação ou expiração)."""
        ...

    async def emitir_documento_venda(self, db: AsyncSession, *, company_id: UUID,
                                     venda_id: UUID, correlation_id: str) -> DocumentoEmitido:
        """Emite documento fiscal de venda. **Idempotente** por correlation_id."""
        ...

    async def registar_recebimento(self, db: AsyncSession, *, company_id: UUID,
                                   venda_id: UUID, valor: Decimal, forma: str,
                                   correlation_id: str) -> str:
        """Regista recebimento no ERP. Devolve a referência externa do recibo."""
        ...
