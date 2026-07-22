"""Gestão Financeira: Centros de Custo, Aprovações Financeiras,
Contas a Receber, Contas a Pagar.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    AprovacaoFinanceiraModel,
    CentroCustoModel,
    ContaPagarModel,
    ContaReceberModel,
    MovimentoFinanceiroModel,
)


router = APIRouter()


# ─── Centros de Custo ────────────────────────────────────────────────


class CentroCustoCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=20)
    nome: str = Field(..., min_length=1, max_length=120)
    activo: bool = True


class CentroCustoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    nome: str
    activo: bool

    class Config:
        from_attributes = True


@router.get("/centros-custo", response_model=List[CentroCustoResponseDTO])
async def list_centros_custo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.gerir_centros_custo")),
):
    r = await db.execute(
        select(CentroCustoModel)
        .where(CentroCustoModel.company_id == current_user.company_id)
        .where(CentroCustoModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/centros-custo", response_model=CentroCustoResponseDTO, status_code=201)
async def create_centro_custo(
    body: CentroCustoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.gerir_centros_custo")),
):
    m = CentroCustoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.get("/centros-custo/{id}/movimentos")
async def movimentos_centro_custo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.gerir_centros_custo")),
):
    """Retorna centro de custo (movimentos vinculados exigiriam campo
    centro_custo_id em MovimentoFinanceiro — fora deste prompt até
    haver confirmação de que compensa alterar a tabela principal)."""
    r = await db.execute(select(CentroCustoModel).where(CentroCustoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Centro de custo não encontrado")
    return {"centro_custo": {"id": str(m.id), "nome": m.nome}, "movimentos": []}


@router.delete("/centros-custo/{id}", status_code=204)
async def delete_centro_custo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.gerir_centros_custo")),
):
    r = await db.execute(select(CentroCustoModel).where(CentroCustoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Centro de custo não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Aprovações Financeiras ──────────────────────────────────────────


class AprovacaoCreateDTO(BaseModel):
    movimento_id: UUID
    valor: Decimal = Field(..., gt=0)


class AprovacaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    movimento_id: UUID
    valor: Decimal
    solicitante_id: UUID
    aprovador_id: Optional[UUID] = None
    estado: str
    motivo_rejeicao: Optional[str] = None
    data_decisao: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/aprovacoes", response_model=List[AprovacaoResponseDTO])
async def list_aprovacoes(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.ver")),
):
    stmt = select(AprovacaoFinanceiraModel).where(AprovacaoFinanceiraModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(AprovacaoFinanceiraModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/aprovacoes", response_model=AprovacaoResponseDTO, status_code=201)
async def create_aprovacao(
    body: AprovacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.ver")),
):
    m = AprovacaoFinanceiraModel(
        id=uuid4(), company_id=current_user.company_id, solicitante_id=current_user.id,
        estado="pendente", **body.model_dump(),
    )
    db.add(m)
    await db.commit()
    return m


@router.post("/aprovacoes/{id}/aprovar", response_model=AprovacaoResponseDTO)
async def aprovar(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.aprovar")),
):
    r = await db.execute(select(AprovacaoFinanceiraModel).where(AprovacaoFinanceiraModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Aprovação não encontrada")
    if m.estado != "pendente":
        raise HTTPException(400, "Aprovação já foi decidida")
    m.estado = "aprovado"
    m.aprovador_id = current_user.id
    m.data_decisao = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "aprovado", "aprovacao_financeira", m.id, dados_novos={},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


class RejeitarAprovacaoDTO(BaseModel):
    motivo: str = Field(..., min_length=1)


@router.post("/aprovacoes/{id}/rejeitar", response_model=AprovacaoResponseDTO)
async def rejeitar(
    id: UUID,
    body: RejeitarAprovacaoDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.aprovar")),
):
    r = await db.execute(select(AprovacaoFinanceiraModel).where(AprovacaoFinanceiraModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Aprovação não encontrada")
    if m.estado != "pendente":
        raise HTTPException(400, "Aprovação já foi decidida")
    m.estado = "rejeitado"
    m.aprovador_id = current_user.id
    m.motivo_rejeicao = body.motivo
    m.data_decisao = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "rejeitado", "aprovacao_financeira", m.id, dados_novos={"motivo": body.motivo},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


# ─── Contas a Receber ────────────────────────────────────────────────


class ContaReceberCreateDTO(BaseModel):
    cliente_id: UUID
    origem_tipo: str = Field(default="manual", pattern="^(venda|manual)$")
    origem_id: Optional[str] = None
    valor: Decimal = Field(..., gt=0)
    data_vencimento: datetime


class ContaReceberResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: str
    origem_tipo: str
    origem_id: Optional[str] = None
    valor: Decimal
    data_vencimento: datetime
    data_recebimento: Optional[datetime] = None
    estado: str
    movimento_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/contas-receber", response_model=List[ContaReceberResponseDTO])
async def list_contas_receber(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_receber.view")),
):
    stmt = select(ContaReceberModel).where(ContaReceberModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(ContaReceberModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/contas-receber", response_model=ContaReceberResponseDTO, status_code=201)
async def create_conta_receber(
    body: ContaReceberCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_receber.gerir")),
):
    m = ContaReceberModel(
        id=uuid4(), company_id=current_user.company_id, cliente_id=str(body.cliente_id),
        estado="pendente", origem_tipo=body.origem_tipo, origem_id=body.origem_id,
        valor=body.valor, data_vencimento=body.data_vencimento,
    )
    db.add(m)
    await db.commit()
    return m


class RegistarRecebimentoDTO(BaseModel):
    valor: Decimal = Field(..., gt=0)
    movimento_id: Optional[UUID] = None


@router.post("/contas-receber/{id}/registar-recebimento", response_model=ContaReceberResponseDTO)
async def registar_recebimento(
    id: UUID,
    body: RegistarRecebimentoDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_receber.registar_recebimento")),
):
    r = await db.execute(select(ContaReceberModel).where(ContaReceberModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Conta a receber não encontrada")
    if m.estado in ("pago", "cancelado"):
        raise HTTPException(400, "Conta já está paga ou cancelada")

    m.estado = "pago" if body.valor >= Decimal(m.valor) else "parcial"
    m.data_recebimento = datetime.utcnow()
    m.movimento_id = body.movimento_id
    await db.commit()
    return m


@router.get("/contas-receber/atrasadas", response_model=List[ContaReceberResponseDTO])
async def contas_receber_atrasadas(
    dias_min: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_receber.view")),
):
    agora = datetime.utcnow()
    r = await db.execute(
        select(ContaReceberModel)
        .where(ContaReceberModel.company_id == current_user.company_id)
        .where(ContaReceberModel.estado.in_(["pendente", "parcial"]))
        .where(ContaReceberModel.data_vencimento < agora)
    )
    todas = list(r.scalars().all())
    return [c for c in todas if (agora - c.data_vencimento).days >= dias_min]


# ─── Contas a Pagar ──────────────────────────────────────────────────


class ContaPagarCreateDTO(BaseModel):
    fornecedor_id: UUID
    origem_tipo: str = Field(default="manual", pattern="^(pedido_compra|manual)$")
    origem_id: Optional[str] = None
    valor: Decimal = Field(..., gt=0)
    data_vencimento: datetime


class ContaPagarResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    fornecedor_id: UUID
    origem_tipo: str
    origem_id: Optional[str] = None
    valor: Decimal
    data_vencimento: datetime
    data_pagamento: Optional[datetime] = None
    estado: str
    movimento_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/contas-pagar", response_model=List[ContaPagarResponseDTO])
async def list_contas_pagar(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_pagar.view")),
):
    stmt = select(ContaPagarModel).where(ContaPagarModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(ContaPagarModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/contas-pagar", response_model=ContaPagarResponseDTO, status_code=201)
async def create_conta_pagar(
    body: ContaPagarCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_pagar.gerir")),
):
    m = ContaPagarModel(id=uuid4(), company_id=current_user.company_id, estado="pendente", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


class RegistarPagamentoDTO(BaseModel):
    valor: Decimal = Field(..., gt=0)
    movimento_id: Optional[UUID] = None


@router.post("/contas-pagar/{id}/registar-pagamento", response_model=ContaPagarResponseDTO)
async def registar_pagamento(
    id: UUID,
    body: RegistarPagamentoDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_pagar.registar_pagamento")),
):
    r = await db.execute(select(ContaPagarModel).where(ContaPagarModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Conta a pagar não encontrada")
    if m.estado in ("pago", "cancelado"):
        raise HTTPException(400, "Conta já está paga ou cancelada")
    m.estado = "pago" if body.valor >= Decimal(m.valor) else "parcial"
    m.data_pagamento = datetime.utcnow()
    m.movimento_id = body.movimento_id
    await db.commit()
    return m


@router.get("/contas-pagar/a-vencer", response_model=List[ContaPagarResponseDTO])
async def contas_pagar_a_vencer(
    dias: int = 7,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("financeiro.contas_pagar.view")),
):
    agora = datetime.utcnow()
    limite = agora + timedelta(days=dias)
    r = await db.execute(
        select(ContaPagarModel)
        .where(ContaPagarModel.company_id == current_user.company_id)
        .where(ContaPagarModel.estado.in_(["pendente", "parcial"]))
        .where(ContaPagarModel.data_vencimento <= limite)
    )
    return list(r.scalars().all())


__all__ = ["router"]
