"""Combustível — Tanques, Bombas, Bicos, Abastecimentos (domínio Operações).

Controlo de perdas:
  Tanque Inicial + Receções − Abastecimentos = Teórico Final
  Comparação com Leitura Real gera Variação:
    > 0.5%  -> Alerta Amarelo
    > 1.0%  -> Alerta Vermelho + Auditoria obrigatória
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
from app.infrastructure.auth.dependencies import get_current_user, require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    AbastecimentoModel,
    BicoModel,
    BombaModel,
    LeituraTanqueModel,
    TanqueCombustivelModel,
)


router = APIRouter()


# ─── Tanques ─────────────────────────────────────────────────────────


class TanqueCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=30)
    tipo_combustivel: str = Field(..., pattern="^(gasolina|gasoleo|gpl|outro)$")
    capacidade_litros: Decimal = Field(..., gt=0)
    nivel_atual_litros: Decimal = Field(default=Decimal("0"), ge=0)
    nivel_minimo_litros: Decimal = Field(default=Decimal("0"), ge=0)
    nivel_reordenamento_litros: Decimal = Field(default=Decimal("0"), ge=0)


class TanqueResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    tipo_combustivel: str
    capacidade_litros: Decimal
    nivel_atual_litros: Decimal
    nivel_minimo_litros: Decimal
    nivel_reordenamento_litros: Decimal
    activo: bool

    class Config:
        from_attributes = True


@router.get("/tanques", response_model=List[TanqueResponseDTO])
async def list_tanques(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.view")),
):
    r = await db.execute(
        select(TanqueCombustivelModel)
        .where(TanqueCombustivelModel.company_id == current_user.company_id)
        .where(TanqueCombustivelModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/tanques", response_model=TanqueResponseDTO, status_code=201)
async def create_tanque(
    body: TanqueCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.gerir_bombas")),
):
    m = TanqueCombustivelModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


class LeituraTanqueDTO(BaseModel):
    nivel_litros: Decimal = Field(..., ge=0)
    temperatura: Optional[Decimal] = None
    origem: str = Field(default="manual", pattern="^(manual|sensor)$")


class LeituraResponseDTO(BaseModel):
    id: UUID
    tanque_id: UUID
    data_hora: datetime
    nivel_litros: Decimal
    temperatura: Optional[Decimal] = None
    origem: str

    class Config:
        from_attributes = True


@router.post("/tanques/{id}/leitura", response_model=LeituraResponseDTO)
async def registar_leitura(
    id: UUID,
    req: Request,
    body: LeituraTanqueDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.registar_leitura")),
):
    tr = await db.execute(select(TanqueCombustivelModel).where(TanqueCombustivelModel.id == id))
    tanque = tr.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id:
        raise HTTPException(404, "Tanque não encontrado")

    leitura = LeituraTanqueModel(
        id=uuid4(), tanque_id=id, nivel_litros=body.nivel_litros,
        temperatura=body.temperatura, origem=body.origem, operador_id=current_user.id,
    )
    db.add(leitura)
    tanque.nivel_atual_litros = body.nivel_litros

    if body.nivel_litros <= tanque.nivel_minimo_litros:
        await write_audit(
            db, current_user.id, current_user.company_id,
            "alerta_nivel_critico", "tanque_combustivel", tanque.id,
            dados_novos={"nivel_litros": str(body.nivel_litros), "minimo": str(tanque.nivel_minimo_litros)},
            ip_address=req.client.host if req.client else None,
        )
    await db.commit()
    return leitura


@router.get("/tanques/{id}/variacao")
async def calcular_variacao(
    id: UUID,
    teorico_final_litros: Decimal,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.ver_alertas_perda")),
):
    """Compara o nível real (última leitura) com o teórico informado
    (Tanque Inicial + Receções − Abastecimentos), calculado externamente
    pelo chamador a partir do histórico de movimentos/abastecimentos."""
    tr = await db.execute(select(TanqueCombustivelModel).where(TanqueCombustivelModel.id == id))
    tanque = tr.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id:
        raise HTTPException(404, "Tanque não encontrado")

    real = Decimal(tanque.nivel_atual_litros)
    if teorico_final_litros == 0:
        variacao_pct = Decimal("0")
    else:
        variacao_pct = ((real - teorico_final_litros) / teorico_final_litros * Decimal("100")).copy_abs()

    alerta = None
    if variacao_pct > Decimal("1.0"):
        alerta = "vermelho"
        await write_audit(
            db, current_user.id, current_user.company_id,
            "alerta_perda_critica", "tanque_combustivel", tanque.id,
            dados_novos={"variacao_pct": str(variacao_pct)},
            ip_address=req.client.host if req.client else None,
        )
        await db.commit()
    elif variacao_pct > Decimal("0.5"):
        alerta = "amarelo"

    return {
        "tanque_id": str(id), "nivel_real_litros": float(real),
        "teorico_final_litros": float(teorico_final_litros),
        "variacao_pct": float(variacao_pct.quantize(Decimal("0.01"))), "alerta": alerta,
    }


# ─── Bombas / Bicos ──────────────────────────────────────────────────


class BombaCreateDTO(BaseModel):
    area_servico_id: Optional[UUID] = None
    codigo: str = Field(..., min_length=1, max_length=30)
    tanque_id: UUID


class BombaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    area_servico_id: Optional[UUID] = None
    codigo: str
    tanque_id: UUID
    estado: str

    class Config:
        from_attributes = True


@router.get("/bombas", response_model=List[BombaResponseDTO])
async def list_bombas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.view")),
):
    r = await db.execute(
        select(BombaModel)
        .where(BombaModel.company_id == current_user.company_id)
        .where(BombaModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/bombas", response_model=BombaResponseDTO, status_code=201)
async def create_bomba(
    body: BombaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.gerir_bombas")),
):
    tr = await db.execute(
        select(TanqueCombustivelModel)
        .where(TanqueCombustivelModel.id == body.tanque_id)
        .where(TanqueCombustivelModel.company_id == current_user.company_id)
    )
    if not tr.scalar_one_or_none():
        raise HTTPException(404, "Tanque não encontrado")
    m = BombaModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump(), estado="operacional")
    db.add(m)
    await db.commit()
    return m


class BicoCreateDTO(BaseModel):
    bomba_id: UUID
    codigo: str = Field(..., min_length=1, max_length=20)
    tipo_combustivel: str = Field(..., pattern="^(gasolina|gasoleo|gpl|outro)$")


class BicoResponseDTO(BaseModel):
    id: UUID
    bomba_id: UUID
    codigo: str
    tipo_combustivel: str

    class Config:
        from_attributes = True


@router.get("/bicos", response_model=List[BicoResponseDTO])
async def list_bicos(
    bomba_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.view")),
):
    stmt = select(BicoModel).where(BicoModel.deleted_at.is_(None))
    if bomba_id:
        stmt = stmt.where(BicoModel.bomba_id == bomba_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/bicos", response_model=BicoResponseDTO, status_code=201)
async def create_bico(
    body: BicoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.gerir_bombas")),
):
    br = await db.execute(
        select(BombaModel).where(BombaModel.id == body.bomba_id).where(BombaModel.company_id == current_user.company_id)
    )
    if not br.scalar_one_or_none():
        raise HTTPException(404, "Bomba não encontrada")
    m = BicoModel(id=uuid4(), **body.model_dump())
    db.add(m)
    await db.commit()
    return m


# ─── Abastecimentos ──────────────────────────────────────────────────


class AbastecimentoCreateDTO(BaseModel):
    bico_id: UUID
    volume_litros: Decimal = Field(..., gt=0)
    preco_unitario: Decimal = Field(..., gt=0)
    cliente_id: Optional[UUID] = None
    forma_pagamento: str = Field(..., pattern="^(numerario|tpa|transferencia)$")


class AbastecimentoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    bico_id: UUID
    tanque_id: UUID
    tipo_combustivel: str
    volume_litros: Decimal
    preco_unitario: Decimal
    total: Decimal
    forma_pagamento: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/abastecimentos", response_model=List[AbastecimentoResponseDTO])
async def list_abastecimentos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.combustivel.view")),
):
    r = await db.execute(
        select(AbastecimentoModel)
        .where(AbastecimentoModel.company_id == current_user.company_id)
        .order_by(AbastecimentoModel.created_at.desc())
    )
    return list(r.scalars().all())


@router.post("/abastecimentos", response_model=AbastecimentoResponseDTO, status_code=201)
async def registar_abastecimento(
    req: Request,
    body: AbastecimentoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    br = await db.execute(select(BicoModel).where(BicoModel.id == body.bico_id))
    bico = br.scalar_one_or_none()
    if not bico:
        raise HTTPException(404, "Bico não encontrado")
    bomba_r = await db.execute(select(BombaModel).where(BombaModel.id == bico.bomba_id))
    bomba = bomba_r.scalar_one_or_none()
    if not bomba or bomba.company_id != current_user.company_id:
        raise HTTPException(404, "Bomba não encontrada")
    tanque_r = await db.execute(select(TanqueCombustivelModel).where(TanqueCombustivelModel.id == bomba.tanque_id))
    tanque = tanque_r.scalar_one()

    if Decimal(tanque.nivel_atual_litros) < body.volume_litros:
        raise HTTPException(409, f"Nível de tanque insuficiente: {tanque.nivel_atual_litros}L disponíveis")

    total = (body.volume_litros * body.preco_unitario).quantize(Decimal("0.01"))
    aba = AbastecimentoModel(
        id=uuid4(), company_id=current_user.company_id, bico_id=body.bico_id,
        tanque_id=tanque.id, tipo_combustivel=bico.tipo_combustivel,
        volume_litros=body.volume_litros, preco_unitario=body.preco_unitario, total=total,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        forma_pagamento=body.forma_pagamento, operador_id=current_user.id,
    )
    db.add(aba)
    tanque.nivel_atual_litros = Decimal(tanque.nivel_atual_litros) - body.volume_litros
    await write_audit(
        db, current_user.id, current_user.company_id,
        "abastecimento", "abastecimento", aba.id,
        dados_novos={"volume_litros": str(body.volume_litros), "total": str(total)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return aba


__all__ = ["router"]
