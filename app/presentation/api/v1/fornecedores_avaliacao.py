"""Contratos e Avaliações de Fornecedores (extensão de Supply Chain).

Router separado do CRUD básico de fornecedores (fornecedor.py) para não
misturar responsabilidades — histórico de pagamentos não é entidade
própria, é consultado directamente via MovimentoFinanceiroModel filtrado
por fornecedor_id (ver presentation/api/v1/relatorios.py / fornecedor.py).
"""
from __future__ import annotations

from datetime import datetime
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
    AvaliacaoFornecedorModel,
    ContratoFornecedorModel,
    FornecedorModel,
)


router = APIRouter()


# ─── Contratos ───────────────────────────────────────────────────────


class ContratoCreateDTO(BaseModel):
    tipo: Optional[str] = None
    data_inicio: datetime
    data_fim: Optional[datetime] = None
    condicoes_pagamento: Optional[str] = None
    arquivo_url: Optional[str] = None


class ContratoResponseDTO(BaseModel):
    id: UUID
    fornecedor_id: UUID
    tipo: Optional[str] = None
    data_inicio: datetime
    data_fim: Optional[datetime] = None
    condicoes_pagamento: Optional[str] = None
    arquivo_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


async def _get_fornecedor(db: AsyncSession, fornecedor_id: UUID, current_user: User) -> FornecedorModel:
    r = await db.execute(
        select(FornecedorModel)
        .where(FornecedorModel.id == fornecedor_id)
        .where(FornecedorModel.company_id == current_user.company_id)
    )
    f = r.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Fornecedor não encontrado")
    return f


@router.get("/{fornecedor_id}/contratos", response_model=List[ContratoResponseDTO])
async def list_contratos(
    fornecedor_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fornecedores.listar")),
):
    await _get_fornecedor(db, fornecedor_id, current_user)
    r = await db.execute(
        select(ContratoFornecedorModel)
        .where(ContratoFornecedorModel.fornecedor_id == fornecedor_id)
        .where(ContratoFornecedorModel.deleted_at.is_(None))
        .order_by(ContratoFornecedorModel.data_inicio.desc())
    )
    return list(r.scalars().all())


@router.post("/{fornecedor_id}/contratos", response_model=ContratoResponseDTO, status_code=201)
async def create_contrato(
    fornecedor_id: UUID,
    req: Request,
    body: ContratoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fornecedores.gerir_contratos")),
):
    await _get_fornecedor(db, fornecedor_id, current_user)
    c = ContratoFornecedorModel(
        id=uuid4(), company_id=current_user.company_id, fornecedor_id=fornecedor_id,
        tipo=body.tipo, data_inicio=body.data_inicio, data_fim=body.data_fim,
        condicoes_pagamento=body.condicoes_pagamento, arquivo_url=body.arquivo_url,
    )
    db.add(c)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "contrato_fornecedor", c.id,
        dados_novos={"fornecedor_id": str(fornecedor_id)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return c


@router.delete("/contratos/{id}", status_code=204)
async def delete_contrato(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fornecedores.gerir_contratos")),
):
    r = await db.execute(select(ContratoFornecedorModel).where(ContratoFornecedorModel.id == id))
    c = r.scalar_one_or_none()
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Contrato não encontrado")
    c.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Avaliações ──────────────────────────────────────────────────────


class AvaliacaoCreateDTO(BaseModel):
    periodo: str = Field(..., min_length=1, max_length=20)
    nota_prazo: Decimal = Field(..., ge=0, le=5)
    nota_qualidade: Decimal = Field(..., ge=0, le=5)
    nota_preco: Decimal = Field(..., ge=0, le=5)
    observacoes: Optional[str] = None


class AvaliacaoResponseDTO(BaseModel):
    id: UUID
    fornecedor_id: UUID
    periodo: str
    nota_prazo: Decimal
    nota_qualidade: Decimal
    nota_preco: Decimal
    observacoes: Optional[str] = None
    avaliado_por: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/{fornecedor_id}/avaliacoes", response_model=List[AvaliacaoResponseDTO])
async def list_avaliacoes(
    fornecedor_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fornecedores.listar")),
):
    await _get_fornecedor(db, fornecedor_id, current_user)
    r = await db.execute(
        select(AvaliacaoFornecedorModel)
        .where(AvaliacaoFornecedorModel.fornecedor_id == fornecedor_id)
        .order_by(AvaliacaoFornecedorModel.periodo.desc())
    )
    return list(r.scalars().all())


@router.post("/{fornecedor_id}/avaliacoes", response_model=AvaliacaoResponseDTO, status_code=201)
async def create_avaliacao(
    fornecedor_id: UUID,
    req: Request,
    body: AvaliacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fornecedores.avaliar")),
):
    await _get_fornecedor(db, fornecedor_id, current_user)
    a = AvaliacaoFornecedorModel(
        id=uuid4(), company_id=current_user.company_id, fornecedor_id=fornecedor_id,
        periodo=body.periodo, nota_prazo=body.nota_prazo, nota_qualidade=body.nota_qualidade,
        nota_preco=body.nota_preco, observacoes=body.observacoes, avaliado_por=current_user.id,
    )
    db.add(a)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "avaliacao_fornecedor", a.id,
        dados_novos={"fornecedor_id": str(fornecedor_id), "periodo": body.periodo},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return a


__all__ = ["router"]
