"""Reservas de Lavagem — Portal do Cliente (FrontOffice).

Cliente vê disponibilidade real (SlotLavagemModel) e cria a sua própria
OrdemLavagem com origem=portal_cliente. Reaproveita o mesmo modelo de
dados e cálculo de preço já usados no backoffice (ver
operacoes_lavagem.py) — não duplica lógica de negócio.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.auth.dependencies import get_current_cliente
from app.presentation.api.v1.anexos import listar_anexos_por_tipo
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    BoxLavagemModel,
    ContaClienteModel,
    ControloQualidadeLavagemModel,
    ExtraLavagemModel,
    OrdemLavagemExtraModel,
    OrdemLavagemModel,
    SlotLavagemModel,
    TipoLavagemModel,
    ViaturaModel,
)
from app.presentation.api.v1.operacoes_lavagem import _calcular_preco_ordem


router = APIRouter()


# ─── Disponibilidade ─────────────────────────────────────────────────


class SlotDisponivelDTO(BaseModel):
    id: UUID
    box_id: UUID
    box_codigo: str
    data_hora_inicio: datetime
    data_hora_fim: datetime
    preco_estimado: Decimal


@router.get("/disponibilidade", response_model=List[SlotDisponivelDTO])
async def disponibilidade(
    data: date,
    tipo_lavagem_id: UUID,
    categoria_veiculo_id: Optional[UUID] = None,
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    inicio_dia = datetime.combine(data, time.min)
    fim_dia = datetime.combine(data, time.max)

    r = await db.execute(
        select(SlotLavagemModel, BoxLavagemModel)
        .join(BoxLavagemModel, BoxLavagemModel.id == SlotLavagemModel.box_id)
        .where(SlotLavagemModel.estado == "disponivel")
        .where(SlotLavagemModel.data_hora_inicio >= inicio_dia)
        .where(SlotLavagemModel.data_hora_inicio <= fim_dia)
        .where(BoxLavagemModel.company_id == conta.company_id)
        .where(BoxLavagemModel.deleted_at.is_(None))
        .order_by(SlotLavagemModel.data_hora_inicio)
    )
    preco_total, _ = await _calcular_preco_ordem(
        db, tipo_lavagem_id=tipo_lavagem_id, categoria_veiculo_id=categoria_veiculo_id, extra_ids=[],
    )

    return [
        SlotDisponivelDTO(
            id=slot.id, box_id=box.id, box_codigo=box.codigo,
            data_hora_inicio=slot.data_hora_inicio, data_hora_fim=slot.data_hora_fim,
            preco_estimado=slot.preco_override if slot.preco_override is not None else preco_total,
        )
        for slot, box in r.all()
    ]


# ─── Viaturas do cliente ─────────────────────────────────────────────


class ViaturaCreateDTO(BaseModel):
    matricula: str = Field(..., min_length=1, max_length=20)
    marca: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None
    categoria_veiculo_id: Optional[UUID] = None


class ViaturaResponseDTO(BaseModel):
    id: UUID
    matricula: str
    marca: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None
    categoria_veiculo_id: Optional[UUID] = None

    class Config:
        from_attributes = True


@router.get("/viaturas", response_model=List[ViaturaResponseDTO])
async def minhas_viaturas(
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(ViaturaModel)
        .where(ViaturaModel.cliente_id == conta.cliente_id)
        .where(ViaturaModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/viaturas", response_model=ViaturaResponseDTO, status_code=201)
async def registar_viatura(
    body: ViaturaCreateDTO,
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    m = ViaturaModel(
        id=uuid4(), company_id=conta.company_id, cliente_id=conta.cliente_id,
        matricula=body.matricula, marca=body.marca, modelo=body.modelo,
        cor=body.cor, categoria_veiculo_id=body.categoria_veiculo_id,
    )
    db.add(m)
    await db.commit()
    return m


# ─── Reservas ────────────────────────────────────────────────────────


class ReservaCreateDTO(BaseModel):
    viatura_id: UUID
    tipo_lavagem_id: UUID
    slot_id: UUID
    extra_ids: List[UUID] = Field(default_factory=list)


class ExtraAplicadoDTO(BaseModel):
    extra_id: UUID
    preco_aplicado: Decimal

    class Config:
        from_attributes = True


class ReservaResponseDTO(BaseModel):
    id: UUID
    viatura_id: Optional[str] = None
    tipo_lavagem_id: UUID
    box_id: Optional[UUID] = None
    slot_id: Optional[UUID] = None
    estado: str
    preco_total: Optional[Decimal] = None
    extras: List[ExtraAplicadoDTO] = []
    created_at: datetime

    class Config:
        from_attributes = True


async def _to_reserva_response(db: AsyncSession, o: OrdemLavagemModel) -> ReservaResponseDTO:
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
    dto = ReservaResponseDTO.model_validate(o)
    dto.preco_total = preco_total
    dto.extras = [ExtraAplicadoDTO.model_validate(e) for e in extras]
    return dto


@router.get("/reservas/minhas", response_model=List[ReservaResponseDTO])
async def minhas_reservas(
    estado: Optional[str] = None,
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    """Sem `estado`, devolve todas as ordens do cliente (comportamento
    original preservado). Com `estado` (CSV, ex.: "concluida,paga,cancelada"),
    filtra por esses estados — usado pelo Histórico (Sprint 7) para separar
    activas de passadas."""
    stmt = (
        select(OrdemLavagemModel)
        .where(OrdemLavagemModel.cliente_id == conta.cliente_id)
        .where(OrdemLavagemModel.origem == "portal_cliente")
    )
    if estado:
        estados = [e.strip() for e in estado.split(",") if e.strip()]
        if estados:
            stmt = stmt.where(OrdemLavagemModel.estado.in_(estados))
    stmt = stmt.order_by(OrdemLavagemModel.created_at.desc())
    r = await db.execute(stmt)
    return [await _to_reserva_response(db, o) for o in r.scalars().all()]


@router.get("/reservas/{id}", response_model=ReservaResponseDTO)
async def get_reserva(
    id: UUID,
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(OrdemLavagemModel).where(OrdemLavagemModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.cliente_id != conta.cliente_id:
        raise HTTPException(404, "Reserva não encontrada")
    return await _to_reserva_response(db, o)


@router.post("/reservas", response_model=ReservaResponseDTO, status_code=201)
async def criar_reserva(
    body: ReservaCreateDTO,
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    vr = await db.execute(select(ViaturaModel).where(ViaturaModel.id == body.viatura_id))
    viatura = vr.scalar_one_or_none()
    if not viatura or viatura.cliente_id != conta.cliente_id:
        raise HTTPException(404, "Viatura não encontrada")

    sr = await db.execute(select(SlotLavagemModel).where(SlotLavagemModel.id == body.slot_id))
    slot = sr.scalar_one_or_none()
    if not slot:
        raise HTTPException(404, "Slot não encontrado")
    if slot.estado != "disponivel":
        raise HTTPException(409, "Este horário já não está disponível — escolha outro")

    tr = await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == body.tipo_lavagem_id))
    if not tr.scalar_one_or_none():
        raise HTTPException(404, "Tipo de lavagem não encontrado")

    _, extras_aplicados = await _calcular_preco_ordem(
        db, tipo_lavagem_id=body.tipo_lavagem_id, categoria_veiculo_id=viatura.categoria_veiculo_id,
        extra_ids=body.extra_ids,
    )

    slot.estado = "reservado"

    m = OrdemLavagemModel(
        id=uuid4(), company_id=conta.company_id, cliente_id=conta.cliente_id,
        viatura_id=str(viatura.id), tipo_lavagem_id=body.tipo_lavagem_id,
        box_id=slot.box_id, slot_id=slot.id, estado="agendada", origem="portal_cliente",
    )
    db.add(m)
    await db.flush()

    for extra_id, preco_aplicado in extras_aplicados:
        db.add(OrdemLavagemExtraModel(
            id=uuid4(), ordem_lavagem_id=m.id, extra_id=extra_id, preco_aplicado=preco_aplicado,
        ))

    await db.commit()

    try:
        from app.infrastructure.email import send_email
        tipo = (await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == body.tipo_lavagem_id))).scalar_one()
        await send_email(
            to=conta.email,
            subject="Confirmação de reserva — Lavagem",
            html=(
                f"<p>A sua reserva foi confirmada.</p>"
                f"<p><b>Serviço:</b> {tipo.nome}<br>"
                f"<b>Data/hora:</b> {slot.data_hora_inicio.strftime('%d/%m/%Y %H:%M')}<br>"
                f"<b>Matrícula:</b> {viatura.matricula}</p>"
            ),
        )
    except Exception:
        pass  # falha de envio de email não deve reverter a reserva já confirmada

    return await _to_reserva_response(db, m)


@router.post("/reservas/{id}/cancelar", response_model=ReservaResponseDTO)
async def cancelar_reserva(
    id: UUID,
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(OrdemLavagemModel).where(OrdemLavagemModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.cliente_id != conta.cliente_id:
        raise HTTPException(404, "Reserva não encontrada")
    if o.estado not in ("rascunho", "agendada", "confirmada"):
        raise HTTPException(400, "Só é possível cancelar antes do check-in")

    if o.slot_id:
        sr = await db.execute(select(SlotLavagemModel).where(SlotLavagemModel.id == o.slot_id))
        slot = sr.scalar_one_or_none()
        if slot:
            slot.estado = "disponivel"

    o.estado = "cancelada"
    o.updated_at = datetime.utcnow()
    await db.commit()
    return await _to_reserva_response(db, o)


# ─── Histórico (Sprint 7) ──────────────────────────────────────────────


class ControloQualidadeDTO(BaseModel):
    pontuacao: int
    observacoes: Optional[str] = None
    data: datetime

    class Config:
        from_attributes = True


class ReservaDetalheDTO(ReservaResponseDTO):
    tipo_lavagem_nome: str
    viatura_matricula: Optional[str] = None
    viatura_marca: Optional[str] = None
    viatura_modelo: Optional[str] = None
    controlo_qualidade: Optional[ControloQualidadeDTO] = None
    fotos_antes: List[str] = []
    fotos_depois: List[str] = []
    re_lavagem_de_id: Optional[UUID] = None


@router.get("/reservas/{id}/detalhe", response_model=ReservaDetalheDTO)
async def detalhe_reserva(
    id: UUID,
    req: Request,
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(OrdemLavagemModel).where(OrdemLavagemModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.cliente_id != conta.cliente_id:
        raise HTTPException(404, "Reserva não encontrada")

    base = await _to_reserva_response(db, o)

    tr = await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == o.tipo_lavagem_id))
    tipo = tr.scalar_one_or_none()

    viatura = None
    if o.viatura_id:
        vr = await db.execute(select(ViaturaModel).where(ViaturaModel.id == UUID(o.viatura_id)))
        viatura = vr.scalar_one_or_none()

    cqr = await db.execute(
        select(ControloQualidadeLavagemModel)
        .where(ControloQualidadeLavagemModel.ordem_lavagem_id == o.id)
        .order_by(ControloQualidadeLavagemModel.data.desc())
    )
    cq = cqr.scalars().first()

    base_url = str(req.base_url).rstrip("/")
    fotos_antes = await listar_anexos_por_tipo(
        db, company_id=o.company_id, entity_type="ordem_lavagem",
        entity_id=o.id, tipo_documento="foto_antes", base_url=base_url,
    )
    fotos_depois = await listar_anexos_por_tipo(
        db, company_id=o.company_id, entity_type="ordem_lavagem",
        entity_id=o.id, tipo_documento="foto_depois", base_url=base_url,
    )

    return ReservaDetalheDTO(
        **base.model_dump(),
        tipo_lavagem_nome=tipo.nome if tipo else "",
        viatura_matricula=viatura.matricula if viatura else None,
        viatura_marca=viatura.marca if viatura else None,
        viatura_modelo=viatura.modelo if viatura else None,
        controlo_qualidade=ControloQualidadeDTO.model_validate(cq) if cq else None,
        fotos_antes=fotos_antes, fotos_depois=fotos_depois,
        re_lavagem_de_id=o.re_lavagem_de_id,
    )


class ResumoClienteDTO(BaseModel):
    total_lavagens: int
    valor_total_gasto: Decimal
    tipo_lavagem_mais_frequente: Optional[str] = None


@router.get("/reservas/minhas/resumo", response_model=ResumoClienteDTO)
async def resumo_cliente(
    conta: ContaClienteModel = Depends(get_current_cliente),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(OrdemLavagemModel)
        .where(OrdemLavagemModel.cliente_id == conta.cliente_id)
        .where(OrdemLavagemModel.origem == "portal_cliente")
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
    )
    ordens = list(r.scalars().all())

    if not ordens:
        return ResumoClienteDTO(total_lavagens=0, valor_total_gasto=Decimal("0"))

    valor_total = Decimal("0")
    contagem_tipos: dict[UUID, int] = {}
    for o in ordens:
        resp = await _to_reserva_response(db, o)
        valor_total += resp.preco_total or Decimal("0")
        contagem_tipos[o.tipo_lavagem_id] = contagem_tipos.get(o.tipo_lavagem_id, 0) + 1

    tipo_mais_frequente_id = max(contagem_tipos, key=contagem_tipos.get)
    tr = await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == tipo_mais_frequente_id))
    tipo = tr.scalar_one_or_none()

    return ResumoClienteDTO(
        total_lavagens=len(ordens),
        valor_total_gasto=valor_total,
        tipo_lavagem_mais_frequente=tipo.nome if tipo else None,
    )


__all__ = ["router"]
