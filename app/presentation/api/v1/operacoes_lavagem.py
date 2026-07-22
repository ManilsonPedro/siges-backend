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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.domain.services import stock_service
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    BoxLavagemModel,
    ControloQualidadeLavagemModel,
    OrdemLavagemModel,
    SlotLavagemModel,
    TipoLavagemModel,
)


router = APIRouter()


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
    codigo: str = Field(..., min_length=1, max_length=20)
    nome: str = Field(..., min_length=1, max_length=120)
    capacidade: int = Field(default=1, gt=0)


class BoxResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
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


class ConsumoDTO(BaseModel):
    agua_consumida_litros: Optional[Decimal] = None
    quimicos: List[dict] = Field(default_factory=list)  # [{"produto_id": "...", "quantidade": 1.5}]
    armazem_id: Optional[UUID] = None


class QualidadeDTO(BaseModel):
    pontuacao: int = Field(..., ge=1, le=5)
    observacoes: Optional[str] = None


class OrdemResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    viatura_id: Optional[str] = None
    tipo_lavagem_id: UUID
    box_id: Optional[UUID] = None
    slot_id: Optional[UUID] = None
    estado: str
    agua_consumida_litros: Optional[Decimal] = None
    re_lavagem_de_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


async def _load_ordem(db: AsyncSession, id: UUID, current_user: User) -> OrdemLavagemModel:
    r = await db.execute(select(OrdemLavagemModel).where(OrdemLavagemModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.company_id != current_user.company_id:
        raise HTTPException(404, "Ordem de lavagem não encontrada")
    return o


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
    return list(r.scalars().all())


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

    m = OrdemLavagemModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        viatura_id=str(body.viatura_id) if body.viatura_id else None,
        tipo_lavagem_id=body.tipo_lavagem_id, box_id=body.box_id, slot_id=body.slot_id,
        estado=estado_inicial,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "ordem_lavagem", m.id, dados_novos={"tipo_lavagem_id": str(body.tipo_lavagem_id)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


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
    o.updated_at = datetime.utcnow()
    await db.commit()
    return o


@router.post("/ordens/{id}/iniciar", response_model=OrdemResponseDTO)
async def iniciar(
    id: UUID,
    box_id: Optional[UUID] = None,
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
    o.estado = "em_curso"
    o.updated_at = datetime.utcnow()
    br = await db.execute(select(BoxLavagemModel).where(BoxLavagemModel.id == o.box_id))
    box = br.scalar_one_or_none()
    if box:
        box.estado = "ocupado"
    await db.commit()
    return o


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
        o.agua_consumida_litros = body.agua_consumida_litros

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
    return o


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
    o.updated_at = datetime.utcnow()

    if body.pontuacao < 3:
        await write_audit(
            db, current_user.id, current_user.company_id,
            "qualidade_baixa", "ordem_lavagem", o.id,
            dados_novos={"pontuacao": body.pontuacao},
            ip_address=req.client.host if req.client else None,
        )
    await db.commit()
    return o


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
        re_lavagem_de_id=original.id,
    )
    db.add(nova)
    await db.commit()
    return nova


@router.post("/ordens/{id}/concluir", response_model=OrdemResponseDTO)
async def concluir(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.operar")),
):
    o = await _load_ordem(db, id, current_user)
    if o.estado != "controlo_qualidade":
        raise HTTPException(400, "Ordem precisa de controlo de qualidade antes de concluir")
    o.estado = "concluida"
    o.updated_at = datetime.utcnow()
    if o.box_id:
        br = await db.execute(select(BoxLavagemModel).where(BoxLavagemModel.id == o.box_id))
        box = br.scalar_one_or_none()
        if box:
            box.estado = "disponivel"
    await db.commit()
    return o


@router.get("/ordens/{id}/fotos")
async def get_fotos(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.lavagem.view")),
):
    """Placeholder de leitura — upload de fotos reutiliza o storage já
    existente (infrastructure/storage/); URLs ficam associadas via
    documento_ref na entidade de anexos já existente no projeto."""
    await _load_ordem(db, id, current_user)
    return {"fotos_antes": [], "fotos_depois": []}


__all__ = ["router"]
