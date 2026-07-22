"""Contabilidade (domínio Gestão Financeira) — camada de LEITURA.

Não tem escrita própria (excepto Plano de Contas/Centros de Custo,
estruturais). Agrega MovimentoFinanceiro já existente. Nunca apresentar
como "contabilidade certificada" — SAF-T e fatura legal continuam
exclusivamente no ERP fiscal externo.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import ConceptoModel, MovimentoFinanceiroModel, PlanoContasModel


router = APIRouter()


# ─── Plano de Contas ─────────────────────────────────────────────────


class PlanoContasCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=20)
    nome: str = Field(..., min_length=1, max_length=150)
    classe: int = Field(..., ge=1, le=7)
    tipo: str = Field(..., pattern="^(analitica|sintetica)$")
    conta_pai_id: Optional[UUID] = None


class PlanoContasResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    nome: str
    classe: int
    tipo: str
    conta_pai_id: Optional[UUID] = None

    class Config:
        from_attributes = True


@router.get("/plano-contas", response_model=List[PlanoContasResponseDTO])
async def list_plano_contas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contabilidade.ver")),
):
    r = await db.execute(
        select(PlanoContasModel)
        .where(PlanoContasModel.company_id == current_user.company_id)
        .where(PlanoContasModel.deleted_at.is_(None))
        .order_by(PlanoContasModel.codigo)
    )
    return list(r.scalars().all())


@router.post("/plano-contas", response_model=PlanoContasResponseDTO, status_code=201)
async def create_plano_contas(
    body: PlanoContasCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contabilidade.gerir_plano_contas")),
):
    m = PlanoContasModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/plano-contas/{id}", status_code=204)
async def delete_plano_contas(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contabilidade.gerir_plano_contas")),
):
    r = await db.execute(select(PlanoContasModel).where(PlanoContasModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Conta não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Balancetes / Razão / Diário (leitura, fonte: dados internos) ────


@router.get("/balancetes")
async def balancetes(
    de: Optional[datetime] = None,
    ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contabilidade.ver")),
):
    """Agregação de MovimentoFinanceiro por Conceito — proxy simplificado
    de balancete enquanto não houver Plano de Contas ligado aos
    movimentos. Fonte: dados internos (não certificada)."""
    filters = [MovimentoFinanceiroModel.company_id == current_user.company_id, MovimentoFinanceiroModel.deleted_at.is_(None)]
    if de:
        filters.append(MovimentoFinanceiroModel.data >= de)
    if ate:
        filters.append(MovimentoFinanceiroModel.data <= ate)
    from sqlalchemy import and_
    r = await db.execute(select(MovimentoFinanceiroModel).where(and_(*filters)))
    movimentos = list(r.scalars().all())

    cr = await db.execute(select(ConceptoModel).where(ConceptoModel.company_id == current_user.company_id))
    conceitos = {str(c.id): c.nome for c in cr.scalars().all()}

    agregado: dict[str, dict[str, Decimal]] = {}
    for m in movimentos:
        chave = str(m.conceito_id)
        agregado.setdefault(chave, {"entradas": Decimal("0"), "saidas": Decimal("0")})
        if m.tipo_movimento == "entrada":
            agregado[chave]["entradas"] += Decimal(m.valor)
        else:
            agregado[chave]["saidas"] += Decimal(m.valor)

    return {
        "fonte": "dados_internos",
        "linhas": [
            {"conceito": conceitos.get(k, k), "entradas": float(v["entradas"]), "saidas": float(v["saidas"])}
            for k, v in agregado.items()
        ],
    }


@router.get("/razao")
async def razao(
    conceito_id: UUID,
    de: Optional[datetime] = None,
    ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contabilidade.ver")),
):
    from sqlalchemy import and_
    filters = [
        MovimentoFinanceiroModel.company_id == current_user.company_id,
        MovimentoFinanceiroModel.deleted_at.is_(None),
        MovimentoFinanceiroModel.conceito_id == conceito_id,
    ]
    if de:
        filters.append(MovimentoFinanceiroModel.data >= de)
    if ate:
        filters.append(MovimentoFinanceiroModel.data <= ate)
    r = await db.execute(select(MovimentoFinanceiroModel).where(and_(*filters)).order_by(MovimentoFinanceiroModel.data))
    movimentos = list(r.scalars().all())
    return {
        "fonte": "dados_internos",
        "lancamentos": [
            {"data": m.data.isoformat(), "tipo": m.tipo_movimento, "valor": float(m.valor), "observacoes": m.observacoes}
            for m in movimentos
        ],
    }


@router.get("/diario")
async def diario(
    data: datetime,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("contabilidade.ver")),
):
    from datetime import timedelta
    from sqlalchemy import and_
    inicio_dia = data.replace(hour=0, minute=0, second=0, microsecond=0)
    fim_dia = inicio_dia + timedelta(days=1)
    r = await db.execute(
        select(MovimentoFinanceiroModel)
        .where(and_(
            MovimentoFinanceiroModel.company_id == current_user.company_id,
            MovimentoFinanceiroModel.deleted_at.is_(None),
            MovimentoFinanceiroModel.data >= inicio_dia,
            MovimentoFinanceiroModel.data < fim_dia,
        ))
        .order_by(MovimentoFinanceiroModel.data)
    )
    movimentos = list(r.scalars().all())
    return {
        "fonte": "dados_internos",
        "lancamentos": [
            {"data": m.data.isoformat(), "tipo": m.tipo_movimento, "valor": float(m.valor)}
            for m in movimentos
        ],
    }


__all__ = ["router"]
