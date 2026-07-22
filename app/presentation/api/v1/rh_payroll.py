"""Processamento Salarial (domínio Capital Humano) — custo bruto por
colaborador. Fora de escopo: impostos/segurança social do regime
laboral local (tratar como iniciativa separada se necessário)."""
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
from app.infrastructure.database.models import (
    ColaboradorModel,
    DescontoModel,
    FolhaPagamentoModel,
    HoraExtraModel,
    ReciboSalarioModel,
    SubsidioModel,
)


router = APIRouter()


# ─── Subsídios ───────────────────────────────────────────────────────


class SubsidioCreateDTO(BaseModel):
    colaborador_id: UUID
    tipo: str = Field(..., pattern="^(alimentacao|transporte|outro)$")
    valor: Decimal = Field(..., gt=0)
    recorrente: bool = True


class SubsidioResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    tipo: str
    valor: Decimal
    recorrente: bool

    class Config:
        from_attributes = True


@router.get("/subsidios", response_model=List[SubsidioResponseDTO])
async def list_subsidios(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.view")),
):
    stmt = select(SubsidioModel)
    if colaborador_id:
        stmt = stmt.where(SubsidioModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/subsidios", response_model=SubsidioResponseDTO, status_code=201)
async def create_subsidio(
    body: SubsidioCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.gerir_subsidios")),
):
    m = SubsidioModel(id=uuid4(), **body.model_dump())
    db.add(m)
    await db.commit()
    return m


# ─── Descontos ───────────────────────────────────────────────────────


class DescontoCreateDTO(BaseModel):
    colaborador_id: UUID
    tipo: str = Field(..., pattern="^(falta_injustificada|adiantamento|outro)$")
    valor: Decimal = Field(..., gt=0)
    referente_periodo: str = Field(..., pattern="^\\d{4}-\\d{2}$")


class DescontoResponseDTO(BaseModel):
    id: UUID
    colaborador_id: UUID
    tipo: str
    valor: Decimal
    referente_periodo: str

    class Config:
        from_attributes = True


@router.get("/descontos", response_model=List[DescontoResponseDTO])
async def list_descontos(
    colaborador_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.view")),
):
    stmt = select(DescontoModel)
    if colaborador_id:
        stmt = stmt.where(DescontoModel.colaborador_id == colaborador_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/descontos", response_model=DescontoResponseDTO, status_code=201)
async def create_desconto(
    body: DescontoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.gerir_descontos")),
):
    m = DescontoModel(id=uuid4(), **body.model_dump())
    db.add(m)
    await db.commit()
    return m


# ─── Folhas de Pagamento ─────────────────────────────────────────────


class FolhaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    periodo: str
    estado: str
    data_processamento: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReciboResponseDTO(BaseModel):
    id: UUID
    folha_pagamento_id: UUID
    colaborador_id: UUID
    salario_base: Decimal
    total_subsidios: Decimal
    total_descontos: Decimal
    total_horas_extra: Decimal
    valor_liquido: Decimal

    class Config:
        from_attributes = True


@router.get("/folhas", response_model=List[FolhaResponseDTO])
async def list_folhas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.view")),
):
    r = await db.execute(select(FolhaPagamentoModel).where(FolhaPagamentoModel.company_id == current_user.company_id))
    return list(r.scalars().all())


class FolhaCreateDTO(BaseModel):
    periodo: str = Field(..., pattern="^\\d{4}-\\d{2}$")


@router.post("/folhas", response_model=FolhaResponseDTO, status_code=201)
async def create_folha(
    body: FolhaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.processar_folha")),
):
    clash = await db.execute(
        select(FolhaPagamentoModel)
        .where(FolhaPagamentoModel.company_id == current_user.company_id)
        .where(FolhaPagamentoModel.periodo == body.periodo)
    )
    if clash.scalar_one_or_none():
        raise HTTPException(409, f"Já existe folha para o período {body.periodo}")
    m = FolhaPagamentoModel(id=uuid4(), company_id=current_user.company_id, periodo=body.periodo, estado="aberta")
    db.add(m)
    await db.commit()
    return m


@router.post("/folhas/{periodo}/processar", response_model=List[ReciboResponseDTO])
async def processar_folha(
    periodo: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.processar_folha")),
):
    """Para cada Colaborador ativo, soma salario_base + subsídios
    recorrentes + horas extra aprovadas do período − descontos do
    período, gera ReciboSalario. Custo bruto — sem impostos/segurança
    social (fora de escopo)."""
    fr = await db.execute(
        select(FolhaPagamentoModel)
        .where(FolhaPagamentoModel.company_id == current_user.company_id)
        .where(FolhaPagamentoModel.periodo == periodo)
    )
    folha = fr.scalar_one_or_none()
    if not folha:
        raise HTTPException(404, f"Folha para {periodo} não encontrada — crie-a primeiro via POST /folhas")
    if folha.estado != "aberta":
        raise HTTPException(400, "Folha já foi processada")

    cr = await db.execute(
        select(ColaboradorModel)
        .where(ColaboradorModel.company_id == current_user.company_id)
        .where(ColaboradorModel.estado == "ativo")
        .where(ColaboradorModel.deleted_at.is_(None))
    )
    colaboradores = list(cr.scalars().all())

    recibos: List[ReciboSalarioModel] = []
    for colaborador in colaboradores:
        sr = await db.execute(
            select(SubsidioModel)
            .where(SubsidioModel.colaborador_id == colaborador.id)
            .where(SubsidioModel.recorrente.is_(True))
        )
        total_subsidios = sum((Decimal(s.valor) for s in sr.scalars().all()), Decimal("0"))

        dr = await db.execute(
            select(DescontoModel)
            .where(DescontoModel.colaborador_id == colaborador.id)
            .where(DescontoModel.referente_periodo == periodo)
        )
        total_descontos = sum((Decimal(d.valor) for d in dr.scalars().all()), Decimal("0"))

        her = await db.execute(
            select(HoraExtraModel)
            .where(HoraExtraModel.colaborador_id == colaborador.id)
            .where(HoraExtraModel.aprovado.is_(True))
        )
        total_horas_extra = sum((Decimal(h.horas) * Decimal("500") for h in her.scalars().all()), Decimal("0"))

        valor_liquido = Decimal(colaborador.salario_base) + total_subsidios + total_horas_extra - total_descontos
        recibo = ReciboSalarioModel(
            id=uuid4(), folha_pagamento_id=folha.id, colaborador_id=colaborador.id,
            salario_base=colaborador.salario_base, total_subsidios=total_subsidios,
            total_descontos=total_descontos, total_horas_extra=total_horas_extra,
            valor_liquido=valor_liquido,
        )
        db.add(recibo)
        recibos.append(recibo)

    folha.estado = "processada"
    folha.data_processamento = datetime.utcnow()
    await db.commit()
    return recibos


@router.get("/folhas/{periodo}/recibos", response_model=List[ReciboResponseDTO])
async def get_recibos(
    periodo: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.view")),
):
    fr = await db.execute(
        select(FolhaPagamentoModel)
        .where(FolhaPagamentoModel.company_id == current_user.company_id)
        .where(FolhaPagamentoModel.periodo == periodo)
    )
    folha = fr.scalar_one_or_none()
    if not folha:
        raise HTTPException(404, "Folha não encontrada")
    r = await db.execute(select(ReciboSalarioModel).where(ReciboSalarioModel.folha_pagamento_id == folha.id))
    return list(r.scalars().all())


@router.get("/recibos/{id}/pdf")
async def get_recibo_pdf(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("rh.payroll.view")),
):
    """Geração de PDF reaproveitando infrastructure/export/ — endpoint
    placeholder até haver decisão sobre layout do recibo."""
    r = await db.execute(select(ReciboSalarioModel).where(ReciboSalarioModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Recibo não encontrado")
    if not m.pdf_url:
        raise HTTPException(501, "Geração de PDF de recibo ainda não implementada")
    return {"pdf_url": m.pdf_url}


__all__ = ["router"]
