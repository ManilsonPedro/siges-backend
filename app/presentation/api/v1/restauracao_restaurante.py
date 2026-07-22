"""Restaurante (domínio Restauração) — Reservas + Conta da Mesa."""
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
from app.infrastructure.database.models import ComandaLinhaModel, ComandaModel, ReservaMesaModel


router = APIRouter()


class ReservaCreateDTO(BaseModel):
    mesa_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None
    nome_cliente: Optional[str] = None
    data_hora: datetime
    numero_pessoas: int = Field(default=2, gt=0)


class ReservaUpdateDTO(BaseModel):
    estado: Optional[str] = Field(None, pattern="^(confirmada|cancelada|concluida|no_show)$")


class ReservaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    mesa_id: Optional[UUID] = None
    cliente_id: Optional[str] = None
    nome_cliente: Optional[str] = None
    data_hora: datetime
    numero_pessoas: int
    estado: str

    class Config:
        from_attributes = True


@router.get("/reservas", response_model=List[ReservaResponseDTO])
async def list_reservas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    r = await db.execute(
        select(ReservaMesaModel)
        .where(ReservaMesaModel.company_id == current_user.company_id)
        .order_by(ReservaMesaModel.data_hora)
    )
    return list(r.scalars().all())


@router.post("/reservas", response_model=ReservaResponseDTO, status_code=201)
async def create_reserva(
    body: ReservaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_reservas")),
):
    m = ReservaMesaModel(
        id=uuid4(), company_id=current_user.company_id, mesa_id=body.mesa_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        nome_cliente=body.nome_cliente, data_hora=body.data_hora,
        numero_pessoas=body.numero_pessoas, estado="confirmada",
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/reservas/{id}", response_model=ReservaResponseDTO)
async def update_reserva(
    id: UUID,
    body: ReservaUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_reservas")),
):
    r = await db.execute(select(ReservaMesaModel).where(ReservaMesaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Reserva não encontrada")
    if body.estado:
        m.estado = body.estado
    await db.commit()
    return m


@router.get("/mesas/{id}/conta")
async def conta_mesa(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    """Agrega todas as comandas abertas da mesa — útil quando há divisão
    de conta por pessoa/comanda múltipla na mesma mesa."""
    cr = await db.execute(
        select(ComandaModel)
        .where(ComandaModel.mesa_id == id)
        .where(ComandaModel.company_id == current_user.company_id)
        .where(ComandaModel.estado == "aberta")
    )
    comandas = list(cr.scalars().all())
    total = Decimal("0")
    detalhe = []
    for c in comandas:
        lr = await db.execute(
            select(ComandaLinhaModel)
            .where(ComandaLinhaModel.comanda_id == c.id)
            .where(ComandaLinhaModel.estado != "cancelado")
        )
        linhas = list(lr.scalars().all())
        subtotal_comanda = sum((Decimal(l.preco_snapshot) * Decimal(l.quantidade) for l in linhas), Decimal("0"))
        total += subtotal_comanda
        detalhe.append({"comanda_id": str(c.id), "subtotal": float(subtotal_comanda), "n_linhas": len(linhas)})

    return {"mesa_id": str(id), "total": float(total), "comandas": detalhe}


@router.post("/mesas/{id}/fechar-conta")
async def fechar_conta_mesa(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.fechar_conta")),
):
    """Retorna a lista de comandas abertas da mesa para o operador fechar
    individualmente via POST /restauracao/comandas/{id}/fechar — evita
    duplicar a lógica de geração de Venda já implementada na base comum."""
    cr = await db.execute(
        select(ComandaModel)
        .where(ComandaModel.mesa_id == id)
        .where(ComandaModel.company_id == current_user.company_id)
        .where(ComandaModel.estado == "aberta")
    )
    comandas = list(cr.scalars().all())
    if not comandas:
        raise HTTPException(400, "Não há comandas abertas nesta mesa")
    return {"comandas_a_fechar": [str(c.id) for c in comandas]}


__all__ = ["router"]
