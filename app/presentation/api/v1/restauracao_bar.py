"""Bar (domínio Restauração) — especialização: Happy Hour.

Mesas/Comandas/ItensMenu são os endpoints comuns em restauracao_base.py,
filtrados por tipo_negocio='bar'.
"""
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
from app.infrastructure.database.models import HappyHourModel


router = APIRouter()


class HappyHourCreateDTO(BaseModel):
    dia_semana: int = Field(..., ge=0, le=6)
    hora_inicio: str = Field(..., pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    hora_fim: str = Field(..., pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    desconto_pct: Decimal = Field(..., gt=0, le=100)
    itens_aplicaveis: List[UUID] = Field(default_factory=list)


class HappyHourResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    dia_semana: int
    hora_inicio: str
    hora_fim: str
    desconto_pct: Decimal
    itens_aplicaveis: List[str] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, m: HappyHourModel) -> "HappyHourResponseDTO":
        return cls(
            id=m.id, company_id=m.company_id, dia_semana=int(m.dia_semana),
            hora_inicio=m.hora_inicio, hora_fim=m.hora_fim, desconto_pct=m.desconto_pct,
            itens_aplicaveis=json.loads(m.itens_aplicaveis) if m.itens_aplicaveis else [],
        )


@router.get("/happy-hour", response_model=List[HappyHourResponseDTO])
async def list_happy_hour(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    r = await db.execute(
        select(HappyHourModel)
        .where(HappyHourModel.company_id == current_user.company_id)
        .where(HappyHourModel.deleted_at.is_(None))
    )
    return [HappyHourResponseDTO.from_model(m) for m in r.scalars().all()]


@router.post("/happy-hour", response_model=HappyHourResponseDTO, status_code=201)
async def create_happy_hour(
    body: HappyHourCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_happy_hour")),
):
    m = HappyHourModel(
        id=uuid4(), company_id=current_user.company_id, dia_semana=body.dia_semana,
        hora_inicio=body.hora_inicio, hora_fim=body.hora_fim, desconto_pct=body.desconto_pct,
        itens_aplicaveis=json.dumps([str(i) for i in body.itens_aplicaveis]),
    )
    db.add(m)
    await db.commit()
    return HappyHourResponseDTO.from_model(m)


@router.delete("/happy-hour/{id}", status_code=204)
async def delete_happy_hour(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_happy_hour")),
):
    r = await db.execute(select(HappyHourModel).where(HappyHourModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Happy Hour não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


__all__ = ["router"]
