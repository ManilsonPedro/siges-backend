from uuid import UUID, uuid4
from decimal import Decimal
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import MovimentoFinanceiro, Fundo
from app.infrastructure.repositories import (
    MovimentoRepository,
    FundoRepository,
    FornecedorRepository,
    ConceptoRepository,
)
from app.domain.exceptions import InsufficientFundsException, FornecedorNotFound, ConceptoNotFound


class CriarMovimentoUseCase:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.mov_repo = MovimentoRepository(db)
        self.fundo_repo = FundoRepository(db)
        self.forn_repo = FornecedorRepository(db)
        self.conc_repo = ConceptoRepository(db)

    async def execute(self, data: dict, company_id: UUID, user_id: UUID) -> MovimentoFinanceiro:
        fornecedor = await self.forn_repo.get_by_id(data["fornecedor_id"])
        if not fornecedor or fornecedor.company_id != company_id:
            raise FornecedorNotFound()

        conceito = await self.conc_repo.get_by_id(data["conceito_id"])
        if not conceito or conceito.company_id != company_id:
            raise ConceptoNotFound()

        valor = Decimal(str(data["valor"]))
        tipo = data["tipo_movimento"]

        if tipo == "saida":
            fundo = await self.fundo_repo.get_by_company(company_id)
            saldo = Decimal(str(fundo.saldo_atual)) if fundo else Decimal("0")
            if saldo < valor:
                raise InsufficientFundsException()

        entity = MovimentoFinanceiro(
            id=uuid4(),
            company_id=company_id,
            data=data.get("data") or datetime.utcnow(),
            fornecedor_id=data["fornecedor_id"],
            conceito_id=data["conceito_id"],
            fatura_proforma=data.get("fatura_proforma") or "",
            valor=valor,
            fatura_recibo=data.get("fatura_recibo") or "",
            observacoes=data.get("observacoes") or "",
            tipo_movimento=tipo,
            estado_pagamento="pendente",
            created_by=user_id,
        )
        created = await self.mov_repo.create(entity)
        await self._recalcular(company_id)
        return created

    async def _recalcular(self, company_id: UUID):
        acumulado = await self.mov_repo.sum_by_tipo(company_id, "saida", "pago")
        fundo = await self.fundo_repo.get_by_company(company_id)
        if fundo:
            disponivel = Decimal(str(fundo.valor_disponivel or 0))
            saldo = disponivel - Decimal(str(acumulado))
            await self.fundo_repo.update_saldos(company_id, Decimal(str(acumulado)), saldo)


class RecalcularSaldosUseCase:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.mov_repo = MovimentoRepository(db)
        self.fundo_repo = FundoRepository(db)

    async def execute(self, company_id: UUID):
        acumulado = await self.mov_repo.sum_by_tipo(company_id, "saida", "pago")
        fundo = await self.fundo_repo.get_by_company(company_id)
        if fundo:
            disponivel = Decimal(str(fundo.valor_disponivel or 0))
            saldo = disponivel - Decimal(str(acumulado))
            await self.fundo_repo.update_saldos(company_id, Decimal(str(acumulado)), saldo)


__all__ = ["CriarMovimentoUseCase", "RecalcularSaldosUseCase"]
