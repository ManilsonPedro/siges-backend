"""Requisições de compra internas (domínio Supply Chain / Compras)."""
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
from app.infrastructure.auth.dependencies import get_current_user, require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    PedidoCompraModel,
    PedidoCompraLinhaModel,
    RequisicaoLinhaModel,
    RequisicaoModel,
)


router = APIRouter()


# ─── DTOs ────────────────────────────────────────────────────────────


class RequisicaoLinhaInDTO(BaseModel):
    produto_id: Optional[UUID] = None
    descricao_livre: Optional[str] = None
    quantidade: Decimal = Field(..., gt=0)


class RequisicaoCreateDTO(BaseModel):
    departamento: Optional[str] = None
    justificativa: Optional[str] = None
    linhas: List[RequisicaoLinhaInDTO] = Field(..., min_length=1)


class RequisicaoLinhaResponseDTO(BaseModel):
    id: UUID
    produto_id: Optional[UUID] = None
    descricao_livre: Optional[str] = None
    quantidade: Decimal

    class Config:
        from_attributes = True


class RequisicaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    solicitante_id: UUID
    departamento: Optional[str] = None
    data: datetime
    justificativa: Optional[str] = None
    estado: str
    motivo_rejeicao: Optional[str] = None
    linhas: List[RequisicaoLinhaResponseDTO] = []
    created_at: datetime

    class Config:
        from_attributes = True


class RejeitarDTO(BaseModel):
    motivo: str = Field(..., min_length=1)


class ConverterPedidoDTO(BaseModel):
    fornecedor_id: UUID
    numero: str
    precos_unitarios: dict[str, Decimal]  # produto_id (str) -> preco_unitario


async def _load_requisicao(db: AsyncSession, id: UUID, current_user: User) -> RequisicaoModel:
    r = await db.execute(select(RequisicaoModel).where(RequisicaoModel.id == id))
    req = r.scalar_one_or_none()
    if not req or req.company_id != current_user.company_id or req.deleted_at is not None:
        raise HTTPException(404, "Requisição não encontrada")
    return req


async def _to_response(db: AsyncSession, req: RequisicaoModel) -> RequisicaoResponseDTO:
    lr = await db.execute(select(RequisicaoLinhaModel).where(RequisicaoLinhaModel.requisicao_id == req.id))
    linhas = [RequisicaoLinhaResponseDTO.model_validate(l) for l in lr.scalars().all()]
    dto = RequisicaoResponseDTO.model_validate(req)
    dto.linhas = linhas
    return dto


# ─── Endpoints ───────────────────────────────────────────────────────


@router.get("", response_model=List[RequisicaoResponseDTO])
async def list_requisicoes(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.ver")),
):
    stmt = (
        select(RequisicaoModel)
        .where(RequisicaoModel.company_id == current_user.company_id)
        .where(RequisicaoModel.deleted_at.is_(None))
    )
    if estado:
        stmt = stmt.where(RequisicaoModel.estado == estado)
    stmt = stmt.order_by(RequisicaoModel.created_at.desc())
    r = await db.execute(stmt)
    return [await _to_response(db, req) for req in r.scalars().all()]


@router.post("", response_model=RequisicaoResponseDTO, status_code=201)
async def create_requisicao(
    req: Request,
    body: RequisicaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.criar_requisicao")),
):
    r = RequisicaoModel(
        id=uuid4(), company_id=current_user.company_id,
        solicitante_id=current_user.id, departamento=body.departamento,
        justificativa=body.justificativa, estado="rascunho",
    )
    db.add(r)
    await db.flush()
    for l in body.linhas:
        db.add(RequisicaoLinhaModel(
            id=uuid4(), requisicao_id=r.id, produto_id=l.produto_id,
            descricao_livre=l.descricao_livre, quantidade=l.quantidade,
        ))
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "requisicao", r.id,
        dados_novos={"n_linhas": len(body.linhas)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, r)


@router.patch("/{id}/submeter", response_model=RequisicaoResponseDTO)
async def submeter_requisicao(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.criar_requisicao")),
):
    r = await _load_requisicao(db, id, current_user)
    if r.estado != "rascunho":
        raise HTTPException(400, "Só é possível submeter requisições em rascunho")
    r.estado = "submetida"
    r.updated_at = datetime.utcnow()
    await db.commit()
    return await _to_response(db, r)


@router.post("/{id}/aprovar", response_model=RequisicaoResponseDTO)
async def aprovar_requisicao(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.aprovar")),
):
    r = await _load_requisicao(db, id, current_user)
    if r.estado != "submetida":
        raise HTTPException(400, "Só é possível aprovar requisições submetidas")
    r.estado = "aprovada"
    r.updated_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "aprovada", "requisicao", r.id, dados_novos={},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, r)


@router.post("/{id}/rejeitar", response_model=RequisicaoResponseDTO)
async def rejeitar_requisicao(
    id: UUID,
    body: RejeitarDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.aprovar")),
):
    r = await _load_requisicao(db, id, current_user)
    if r.estado != "submetida":
        raise HTTPException(400, "Só é possível rejeitar requisições submetidas")
    r.estado = "rejeitada"
    r.motivo_rejeicao = body.motivo
    r.updated_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "rejeitada", "requisicao", r.id, dados_novos={"motivo": body.motivo},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, r)


@router.post("/{id}/converter-pedido")
async def converter_pedido(
    id: UUID,
    body: ConverterPedidoDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("compras.gerir_pedidos")),
):
    r = await _load_requisicao(db, id, current_user)
    if r.estado != "aprovada":
        raise HTTPException(400, "Só é possível converter requisições aprovadas")

    lr = await db.execute(select(RequisicaoLinhaModel).where(RequisicaoLinhaModel.requisicao_id == r.id))
    linhas_req = list(lr.scalars().all())
    sem_produto = [l for l in linhas_req if not l.produto_id]
    if sem_produto:
        raise HTTPException(400, "Todas as linhas precisam de produto_id associado para gerar um pedido")

    total = Decimal("0")
    pedido = PedidoCompraModel(
        id=uuid4(), company_id=current_user.company_id, requisicao_id=r.id,
        fornecedor_id=body.fornecedor_id, numero=body.numero, estado="enviado",
        created_by=current_user.id,
    )
    db.add(pedido)
    await db.flush()
    for l in linhas_req:
        preco = body.precos_unitarios.get(str(l.produto_id))
        if preco is None:
            raise HTTPException(400, f"Falta preco_unitario para produto {l.produto_id}")
        db.add(PedidoCompraLinhaModel(
            id=uuid4(), pedido_id=pedido.id, produto_id=l.produto_id,
            quantidade=l.quantidade, preco_unitario=preco,
        ))
        total += Decimal(l.quantidade) * Decimal(preco)
    pedido.total = total

    r.estado = "convertida_pedido"
    r.updated_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "convertida_pedido", "requisicao", r.id,
        dados_novos={"pedido_id": str(pedido.id)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"pedido_id": str(pedido.id)}


__all__ = ["router"]
