"""Lavagem Automóvel (domínio Operações).

Máquina de estados:
  rascunho -> agendada -> confirmada -> checkin -> em_curso
  -> controlo_qualidade -> concluida -> paga

Regras:
  1. Slot só reservável se estado = disponivel.
  2. Check-in permitido dentro de ±15 min do horário agendado.
  3. Início requer box_id e equipa atribuídos.
  4. Consumo de água/químicos registado manualmente (porta IoT futura).
  5. Controlo de qualidade obrigatório antes de concluir (pontuação 1-5).
  6. Pontuação < 3 dispara alerta e permite oferecer re-lavagem.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.domain.services import stock_service
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    AnexoModel,
    BoxLavagemModel,
    CategoriaVeiculoModel,
    ConsumoAguaModel,
    ControloQualidadeLavagemModel,
    EquipaLavagemModel,
    EquipaMembroModel,
    EscalaTurnoModel,
    ExtraLavagemModel,
    OrdemLavagemExtraModel,
    OrdemLavagemModel,
    SlotLavagemModel,
    TanqueAguaModel,
    TipoLavagemModel,
    TurnoOperacionalModel,
    ViaturaModel,
)
from app.infrastructure.storage import get_storage_provider
from app.presentation.api.v1.anexos import listar_anexos_por_tipo


router = APIRouter()


# ─── Categorias de Veículo ───────────────────────────────────────────


class CategoriaVeiculoCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=30)
    nome: str = Field(..., min_length=1, max_length=80)
    fator_preco: Decimal = Field(default=Decimal("1"), gt=0)
    fator_agua: Decimal = Field(default=Decimal("1"), gt=0)
    ordem: int = Field(default=0, ge=0)
    activo: bool = True


class CategoriaVeiculoUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=80)
    fator_preco: Optional[Decimal] = Field(None, gt=0)
    fator_agua: Optional[Decimal] = Field(None, gt=0)
    ordem: Optional[int] = Field(None, ge=0)
    activo: Optional[bool] = None


class CategoriaVeiculoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    nome: str
    fator_preco: Decimal
    fator_agua: Decimal
    ordem: int
    activo: bool

    class Config:
        from_attributes = True


@router.get("/categorias-veiculo", response_model=List[CategoriaVeiculoResponseDTO])
async def list_categorias_veiculo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    r = await db.execute(
        select(CategoriaVeiculoModel)
        .where(CategoriaVeiculoModel.company_id == current_user.company_id)
        .where(CategoriaVeiculoModel.deleted_at.is_(None))
        .order_by(CategoriaVeiculoModel.ordem)
    )
    return list(r.scalars().all())


@router.post("/categorias-veiculo", response_model=CategoriaVeiculoResponseDTO, status_code=201)
async def create_categoria_veiculo(
    body: CategoriaVeiculoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = CategoriaVeiculoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/categorias-veiculo/{id}", response_model=CategoriaVeiculoResponseDTO)
async def update_categoria_veiculo(
    id: UUID,
    body: CategoriaVeiculoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(CategoriaVeiculoModel).where(CategoriaVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Categoria de veículo não encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await db.commit()
    return m


@router.delete("/categorias-veiculo/{id}", status_code=204)
async def delete_categoria_veiculo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(CategoriaVeiculoModel).where(CategoriaVeiculoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Categoria de veículo não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Extras de Lavagem ───────────────────────────────────────────────


class ExtraLavagemCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=30)
    nome: str = Field(..., min_length=1, max_length=120)
    preco: Decimal = Field(..., ge=0)
    duracao_adicional_minutos: int = Field(default=0, ge=0)
    activo: bool = True


class ExtraLavagemUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=120)
    preco: Optional[Decimal] = Field(None, ge=0)
    duracao_adicional_minutos: Optional[int] = Field(None, ge=0)
    activo: Optional[bool] = None


class ExtraLavagemResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    nome: str
    preco: Decimal
    duracao_adicional_minutos: int
    activo: bool

    class Config:
        from_attributes = True


@router.get("/extras", response_model=List[ExtraLavagemResponseDTO])
async def list_extras(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    r = await db.execute(
        select(ExtraLavagemModel)
        .where(ExtraLavagemModel.company_id == current_user.company_id)
        .where(ExtraLavagemModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/extras", response_model=ExtraLavagemResponseDTO, status_code=201)
async def create_extra(
    body: ExtraLavagemCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = ExtraLavagemModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/extras/{id}", response_model=ExtraLavagemResponseDTO)
async def update_extra(
    id: UUID,
    body: ExtraLavagemUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(ExtraLavagemModel).where(ExtraLavagemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Extra não encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await db.commit()
    return m


@router.delete("/extras/{id}", status_code=204)
async def delete_extra(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(ExtraLavagemModel).where(ExtraLavagemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Extra não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Viaturas (walk-in ou cliente cadastrado) ────────────────────────


class ViaturaCreateDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    matricula: str = Field(..., min_length=1, max_length=20)
    marca: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None
    categoria_veiculo_id: Optional[UUID] = None


class ViaturaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    matricula: str
    marca: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None
    categoria_veiculo_id: Optional[UUID] = None

    class Config:
        from_attributes = True


@router.get("/viaturas", response_model=List[ViaturaResponseDTO])
async def list_viaturas(
    matricula: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    stmt = (
        select(ViaturaModel)
        .where(ViaturaModel.company_id == current_user.company_id)
        .where(ViaturaModel.deleted_at.is_(None))
    )
    if matricula:
        stmt = stmt.where(ViaturaModel.matricula.ilike(f"%{matricula}%"))
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/viaturas", response_model=ViaturaResponseDTO, status_code=201)
async def create_viatura(
    body: ViaturaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.agendar")),
):
    m = ViaturaModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        matricula=body.matricula, marca=body.marca, modelo=body.modelo,
        cor=body.cor, categoria_veiculo_id=body.categoria_veiculo_id,
    )
    db.add(m)
    await db.commit()
    return m


# ─── Equipas e Escalas (Sprint 4) ─────────────────────────────────────


class EquipaCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    activo: bool = True
    membro_user_ids: List[UUID] = Field(default_factory=list)


class EquipaUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=120)
    activo: Optional[bool] = None


class EquipaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    activo: bool
    membro_user_ids: List[UUID] = []

    class Config:
        from_attributes = True


async def _to_equipa_response(db: AsyncSession, e: EquipaLavagemModel) -> EquipaResponseDTO:
    mr = await db.execute(select(EquipaMembroModel.user_id).where(EquipaMembroModel.equipa_id == e.id))
    dto = EquipaResponseDTO.model_validate(e)
    dto.membro_user_ids = [row[0] for row in mr.all()]
    return dto


@router.get("/equipas", response_model=List[EquipaResponseDTO])
async def list_equipas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    r = await db.execute(
        select(EquipaLavagemModel)
        .where(EquipaLavagemModel.company_id == current_user.company_id)
        .where(EquipaLavagemModel.deleted_at.is_(None))
    )
    return [await _to_equipa_response(db, e) for e in r.scalars().all()]


@router.post("/equipas", response_model=EquipaResponseDTO, status_code=201)
async def create_equipa(
    body: EquipaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = EquipaLavagemModel(id=uuid4(), company_id=current_user.company_id, nome=body.nome, activo=body.activo)
    db.add(m)
    await db.flush()
    for user_id in body.membro_user_ids:
        db.add(EquipaMembroModel(id=uuid4(), equipa_id=m.id, user_id=user_id))
    await db.commit()
    return await _to_equipa_response(db, m)


@router.patch("/equipas/{id}", response_model=EquipaResponseDTO)
async def update_equipa(
    id: UUID,
    body: EquipaUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(EquipaLavagemModel).where(EquipaLavagemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Equipa não encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    await db.commit()
    return await _to_equipa_response(db, m)


@router.delete("/equipas/{id}", status_code=204)
async def delete_equipa(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(EquipaLavagemModel).where(EquipaLavagemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Equipa não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


class EquipaMembroCreateDTO(BaseModel):
    user_id: UUID


@router.post("/equipas/{id}/membros", response_model=EquipaResponseDTO, status_code=201)
async def add_membro_equipa(
    id: UUID,
    body: EquipaMembroCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(EquipaLavagemModel).where(EquipaLavagemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Equipa não encontrada")
    db.add(EquipaMembroModel(id=uuid4(), equipa_id=id, user_id=body.user_id))
    await db.commit()
    return await _to_equipa_response(db, m)


@router.delete("/equipas/{id}/membros/{user_id}", status_code=204)
async def remove_membro_equipa(
    id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(EquipaLavagemModel).where(EquipaLavagemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Equipa não encontrada")
    mr = await db.execute(
        select(EquipaMembroModel)
        .where(EquipaMembroModel.equipa_id == id)
        .where(EquipaMembroModel.user_id == user_id)
    )
    membro = mr.scalar_one_or_none()
    if membro:
        await db.delete(membro)
        await db.commit()


class EscalaCreateDTO(BaseModel):
    equipa_id: UUID
    box_id: UUID
    turno_id: UUID
    data: datetime
    activo: bool = True


class EscalaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    equipa_id: UUID
    box_id: UUID
    turno_id: UUID
    data: datetime
    activo: bool

    class Config:
        from_attributes = True


@router.get("/escalas", response_model=List[EscalaResponseDTO])
async def list_escalas(
    data: Optional[datetime] = None,
    box_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    stmt = (
        select(EscalaTurnoModel)
        .where(EscalaTurnoModel.company_id == current_user.company_id)
        .where(EscalaTurnoModel.activo.is_(True))
    )
    if data:
        stmt = stmt.where(EscalaTurnoModel.data == data)
    if box_id:
        stmt = stmt.where(EscalaTurnoModel.box_id == box_id)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/escalas", response_model=EscalaResponseDTO, status_code=201)
async def create_escala(
    body: EscalaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = EscalaTurnoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/escalas/{id}", status_code=204)
async def delete_escala(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(EscalaTurnoModel).where(EscalaTurnoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Escala não encontrada")
    m.activo = False
    await db.commit()


async def _atribuir_equipa_automatica(
    db: AsyncSession, *, company_id: UUID, box_id: UUID,
) -> Optional[str]:
    """Procura a EscalaTurno para (box_id, hoje, turno correspondente à hora
    actual) e devolve o CSV de user_id da equipa escalada, ou None se não
    houver escala (D7: atribuição automática, nunca manual por ordem)."""
    agora = datetime.utcnow()
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)

    tr = await db.execute(
        select(TurnoOperacionalModel).where(TurnoOperacionalModel.company_id == company_id)
    )
    turno_atual = None
    hora_actual = agora.strftime("%H:%M")
    for turno in tr.scalars().all():
        if turno.hora_inicio <= turno.hora_fim:
            dentro = turno.hora_inicio <= hora_actual <= turno.hora_fim
        else:  # turno atravessa a meia-noite
            dentro = hora_actual >= turno.hora_inicio or hora_actual <= turno.hora_fim
        if dentro:
            turno_atual = turno
            break
    if not turno_atual:
        return None

    er = await db.execute(
        select(EscalaTurnoModel)
        .where(EscalaTurnoModel.company_id == company_id)
        .where(EscalaTurnoModel.box_id == box_id)
        .where(EscalaTurnoModel.turno_id == turno_atual.id)
        .where(EscalaTurnoModel.data == inicio_dia)
        .where(EscalaTurnoModel.activo.is_(True))
    )
    escala = er.scalar_one_or_none()
    if not escala:
        return None

    mr = await db.execute(select(EquipaMembroModel.user_id).where(EquipaMembroModel.equipa_id == escala.equipa_id))
    user_ids = [str(row[0]) for row in mr.all()]
    return ",".join(user_ids)


# ─── Cálculo de preço (Sprint 1 — usado por Ordens) ──────────────────


async def _calcular_preco_ordem(
    db: AsyncSession, *, tipo_lavagem_id: UUID, categoria_veiculo_id: Optional[UUID],
    extra_ids: List[UUID],
) -> tuple[Decimal, List[tuple[UUID, Decimal]]]:
    """Devolve (preco_total, [(extra_id, preco_aplicado), ...]).

    preco_total = TipoLavagem.preco_base * CategoriaVeiculo.fator_preco + soma(extras.preco)
    Sem categoria informada, fator_preco = 1 (comportamento antigo preservado).
    """
    tr = await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == tipo_lavagem_id))
    tipo = tr.scalar_one_or_none()
    if not tipo:
        raise HTTPException(404, "Tipo de lavagem não encontrado")

    fator = Decimal("1")
    if categoria_veiculo_id:
        cr = await db.execute(select(CategoriaVeiculoModel).where(CategoriaVeiculoModel.id == categoria_veiculo_id))
        cat = cr.scalar_one_or_none()
        if cat:
            fator = Decimal(cat.fator_preco)

    total = Decimal(tipo.preco_base) * fator
    extras_aplicados: List[tuple[UUID, Decimal]] = []
    for extra_id in extra_ids:
        er = await db.execute(select(ExtraLavagemModel).where(ExtraLavagemModel.id == extra_id))
        extra = er.scalar_one_or_none()
        if not extra:
            raise HTTPException(404, f"Extra {extra_id} não encontrado")
        extras_aplicados.append((extra_id, Decimal(extra.preco)))
        total += Decimal(extra.preco)

    return total, extras_aplicados


async def _calcular_agua_estimada(db: AsyncSession, o: OrdemLavagemModel) -> Decimal:
    """agua_consumida_litros = TipoLavagem.agua_estimada_litros * CategoriaVeiculo.fator_agua
    (D3, Sprint 5). Valor por omissão — o operador pode ajustar manualmente se a
    medição real divergir (ver ConsumoDTO.agua_consumida_litros)."""
    tr = await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == o.tipo_lavagem_id))
    tipo = tr.scalar_one_or_none()
    if not tipo:
        return Decimal("0")

    fator = Decimal("1")
    if o.viatura_id:
        vr = await db.execute(select(ViaturaModel).where(ViaturaModel.id == UUID(o.viatura_id)))
        viatura = vr.scalar_one_or_none()
        if viatura and viatura.categoria_veiculo_id:
            cr = await db.execute(select(CategoriaVeiculoModel).where(CategoriaVeiculoModel.id == viatura.categoria_veiculo_id))
            cat = cr.scalar_one_or_none()
            if cat:
                fator = Decimal(cat.fator_agua)

    return Decimal(tipo.agua_estimada_litros) * fator


# ─── Tipos de Lavagem ────────────────────────────────────────────────


class TipoLavagemCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=30)
    nome: str = Field(..., min_length=1, max_length=120)
    descricao: Optional[str] = None
    preco_base: Decimal = Field(..., gt=0)
    duracao_estimada_minutos: int = Field(default=30, gt=0)
    agua_estimada_litros: Decimal = Field(default=Decimal("0"), ge=0)


class TipoLavagemResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    nome: str
    descricao: Optional[str] = None
    preco_base: Decimal
    duracao_estimada_minutos: int
    agua_estimada_litros: Decimal
    activo: bool

    class Config:
        from_attributes = True


@router.get("/tipos", response_model=List[TipoLavagemResponseDTO])
async def list_tipos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    r = await db.execute(
        select(TipoLavagemModel)
        .where(TipoLavagemModel.company_id == current_user.company_id)
        .where(TipoLavagemModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/tipos", response_model=TipoLavagemResponseDTO, status_code=201)
async def create_tipo(
    body: TipoLavagemCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = TipoLavagemModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/tipos/{id}", status_code=204)
async def delete_tipo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    r = await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Tipo de lavagem não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Boxes ───────────────────────────────────────────────────────────


class BoxCreateDTO(BaseModel):
    area_servico_id: Optional[UUID] = None
    filial_id: Optional[UUID] = None
    codigo: str = Field(..., min_length=1, max_length=20)
    nome: str = Field(..., min_length=1, max_length=120)
    capacidade: int = Field(default=1, gt=0)


class BoxResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    filial_id: Optional[UUID] = None
    codigo: str
    nome: str
    estado: str
    capacidade: int

    class Config:
        from_attributes = True


@router.get("/boxes", response_model=List[BoxResponseDTO])
async def list_boxes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    r = await db.execute(
        select(BoxLavagemModel)
        .where(BoxLavagemModel.company_id == current_user.company_id)
        .where(BoxLavagemModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/boxes", response_model=BoxResponseDTO, status_code=201)
async def create_box(
    body: BoxCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.gerir_tipos")),
):
    m = BoxLavagemModel(id=uuid4(), company_id=current_user.company_id, estado="disponivel", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


# ─── Slots ───────────────────────────────────────────────────────────


class SlotCreateDTO(BaseModel):
    box_id: UUID
    data_hora_inicio: datetime
    data_hora_fim: datetime
    preco_override: Optional[Decimal] = None


class SlotResponseDTO(BaseModel):
    id: UUID
    box_id: UUID
    data_hora_inicio: datetime
    data_hora_fim: datetime
    estado: str
    preco_override: Optional[Decimal] = None

    class Config:
        from_attributes = True


@router.get("/slots", response_model=List[SlotResponseDTO])
async def list_slots(
    box_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    stmt = select(SlotLavagemModel)
    if box_id:
        stmt = stmt.where(SlotLavagemModel.box_id == box_id)
    if estado:
        stmt = stmt.where(SlotLavagemModel.estado == estado)
    stmt = stmt.order_by(SlotLavagemModel.data_hora_inicio)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/slots", response_model=SlotResponseDTO, status_code=201)
async def create_slot(
    body: SlotCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.agendar")),
):
    m = SlotLavagemModel(id=uuid4(), estado="disponivel", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


# ─── Ordens de Lavagem ───────────────────────────────────────────────


class OrdemCreateDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    viatura_id: Optional[UUID] = None
    tipo_lavagem_id: UUID
    slot_id: Optional[UUID] = None
    box_id: Optional[UUID] = None
    extra_ids: List[UUID] = Field(default_factory=list)
    origem: str = Field(default="backoffice_walkin", pattern="^(portal_cliente|backoffice_walkin|backoffice_telefone)$")


class ConsumoDTO(BaseModel):
    agua_consumida_litros: Optional[Decimal] = None
    quimicos: List[dict] = Field(default_factory=list)  # [{"produto_id": "...", "quantidade": 1.5}]
    armazem_id: Optional[UUID] = None


class QualidadeDTO(BaseModel):
    pontuacao: int = Field(..., ge=1, le=5)
    observacoes: Optional[str] = None


class ExtraAplicadoDTO(BaseModel):
    extra_id: UUID
    preco_aplicado: Decimal

    class Config:
        from_attributes = True


class OrdemResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    viatura_id: Optional[str] = None
    tipo_lavagem_id: UUID
    box_id: Optional[UUID] = None
    slot_id: Optional[UUID] = None
    estado: str
    origem: str
    equipa: Optional[str] = None
    colaborador_responsavel_id: Optional[UUID] = None
    no_show: bool = False
    agua_consumida_litros: Optional[Decimal] = None
    re_lavagem_de_id: Optional[UUID] = None
    preco_total: Optional[Decimal] = None
    extras: List[ExtraAplicadoDTO] = []
    created_at: datetime

    class Config:
        from_attributes = True


async def _load_ordem(db: AsyncSession, id: UUID, current_user: User) -> OrdemLavagemModel:
    r = await db.execute(select(OrdemLavagemModel).where(OrdemLavagemModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.company_id != current_user.company_id:
        raise HTTPException(404, "Ordem de lavagem não encontrada")
    return o


async def _calcular_preco_atual(db: AsyncSession, o: OrdemLavagemModel) -> tuple[Decimal, list]:
    """Preço da ordem calculado *agora* (tipo+categoria+extras vigentes).

    Só reflecte o catálogo actual — usar `preco_total_snapshot` (gravado na
    conclusão) para valores históricos que não mudam se o catálogo mudar
    depois (ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md, Fase 3).
    """
    er = await db.execute(select(OrdemLavagemExtraModel).where(OrdemLavagemExtraModel.ordem_lavagem_id == o.id))
    extras = list(er.scalars().all())

    categoria_veiculo_id = None
    if o.viatura_id:
        vr = await db.execute(select(ViaturaModel).where(ViaturaModel.id == UUID(o.viatura_id)))
        viatura = vr.scalar_one_or_none()
        if viatura:
            categoria_veiculo_id = viatura.categoria_veiculo_id

    preco_total, _ = await _calcular_preco_ordem(
        db, tipo_lavagem_id=o.tipo_lavagem_id, categoria_veiculo_id=categoria_veiculo_id,
        extra_ids=[e.extra_id for e in extras],
    )
    return preco_total, extras


async def _to_response(db: AsyncSession, o: OrdemLavagemModel) -> OrdemResponseDTO:
    er = await db.execute(select(OrdemLavagemExtraModel).where(OrdemLavagemExtraModel.ordem_lavagem_id == o.id))
    extras = list(er.scalars().all())

    if o.preco_total_snapshot is not None:
        preco_total = Decimal(o.preco_total_snapshot)
    else:
        preco_total, extras = await _calcular_preco_atual(db, o)

    dto = OrdemResponseDTO.model_validate(o)
    dto.preco_total = preco_total
    dto.extras = [ExtraAplicadoDTO.model_validate(e) for e in extras]
    return dto


@router.get("/ordens", response_model=List[OrdemResponseDTO])
async def list_ordens(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    stmt = select(OrdemLavagemModel).where(OrdemLavagemModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(OrdemLavagemModel.estado == estado)
    stmt = stmt.order_by(OrdemLavagemModel.created_at.desc())
    r = await db.execute(stmt)
    return [await _to_response(db, o) for o in r.scalars().all()]


@router.post("/ordens", response_model=OrdemResponseDTO, status_code=201)
async def create_ordem(
    req: Request,
    body: OrdemCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.agendar")),
):
    estado_inicial = "rascunho"
    if body.slot_id:
        sr = await db.execute(select(SlotLavagemModel).where(SlotLavagemModel.id == body.slot_id))
        slot = sr.scalar_one_or_none()
        if not slot:
            raise HTTPException(404, "Slot não encontrado")
        if slot.estado != "disponivel":
            raise HTTPException(409, "Slot não está disponível")
        slot.estado = "reservado"
        estado_inicial = "agendada"

    categoria_veiculo_id = None
    if body.viatura_id:
        vr = await db.execute(select(ViaturaModel).where(ViaturaModel.id == body.viatura_id))
        viatura = vr.scalar_one_or_none()
        if viatura:
            categoria_veiculo_id = viatura.categoria_veiculo_id

    # valida tipo de lavagem e extras existem antes de persistir
    _, extras_aplicados = await _calcular_preco_ordem(
        db, tipo_lavagem_id=body.tipo_lavagem_id, categoria_veiculo_id=categoria_veiculo_id,
        extra_ids=body.extra_ids,
    )

    m = OrdemLavagemModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        viatura_id=str(body.viatura_id) if body.viatura_id else None,
        tipo_lavagem_id=body.tipo_lavagem_id, box_id=body.box_id, slot_id=body.slot_id,
        estado=estado_inicial, origem=body.origem,
    )
    db.add(m)
    await db.flush()

    for extra_id, preco_aplicado in extras_aplicados:
        db.add(OrdemLavagemExtraModel(
            id=uuid4(), ordem_lavagem_id=m.id, extra_id=extra_id, preco_aplicado=preco_aplicado,
        ))

    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "ordem_lavagem", m.id,
        dados_novos={"tipo_lavagem_id": str(body.tipo_lavagem_id), "origem": body.origem},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, m)


@router.post("/ordens/{id}/checkin", response_model=OrdemResponseDTO)
async def checkin(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    o = await _load_ordem(db, id, current_user)
    if o.estado not in ("agendada", "confirmada"):
        raise HTTPException(400, "Só é possível fazer check-in de ordens agendadas/confirmadas")
    if o.slot_id:
        sr = await db.execute(select(SlotLavagemModel).where(SlotLavagemModel.id == o.slot_id))
        slot = sr.scalar_one_or_none()
        if slot:
            agora = datetime.utcnow()
            janela = timedelta(minutes=15)
            if not (slot.data_hora_inicio - janela <= agora <= slot.data_hora_inicio + janela):
                raise HTTPException(400, "Check-in só permitido dentro de ±15 min do horário agendado")
    o.estado = "checkin"
    o.checkin_em = datetime.utcnow()
    o.updated_at = o.checkin_em
    await db.commit()
    return await _to_response(db, o)


@router.post("/ordens/{id}/no-show", response_model=OrdemResponseDTO)
async def marcar_no_show(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    """Cliente reservou e não apareceu (distinto de cancelamento activo,
    ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md, Fase 6). Só faz sentido
    antes do check-in — depois disso já houve comparência."""
    o = await _load_ordem(db, id, current_user)
    if o.estado not in ("agendada", "confirmada"):
        raise HTTPException(400, "Só é possível marcar não-comparência antes do check-in")
    if o.slot_id:
        sr = await db.execute(select(SlotLavagemModel).where(SlotLavagemModel.id == o.slot_id))
        slot = sr.scalar_one_or_none()
        if slot:
            slot.estado = "disponivel"
    o.estado = "cancelada"
    o.no_show = True
    o.updated_at = datetime.utcnow()
    await db.commit()
    return await _to_response(db, o)


@router.post("/ordens/{id}/iniciar", response_model=OrdemResponseDTO)
async def iniciar(
    id: UUID,
    box_id: Optional[UUID] = None,
    colaborador_responsavel_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    o = await _load_ordem(db, id, current_user)
    if o.estado != "checkin":
        raise HTTPException(400, "Ordem precisa de check-in antes de iniciar")
    if box_id:
        o.box_id = box_id
    if not o.box_id:
        raise HTTPException(400, "Início requer box atribuído")

    equipa_csv = await _atribuir_equipa_automatica(db, company_id=current_user.company_id, box_id=o.box_id)
    if not equipa_csv:
        raise HTTPException(400, "Nenhuma equipa escalada para este box neste turno — escale uma equipa primeiro")
    o.equipa = equipa_csv

    # Atribuição individual opcional (D7 continua colectivo por omissão —
    # ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md, Fase 4). Se indicado, o
    # operador confirma que este membro da equipa é o responsável directo.
    if colaborador_responsavel_id:
        equipa_ids = {UUID(uid) for uid in equipa_csv.split(",") if uid}
        if colaborador_responsavel_id not in equipa_ids:
            raise HTTPException(400, "Colaborador indicado não pertence à equipa escalada para este box/turno")
        o.colaborador_responsavel_id = colaborador_responsavel_id

    o.estado = "em_curso"
    o.iniciado_em = datetime.utcnow()
    o.updated_at = o.iniciado_em
    br = await db.execute(select(BoxLavagemModel).where(BoxLavagemModel.id == o.box_id))
    box = br.scalar_one_or_none()
    if box:
        box.estado = "ocupado"
    await db.commit()
    return await _to_response(db, o)


class ColaboradorResponsavelDTO(BaseModel):
    colaborador_responsavel_id: UUID


@router.patch("/ordens/{id}/colaborador-responsavel", response_model=OrdemResponseDTO)
async def definir_colaborador_responsavel(
    id: UUID,
    body: ColaboradorResponsavelDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    """Regista/corrige qual colaborador da equipa foi o responsável directo
    pela lavagem — opcional, para produtividade individual (Fase 4).
    Aceite em qualquer estado a partir de 'em_curso', para permitir
    correcção mesmo depois de concluída."""
    o = await _load_ordem(db, id, current_user)
    if o.estado in ("rascunho", "agendada", "confirmada", "checkin"):
        raise HTTPException(400, "Só é possível atribuir responsável a partir do início da lavagem")
    if o.equipa:
        equipa_ids = {UUID(uid) for uid in o.equipa.split(",") if uid}
        if body.colaborador_responsavel_id not in equipa_ids:
            raise HTTPException(400, "Colaborador indicado não pertence à equipa desta ordem")
    o.colaborador_responsavel_id = body.colaborador_responsavel_id
    await db.commit()
    return await _to_response(db, o)


@router.post("/ordens/{id}/registar-consumo", response_model=OrdemResponseDTO)
async def registar_consumo(
    id: UUID,
    body: ConsumoDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    o = await _load_ordem(db, id, current_user)
    if o.estado != "em_curso":
        raise HTTPException(400, "Só é possível registar consumo em ordens em curso")

    if body.agua_consumida_litros is not None:
        agua_litros = body.agua_consumida_litros
    else:
        agua_litros = await _calcular_agua_estimada(db, o)
    o.agua_consumida_litros = agua_litros

    if agua_litros:
        tr = await db.execute(
            select(TanqueAguaModel)
            .where(TanqueAguaModel.company_id == current_user.company_id)
            .where(TanqueAguaModel.deleted_at.is_(None))
            .order_by(TanqueAguaModel.nivel_atual_litros.desc())
        )
        tanque = tr.scalars().first()
        if tanque:
            tanque.nivel_atual_litros = max(Decimal("0"), Decimal(tanque.nivel_atual_litros) - Decimal(agua_litros))
            db.add(ConsumoAguaModel(
                id=uuid4(), company_id=current_user.company_id, tanque_agua_id=tanque.id,
                litros_consumidos=Decimal(agua_litros), tipo="lavagem",
                referencia_id=o.id, referencia_tipo="ordem_lavagem",
            ))

    if body.quimicos and body.armazem_id:
        for item in body.quimicos:
            await stock_service.registar_movimento(
                db, company_id=current_user.company_id,
                produto_id=UUID(item["produto_id"]), tipo="saida_perda",
                quantidade=Decimal(str(item["quantidade"])), armazem_origem_id=body.armazem_id,
                motivo=f"Consumo de químicos na lavagem {o.id}", created_by=current_user.id,
                documento_ref_tipo="ordem_lavagem", documento_ref_id=str(o.id),
            )
        o.quimicos_consumidos = json.dumps(body.quimicos)

    await db.commit()
    return await _to_response(db, o)


@router.post("/ordens/{id}/controlo-qualidade", response_model=OrdemResponseDTO)
async def controlo_qualidade(
    id: UUID,
    req: Request,
    body: QualidadeDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.avaliar_qualidade")),
):
    o = await _load_ordem(db, id, current_user)
    if o.estado != "em_curso":
        raise HTTPException(400, "Controlo de qualidade só é possível em ordens em curso")

    cq = ControloQualidadeLavagemModel(
        id=uuid4(), ordem_lavagem_id=o.id, avaliador_id=current_user.id,
        pontuacao=body.pontuacao, observacoes=body.observacoes,
    )
    db.add(cq)
    o.estado = "controlo_qualidade"
    o.controlo_qualidade_em = datetime.utcnow()
    o.updated_at = o.controlo_qualidade_em

    if body.pontuacao < 3:
        await write_audit(
            db, current_user.id, current_user.company_id,
            "qualidade_baixa", "ordem_lavagem", o.id,
            dados_novos={"pontuacao": body.pontuacao},
            ip_address=req.client.host if req.client else None,
        )
    await db.commit()
    return await _to_response(db, o)


@router.post("/ordens/{id}/oferecer-re-lavagem", response_model=OrdemResponseDTO, status_code=201)
async def oferecer_re_lavagem(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.avaliar_qualidade")),
):
    original = await _load_ordem(db, id, current_user)
    nova = OrdemLavagemModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=original.cliente_id, viatura_id=original.viatura_id,
        tipo_lavagem_id=original.tipo_lavagem_id, estado="rascunho",
        origem=original.origem, re_lavagem_de_id=original.id,
    )
    db.add(nova)
    await db.commit()
    return await _to_response(db, nova)


@router.post("/ordens/{id}/concluir", response_model=OrdemResponseDTO)
async def concluir(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    o = await _load_ordem(db, id, current_user)
    if o.estado != "controlo_qualidade":
        raise HTTPException(400, "Ordem precisa de controlo de qualidade antes de concluir")
    preco_total, _ = await _calcular_preco_atual(db, o)
    o.preco_total_snapshot = preco_total
    o.estado = "concluida"
    o.concluido_em = datetime.utcnow()
    o.updated_at = o.concluido_em
    if o.box_id:
        br = await db.execute(select(BoxLavagemModel).where(BoxLavagemModel.id == o.box_id))
        box = br.scalar_one_or_none()
        if box:
            box.estado = "disponivel"
    await db.commit()
    return await _to_response(db, o)


@router.get("/ordens/{id}/fotos")
async def get_fotos(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    """Fotos antes/depois via AnexoModel genérico (entity_type=ordem_lavagem),
    reaproveitando o mesmo modelo/versionamento criado para Gestão da Água
    (PROMPT_GESTAO_AGUA_SPRINTS.md, Fase 4) em vez de uma tabela dedicada."""
    await _load_ordem(db, id, current_user)
    base_url = str(req.base_url).rstrip("/")
    fotos_antes = await listar_anexos_por_tipo(
        db, company_id=current_user.company_id, entity_type="ordem_lavagem",
        entity_id=id, tipo_documento="foto_antes", base_url=base_url,
    )
    fotos_depois = await listar_anexos_por_tipo(
        db, company_id=current_user.company_id, entity_type="ordem_lavagem",
        entity_id=id, tipo_documento="foto_depois", base_url=base_url,
    )
    return {"fotos_antes": fotos_antes, "fotos_depois": fotos_depois}


@router.post("/ordens/{id}/fotos", status_code=201)
async def upload_foto(
    id: UUID,
    req: Request,
    momento: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    if momento not in ("antes", "depois"):
        raise HTTPException(400, "momento deve ser 'antes' ou 'depois'")
    await _load_ordem(db, id, current_user)
    if file.content_type not in ("image/png", "image/jpeg", "image/jpg"):
        raise HTTPException(400, f"Tipo de ficheiro não suportado: {file.content_type}")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "Ficheiro maior que 10 MB")

    tipo_documento = f"foto_{momento}"
    versao_r = await db.execute(
        select(AnexoModel.versao)
        .where(AnexoModel.company_id == current_user.company_id)
        .where(AnexoModel.entity_type == "ordem_lavagem")
        .where(AnexoModel.entity_id == id)
        .where(AnexoModel.tipo_documento == tipo_documento)
        .order_by(AnexoModel.versao.desc())
        .limit(1)
    )
    versao = (versao_r.scalar() or 0) + 1
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    file_key = f"anexos/ordem_lavagem/{id}/{tipo_documento}_v{versao}_{uuid4().hex[:8]}.{ext}"

    storage = get_storage_provider()
    import io as _io
    await storage.upload(file_key, _io.BytesIO(content), content_type=file.content_type or "image/jpeg")

    a = AnexoModel(
        id=uuid4(), company_id=current_user.company_id,
        entity_type="ordem_lavagem", entity_id=id,
        tipo_documento=tipo_documento, versao=versao,
        file_path=file_key, file_name=file.filename or file_key,
        mime_type=file.content_type, size_bytes=len(content),
        uploaded_by=current_user.id,
    )
    db.add(a)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "anexo_upload", "ordem_lavagem", id,
        dados_novos={"tipo_documento": tipo_documento, "versao": versao},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"id": str(a.id), "tipo_documento": tipo_documento, "versao": versao}


# ─── Walk-in e Fila de Prioridade (D1, D2) ───────────────────────────


class WalkinCreateDTO(BaseModel):
    """Criação rápida de ordem para cliente sem reserva/telefone/portal.
    cliente_id é opcional — aceita nome/matrícula livres quando o cliente
    ainda não existe no CRM (D1: mesma entidade OrdemLavagem, só muda
    a origem)."""
    nome_cliente: Optional[str] = None
    telefone_cliente: Optional[str] = None
    matricula: str = Field(..., min_length=1, max_length=20)
    marca: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None
    categoria_veiculo_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None
    tipo_lavagem_id: UUID
    extra_ids: List[UUID] = Field(default_factory=list)


@router.post("/ordens/walkin", response_model=OrdemResponseDTO, status_code=201)
async def criar_walkin(
    req: Request,
    body: WalkinCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.agendar")),
):
    """Cria uma OrdemLavagem para atendimento imediato (sem reserva prévia),
    origem=backoffice_walkin. Regista/reaproveita a viatura pela matrícula
    para não duplicar registos do mesmo veículo em walk-ins repetidos."""
    vr = await db.execute(
        select(ViaturaModel)
        .where(ViaturaModel.company_id == current_user.company_id)
        .where(ViaturaModel.matricula == body.matricula)
        .where(ViaturaModel.deleted_at.is_(None))
    )
    viatura = vr.scalar_one_or_none()
    if not viatura:
        viatura = ViaturaModel(
            id=uuid4(), company_id=current_user.company_id,
            cliente_id=str(body.cliente_id) if body.cliente_id else None,
            matricula=body.matricula, marca=body.marca, modelo=body.modelo,
            cor=body.cor, categoria_veiculo_id=body.categoria_veiculo_id,
        )
        db.add(viatura)
        await db.flush()
    elif body.categoria_veiculo_id and not viatura.categoria_veiculo_id:
        viatura.categoria_veiculo_id = body.categoria_veiculo_id

    _, extras_aplicados = await _calcular_preco_ordem(
        db, tipo_lavagem_id=body.tipo_lavagem_id, categoria_veiculo_id=viatura.categoria_veiculo_id,
        extra_ids=body.extra_ids,
    )

    m = OrdemLavagemModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        viatura_id=str(viatura.id), tipo_lavagem_id=body.tipo_lavagem_id,
        estado="agendada", origem="backoffice_walkin",
    )
    db.add(m)
    await db.flush()

    for extra_id, preco_aplicado in extras_aplicados:
        db.add(OrdemLavagemExtraModel(
            id=uuid4(), ordem_lavagem_id=m.id, extra_id=extra_id, preco_aplicado=preco_aplicado,
        ))

    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada_walkin", "ordem_lavagem", m.id,
        dados_novos={"matricula": body.matricula, "nome_cliente": body.nome_cliente},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, m)


class FilaItemDTO(BaseModel):
    ordem_id: UUID
    origem: str
    prioridade: int  # 1 = reserva na janela imediata, 2 = próxima reserva agendada, 3 = walk-in
    matricula: Optional[str] = None
    tipo_lavagem_nome: str
    slot_hora: Optional[datetime] = None
    espera_desde: datetime


@router.get("/fila-atendimento", response_model=List[FilaItemDTO])
async def fila_atendimento(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    """Fila ordenada por prioridade (D2):
      1. Reserva com slot dentro dos próximos 15 min (ou já na janela ±15min)
      2. Próxima reserva agendada no tempo (qualquer box)
      3. Walk-in mais antigo (por created_at), sem reserva/slot

    Nunca um walk-in ultrapassa uma reserva confirmada dentro da janela.
    """
    r = await db.execute(
        select(OrdemLavagemModel, TipoLavagemModel, SlotLavagemModel)
        .join(TipoLavagemModel, TipoLavagemModel.id == OrdemLavagemModel.tipo_lavagem_id)
        .outerjoin(SlotLavagemModel, SlotLavagemModel.id == OrdemLavagemModel.slot_id)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["agendada", "confirmada"]))
    )
    rows = r.all()

    agora = datetime.utcnow()
    janela = timedelta(minutes=15)
    itens: List[FilaItemDTO] = []

    for ordem, tipo, slot in rows:
        matricula = None
        if ordem.viatura_id:
            vr = await db.execute(select(ViaturaModel.matricula).where(ViaturaModel.id == UUID(ordem.viatura_id)))
            row = vr.first()
            matricula = row[0] if row else None

        if slot is not None:
            prioridade = 1 if (slot.data_hora_inicio - janela <= agora <= slot.data_hora_inicio + janela) else 2
            slot_hora = slot.data_hora_inicio
        else:
            prioridade = 3
            slot_hora = None

        itens.append(FilaItemDTO(
            ordem_id=ordem.id, origem=ordem.origem, prioridade=prioridade,
            matricula=matricula, tipo_lavagem_nome=tipo.nome,
            slot_hora=slot_hora, espera_desde=ordem.created_at,
        ))

    # Ordenação: prioridade asc; dentro de prioridade 1/2 por slot_hora asc;
    # dentro de prioridade 3 (walk-in) por espera_desde asc (mais antigo primeiro).
    itens.sort(key=lambda i: (
        i.prioridade,
        i.slot_hora or datetime.max,
        i.espera_desde,
    ))
    return itens


# ─── Lembretes de reserva (Sprint 6) ─────────────────────────────────


@router.post("/lembretes/processar")
async def processar_lembretes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.agendar")),
):
    """Envia email de lembrete a clientes do portal com reserva nos
    próximos 30 minutos ainda não notificados. Sem scheduler in-process
    no backend — pensado para ser chamado por um cron externo (Task
    Scheduler / cron-job.org) a cada poucos minutos."""
    from app.infrastructure.database.models import ContaClienteModel
    from app.infrastructure.email import send_email

    agora = datetime.utcnow()
    janela_fim = agora + timedelta(minutes=30)

    r = await db.execute(
        select(OrdemLavagemModel, SlotLavagemModel, TipoLavagemModel)
        .join(SlotLavagemModel, SlotLavagemModel.id == OrdemLavagemModel.slot_id)
        .join(TipoLavagemModel, TipoLavagemModel.id == OrdemLavagemModel.tipo_lavagem_id)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.origem == "portal_cliente")
        .where(OrdemLavagemModel.estado.in_(["agendada", "confirmada"]))
        .where(OrdemLavagemModel.lembrete_enviado.is_(False))
        .where(SlotLavagemModel.data_hora_inicio >= agora)
        .where(SlotLavagemModel.data_hora_inicio <= janela_fim)
    )
    rows = r.all()

    enviados = 0
    for ordem, slot, tipo in rows:
        if not ordem.cliente_id:
            continue
        cr = await db.execute(
            select(ContaClienteModel).where(ContaClienteModel.cliente_id == ordem.cliente_id)
        )
        conta = cr.scalar_one_or_none()
        if not conta:
            continue
        try:
            await send_email(
                to=conta.email,
                subject="Lembrete — a sua lavagem é dentro de 30 minutos",
                html=(
                    f"<p>A sua reserva de <b>{tipo.nome}</b> está agendada para "
                    f"{slot.data_hora_inicio.strftime('%d/%m/%Y %H:%M')} — dentro de 30 minutos.</p>"
                ),
            )
            ordem.lembrete_enviado = True
            enviados += 1
        except Exception:
            continue  # falha de envio não deve travar o processamento dos restantes

    await db.commit()
    return {"lembretes_enviados": enviados}


__all__ = ["router"]
