"""Fiscalidade (domínio Gestão Financeira): Taxas de Imposto, Obrigações,
IVA. SAF-T fica como stub até confirmação do regime fiscal aplicável.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import ObrigacaoFiscalModel, TaxaImpostoModel, VendaModel


router = APIRouter()


# ─── Taxas de Imposto ────────────────────────────────────────────────


class TaxaCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    percentagem: Decimal = Field(..., ge=0, le=100)
    tipo: str = Field(default="iva", pattern="^(iva|retencao|outro)$")
    padrao: bool = False
    activo: bool = True


class TaxaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    percentagem: Decimal
    tipo: str
    padrao: bool
    activo: bool

    class Config:
        from_attributes = True


@router.get("/taxas", response_model=List[TaxaResponseDTO])
async def list_taxas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fiscalidade.view")),
):
    r = await db.execute(
        select(TaxaImpostoModel)
        .where(TaxaImpostoModel.company_id == current_user.company_id)
        .where(TaxaImpostoModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/taxas", response_model=TaxaResponseDTO, status_code=201)
async def create_taxa(
    body: TaxaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fiscalidade.gerir_taxas")),
):
    if body.padrao:
        r = await db.execute(
            select(TaxaImpostoModel)
            .where(TaxaImpostoModel.company_id == current_user.company_id)
            .where(TaxaImpostoModel.padrao.is_(True))
        )
        for outra in r.scalars().all():
            outra.padrao = False
    m = TaxaImpostoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/taxas/{id}", status_code=204)
async def delete_taxa(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fiscalidade.gerir_taxas")),
):
    r = await db.execute(select(TaxaImpostoModel).where(TaxaImpostoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Taxa não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Obrigações Fiscais ──────────────────────────────────────────────


class ObrigacaoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=150)
    prazo: datetime
    recorrencia: Optional[str] = Field(None, pattern="^(mensal|trimestral|anual|unica)$")


class ObrigacaoUpdateDTO(BaseModel):
    estado: str = Field(..., pattern="^(pendente|cumprida)$")


class ObrigacaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    prazo: datetime
    recorrencia: Optional[str] = None
    estado: str

    class Config:
        from_attributes = True


@router.get("/obrigacoes", response_model=List[ObrigacaoResponseDTO])
async def list_obrigacoes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fiscalidade.view")),
):
    r = await db.execute(
        select(ObrigacaoFiscalModel)
        .where(ObrigacaoFiscalModel.company_id == current_user.company_id)
        .order_by(ObrigacaoFiscalModel.prazo)
    )
    return list(r.scalars().all())


@router.post("/obrigacoes", response_model=ObrigacaoResponseDTO, status_code=201)
async def create_obrigacao(
    body: ObrigacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fiscalidade.gerir_obrigacoes")),
):
    m = ObrigacaoFiscalModel(id=uuid4(), company_id=current_user.company_id, estado="pendente", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/obrigacoes/{id}", response_model=ObrigacaoResponseDTO)
async def update_obrigacao(
    id: UUID,
    body: ObrigacaoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fiscalidade.gerir_obrigacoes")),
):
    r = await db.execute(select(ObrigacaoFiscalModel).where(ObrigacaoFiscalModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Obrigação não encontrada")
    m.estado = body.estado
    await db.commit()
    return m


# ─── IVA ─────────────────────────────────────────────────────────────


@router.get("/iva")
async def relatorio_iva(
    de: Optional[datetime] = None,
    ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fiscalidade.view")),
):
    """Soma de IVA aplicado nas vendas do período, por taxa."""
    filters = [VendaModel.company_id == current_user.company_id, VendaModel.estado == "concluida"]
    if de:
        filters.append(VendaModel.data >= de)
    if ate:
        filters.append(VendaModel.data <= ate)
    r = await db.execute(select(VendaModel).where(and_(*filters)))
    vendas = list(r.scalars().all())
    total_iva = sum((Decimal(v.total_iva) for v in vendas), Decimal("0"))
    total_vendas = sum((Decimal(v.total_liquido) for v in vendas), Decimal("0"))
    return {"total_vendas": float(total_vendas), "total_iva": float(total_iva), "n_vendas": len(vendas)}


@router.post("/saft/exportar")
async def exportar_saft(
    periodo: str,
    current_user: User = Depends(require_permission("fiscalidade.gerir_obrigacoes")),
):
    """Stub — condicionado à confirmação do regime fiscal aplicável.
    Falha propositadamente até haver decisão/API confirmada."""
    raise HTTPException(
        501,
        "Exportação SAF-T ainda não implementada. Aguarda confirmação do regime fiscal aplicável "
        "e/ou disponibilização de integração com o ERP fiscal.",
    )


__all__ = ["router"]
