"""Tesouraria (domínio Gestão Financeira): Transferências entre Fundos e
Fluxo de Caixa consolidado.

Fundo já existe (BCS/BFA) — Transferência aqui só regista o registo de
auditoria da operação; os dois MovimentoFinanceiro (saída na origem,
entrada no destino) devem ser criados via o endpoint já validado
POST /movimentos (com conceito_id apropriado), mantendo toda a lógica
de recálculo de saldo já existente em movimento.py — não duplicada aqui.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import MovimentoFinanceiroModel, TransferenciaFundoModel


router = APIRouter()


class TransferenciaCreateDTO(BaseModel):
    fundo_origem_tipo: str = Field(..., pattern="^(BCS|BFA)$")
    fundo_destino_tipo: str = Field(..., pattern="^(BCS|BFA)$")
    valor: Decimal = Field(..., gt=0)
    motivo: Optional[str] = None
    movimento_origem_id: Optional[UUID] = None
    movimento_destino_id: Optional[UUID] = None


class TransferenciaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    fundo_origem_tipo: str
    fundo_destino_tipo: str
    valor: Decimal
    data: datetime
    motivo: Optional[str] = None
    movimento_origem_id: Optional[UUID] = None
    movimento_destino_id: Optional[UUID] = None

    class Config:
        from_attributes = True


@router.get("/transferencias", response_model=List[TransferenciaResponseDTO])
async def list_transferencias(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.tesouraria.view")),
):
    r = await db.execute(
        select(TransferenciaFundoModel)
        .where(TransferenciaFundoModel.company_id == current_user.company_id)
        .order_by(TransferenciaFundoModel.data.desc())
    )
    return list(r.scalars().all())


@router.post("/transferencias", response_model=TransferenciaResponseDTO, status_code=201)
async def registar_transferencia(
    req: Request,
    body: TransferenciaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.tesouraria.gerir_transferencias")),
):
    """Regista a transferência como facto histórico. Os movimentos
    financeiros correspondentes (saída/entrada) devem ser criados
    separadamente via POST /movimentos e associados aqui pelos IDs,
    para não duplicar as validações de conceito/fundo já existentes."""
    if body.fundo_origem_tipo == body.fundo_destino_tipo:
        raise HTTPException(400, "Fundo de origem e destino têm de ser diferentes")

    m = TransferenciaFundoModel(
        id=uuid4(), company_id=current_user.company_id, created_by=current_user.id,
        **body.model_dump(),
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "transferencia_fundo", m.id,
        dados_novos={"valor": str(body.valor), "origem": body.fundo_origem_tipo, "destino": body.fundo_destino_tipo},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.get("/fluxo-caixa")
async def fluxo_caixa(
    de: Optional[datetime] = None,
    ate: Optional[datetime] = None,
    agrupar_por: str = Query(default="mes", pattern="^(dia|semana|mes)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.tesouraria.view")),
):
    """Agregação sobre MovimentoFinanceiro já existente — sem nova entidade."""
    filters = [MovimentoFinanceiroModel.company_id == current_user.company_id, MovimentoFinanceiroModel.deleted_at.is_(None)]
    if de:
        filters.append(MovimentoFinanceiroModel.data >= de)
    if ate:
        filters.append(MovimentoFinanceiroModel.data <= ate)
    r = await db.execute(select(MovimentoFinanceiroModel).where(and_(*filters)))
    movimentos = list(r.scalars().all())

    def periodo_key(dt: datetime) -> str:
        if agrupar_por == "dia":
            return dt.strftime("%Y-%m-%d")
        if agrupar_por == "semana":
            return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        return dt.strftime("%Y-%m")

    agregados: dict[str, dict[str, Decimal]] = {}
    for m in movimentos:
        chave = periodo_key(m.data)
        agregados.setdefault(chave, {"entradas": Decimal("0"), "saidas": Decimal("0")})
        if m.tipo_movimento == "entrada":
            agregados[chave]["entradas"] += Decimal(m.valor)
        else:
            agregados[chave]["saidas"] += Decimal(m.valor)

    return [
        {"periodo": k, "entradas": float(v["entradas"]), "saidas": float(v["saidas"]), "liquido": float(v["entradas"] - v["saidas"])}
        for k, v in sorted(agregados.items())
    ]


__all__ = ["router"]
