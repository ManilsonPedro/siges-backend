"""Churrasqueira (domínio Restauração) — Combos + KDS (fila de produção)."""
from __future__ import annotations

import json
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
from app.infrastructure.database.models import ComboModel, PedidoProducaoModel


router = APIRouter()


class ComboCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=150)
    itens: List[dict] = Field(..., min_length=1)  # [{item_menu_id, quantidade}]
    preco_combo: Decimal = Field(..., gt=0)
    activo: bool = True


class ComboResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    itens: List[dict] = []
    preco_combo: Decimal
    activo: bool

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, m: ComboModel) -> "ComboResponseDTO":
        return cls(
            id=m.id, company_id=m.company_id, nome=m.nome,
            itens=json.loads(m.itens), preco_combo=m.preco_combo, activo=m.activo,
        )


@router.get("/combos", response_model=List[ComboResponseDTO])
async def list_combos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    r = await db.execute(
        select(ComboModel)
        .where(ComboModel.company_id == current_user.company_id)
        .where(ComboModel.deleted_at.is_(None))
    )
    return [ComboResponseDTO.from_model(m) for m in r.scalars().all()]


@router.post("/combos", response_model=ComboResponseDTO, status_code=201)
async def create_combo(
    body: ComboCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_combos")),
):
    m = ComboModel(
        id=uuid4(), company_id=current_user.company_id, nome=body.nome,
        itens=json.dumps(body.itens), preco_combo=body.preco_combo, activo=body.activo,
    )
    db.add(m)
    await db.commit()
    return ComboResponseDTO.from_model(m)


@router.delete("/combos/{id}", status_code=204)
async def delete_combo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_combos")),
):
    r = await db.execute(select(ComboModel).where(ComboModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Combo não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Fila de Produção (KDS) ──────────────────────────────────────────


class PedidoProducaoCreateDTO(BaseModel):
    comanda_linha_id: Optional[UUID] = None
    estacao_producao: Optional[str] = None
    tempo_estimado_minutos: Optional[int] = None


class PedidoProducaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    comanda_linha_id: Optional[UUID] = None
    estado: str
    estacao_producao: Optional[str] = None
    tempo_estimado_minutos: Optional[int] = None
    criado_em: datetime

    class Config:
        from_attributes = True


@router.get("/pedidos-producao", response_model=List[PedidoProducaoResponseDTO])
async def list_pedidos_producao(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    stmt = select(PedidoProducaoModel).where(PedidoProducaoModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(PedidoProducaoModel.estado == estado)
    stmt = stmt.order_by(PedidoProducaoModel.criado_em)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/pedidos-producao", response_model=PedidoProducaoResponseDTO, status_code=201)
async def create_pedido_producao(
    body: PedidoProducaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_producao")),
):
    m = PedidoProducaoModel(
        id=uuid4(), company_id=current_user.company_id, estado="fila", **body.model_dump()
    )
    db.add(m)
    await db.commit()
    return m


@router.post("/pedidos-producao/{id}/avancar-estado", response_model=PedidoProducaoResponseDTO)
async def avancar_estado(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_producao")),
):
    r = await db.execute(select(PedidoProducaoModel).where(PedidoProducaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Pedido de produção não encontrado")
    proximos = {"fila": "em_preparacao", "em_preparacao": "pronto"}
    if m.estado not in proximos:
        raise HTTPException(400, "Pedido já está pronto")
    m.estado = proximos[m.estado]
    await db.commit()
    return m


@router.get("/kds", response_model=List[PedidoProducaoResponseDTO])
async def kds(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_producao")),
):
    """Kitchen Display System — fila de produção em tempo real via polling."""
    r = await db.execute(
        select(PedidoProducaoModel)
        .where(PedidoProducaoModel.company_id == current_user.company_id)
        .where(PedidoProducaoModel.estado != "pronto")
        .order_by(PedidoProducaoModel.criado_em)
    )
    return list(r.scalars().all())


__all__ = ["router"]
