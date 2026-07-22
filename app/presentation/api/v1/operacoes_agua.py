"""Gestão da Água (domínio Operações): tanques, leituras, consumos, alertas."""
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
from app.infrastructure.database.models import ConsumoAguaModel, TanqueAguaModel


router = APIRouter()


class TanqueAguaCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=30)
    nome: str = Field(..., min_length=1, max_length=120)
    tipo: str = Field(..., pattern="^(limpa|reciclada|tratada|pluvial)$")
    capacidade_litros: Decimal = Field(..., gt=0)
    nivel_atual_litros: Decimal = Field(default=Decimal("0"), ge=0)
    nivel_minimo_litros: Decimal = Field(default=Decimal("0"), ge=0)
    tem_sensor: bool = False
    sensor_id: Optional[str] = None


class TanqueAguaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    nome: str
    tipo: str
    capacidade_litros: Decimal
    nivel_atual_litros: Decimal
    nivel_minimo_litros: Decimal
    ph: Optional[Decimal] = None
    turbidez: Optional[Decimal] = None
    condutividade: Optional[Decimal] = None
    tem_sensor: bool
    sensor_id: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/tanques", response_model=List[TanqueAguaResponseDTO])
async def list_tanques(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    r = await db.execute(
        select(TanqueAguaModel)
        .where(TanqueAguaModel.company_id == current_user.company_id)
        .where(TanqueAguaModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/tanques", response_model=TanqueAguaResponseDTO, status_code=201)
async def create_tanque(
    body: TanqueAguaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    m = TanqueAguaModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


class LeituraAguaDTO(BaseModel):
    nivel_litros: Optional[Decimal] = Field(None, ge=0)
    ph: Optional[Decimal] = None
    turbidez: Optional[Decimal] = None
    condutividade: Optional[Decimal] = None


PARAMETROS_LIMITE = {"ph_min": Decimal("6.5"), "ph_max": Decimal("8.5"), "turbidez_max": Decimal("5.0")}


@router.post("/tanques/{id}/leitura", response_model=TanqueAguaResponseDTO)
async def registar_leitura(
    id: UUID,
    req: Request,
    body: LeituraAguaDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.registar_leitura")),
):
    r = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.id == id))
    tanque = r.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id:
        raise HTTPException(404, "Tanque de água não encontrado")

    alertas = []
    if body.nivel_litros is not None:
        tanque.nivel_atual_litros = body.nivel_litros
        if body.nivel_litros <= tanque.nivel_minimo_litros:
            alertas.append("nivel_critico")
    if body.ph is not None:
        tanque.ph = body.ph
        if body.ph < PARAMETROS_LIMITE["ph_min"] or body.ph > PARAMETROS_LIMITE["ph_max"]:
            alertas.append("ph_fora_do_limite")
    if body.turbidez is not None:
        tanque.turbidez = body.turbidez
        if body.turbidez > PARAMETROS_LIMITE["turbidez_max"]:
            alertas.append("turbidez_alta")
    if body.condutividade is not None:
        tanque.condutividade = body.condutividade

    if alertas:
        await write_audit(
            db, current_user.id, current_user.company_id,
            "alerta_tanque_agua", "tanque_agua", tanque.id,
            dados_novos={"alertas": alertas},
            ip_address=req.client.host if req.client else None,
        )
    await db.commit()
    return tanque


class ConsumoAguaCreateDTO(BaseModel):
    tanque_agua_id: UUID
    litros_consumidos: Decimal = Field(..., gt=0)
    tipo: str = Field(..., pattern="^(lavagem|limpeza|outro)$")
    referencia_id: Optional[UUID] = None
    referencia_tipo: Optional[str] = None
    custo_por_litro: Optional[Decimal] = None


class ConsumoAguaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    tanque_agua_id: UUID
    litros_consumidos: Decimal
    tipo: str
    referencia_id: Optional[UUID] = None
    referencia_tipo: Optional[str] = None
    custo_por_litro: Optional[Decimal] = None
    custo_total: Optional[Decimal] = None
    data: datetime

    class Config:
        from_attributes = True


@router.get("/consumos", response_model=List[ConsumoAguaResponseDTO])
async def list_consumos(
    tanque_agua_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    stmt = select(ConsumoAguaModel).where(ConsumoAguaModel.company_id == current_user.company_id)
    if tanque_agua_id:
        stmt = stmt.where(ConsumoAguaModel.tanque_agua_id == tanque_agua_id)
    stmt = stmt.order_by(ConsumoAguaModel.data.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/consumos", response_model=ConsumoAguaResponseDTO, status_code=201)
async def create_consumo(
    body: ConsumoAguaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.registar_leitura")),
):
    tr = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.id == body.tanque_agua_id))
    tanque = tr.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id:
        raise HTTPException(404, "Tanque de água não encontrado")

    custo_total = (body.custo_por_litro * body.litros_consumidos) if body.custo_por_litro else None
    m = ConsumoAguaModel(
        id=uuid4(), company_id=current_user.company_id, tanque_agua_id=body.tanque_agua_id,
        litros_consumidos=body.litros_consumidos, tipo=body.tipo,
        referencia_id=body.referencia_id, referencia_tipo=body.referencia_tipo,
        custo_por_litro=body.custo_por_litro, custo_total=custo_total,
    )
    db.add(m)
    tanque.nivel_atual_litros = max(Decimal("0"), Decimal(tanque.nivel_atual_litros) - body.litros_consumidos)
    await db.commit()
    return m


@router.get("/indicadores")
async def indicadores(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    r = await db.execute(
        select(ConsumoAguaModel).where(ConsumoAguaModel.company_id == current_user.company_id)
    )
    consumos = list(r.scalars().all())
    total_litros = sum((Decimal(c.litros_consumidos) for c in consumos), Decimal("0"))
    total_custo = sum((Decimal(c.custo_total) for c in consumos if c.custo_total), Decimal("0"))

    tr = await db.execute(
        select(TanqueAguaModel)
        .where(TanqueAguaModel.company_id == current_user.company_id)
        .where(TanqueAguaModel.deleted_at.is_(None))
    )
    tanques = list(tr.scalars().all())
    total_reciclada = sum((Decimal(t.nivel_atual_litros) for t in tanques if t.tipo == "reciclada"), Decimal("0"))
    total_geral = sum((Decimal(t.nivel_atual_litros) for t in tanques), Decimal("0"))
    pct_reciclagem = (total_reciclada / total_geral * Decimal("100")) if total_geral > 0 else Decimal("0")

    return {
        "consumo_total_litros": float(total_litros),
        "custo_total": float(total_custo),
        "percentual_reciclagem": float(pct_reciclagem.quantize(Decimal("0.01"))),
    }


__all__ = ["router"]
