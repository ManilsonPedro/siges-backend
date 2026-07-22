"""Atendimento (domínio Gestão Comercial): Reclamações, Sugestões, Tickets, Registos."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    AtendimentoRegistroModel,
    ReclamacaoModel,
    SugestaoModel,
    TicketModel,
)


router = APIRouter()


# ─── Reclamações ─────────────────────────────────────────────────────


class ReclamacaoCreateDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    assunto: str = Field(..., min_length=1, max_length=150)
    descricao: str = Field(..., min_length=1)
    canal: str = Field(..., pattern="^(telefone|email|whatsapp|presencial|app)$")
    gravidade: str = Field(default="media", pattern="^(baixa|media|alta)$")


class ReclamacaoUpdateDTO(BaseModel):
    estado: Optional[str] = Field(None, pattern="^(aberta|em_analise|resolvida|fechada)$")


class ReclamacaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    assunto: str
    descricao: str
    canal: str
    gravidade: str
    estado: str
    responsavel_id: Optional[UUID] = None
    data_abertura: datetime
    data_resolucao: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("/reclamacoes", response_model=List[ReclamacaoResponseDTO])
async def list_reclamacoes(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.view")),
):
    stmt = select(ReclamacaoModel).where(ReclamacaoModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(ReclamacaoModel.estado == estado)
    stmt = stmt.order_by(ReclamacaoModel.data_abertura.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/reclamacoes", response_model=ReclamacaoResponseDTO, status_code=201)
async def create_reclamacao(
    body: ReclamacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.gerir_reclamacoes")),
):
    m = ReclamacaoModel(
        id=uuid4(), company_id=current_user.company_id, responsavel_id=current_user.id,
        estado="aberta", cliente_id=str(body.cliente_id) if body.cliente_id else None,
        **body.model_dump(exclude={"cliente_id"}),
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/reclamacoes/{id}", response_model=ReclamacaoResponseDTO)
async def update_reclamacao(
    id: UUID,
    body: ReclamacaoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.gerir_reclamacoes")),
):
    r = await db.execute(select(ReclamacaoModel).where(ReclamacaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Reclamação não encontrada")
    if body.estado:
        m.estado = body.estado
        if body.estado == "resolvida":
            m.data_resolucao = datetime.utcnow()
    await db.commit()
    return m


@router.post("/reclamacoes/{id}/resolver", response_model=ReclamacaoResponseDTO)
async def resolver_reclamacao(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.gerir_reclamacoes")),
):
    r = await db.execute(select(ReclamacaoModel).where(ReclamacaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Reclamação não encontrada")
    m.estado = "resolvida"
    m.data_resolucao = datetime.utcnow()
    await db.commit()
    return m


# ─── Sugestões ───────────────────────────────────────────────────────


class SugestaoCreateDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    descricao: str = Field(..., min_length=1)


class SugestaoUpdateDTO(BaseModel):
    estado: str = Field(..., pattern="^(recebida|em_avaliacao|aceite|rejeitada|implementada)$")


class SugestaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    descricao: str
    estado: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/sugestoes", response_model=List[SugestaoResponseDTO])
async def list_sugestoes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.view")),
):
    r = await db.execute(select(SugestaoModel).where(SugestaoModel.company_id == current_user.company_id))
    return list(r.scalars().all())


@router.post("/sugestoes", response_model=SugestaoResponseDTO, status_code=201)
async def create_sugestao(
    body: SugestaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.view")),
):
    m = SugestaoModel(
        id=uuid4(), company_id=current_user.company_id, estado="recebida",
        cliente_id=str(body.cliente_id) if body.cliente_id else None, descricao=body.descricao,
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/sugestoes/{id}", response_model=SugestaoResponseDTO)
async def update_sugestao(
    id: UUID,
    body: SugestaoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.gerir_reclamacoes")),
):
    r = await db.execute(select(SugestaoModel).where(SugestaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Sugestão não encontrada")
    m.estado = body.estado
    await db.commit()
    return m


# ─── Tickets ─────────────────────────────────────────────────────────


class TicketCreateDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    assunto: str = Field(..., min_length=1, max_length=150)
    descricao: str = Field(..., min_length=1)
    prioridade: str = Field(default="media", pattern="^(baixa|media|alta|urgente)$")


class TicketUpdateDTO(BaseModel):
    estado: Optional[str] = Field(None, pattern="^(aberto|em_curso|resolvido|fechado)$")


class TicketResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    assunto: str
    descricao: str
    prioridade: str
    estado: str
    responsavel_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/tickets", response_model=List[TicketResponseDTO])
async def list_tickets(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.view")),
):
    stmt = select(TicketModel).where(TicketModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(TicketModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/tickets", response_model=TicketResponseDTO, status_code=201)
async def create_ticket(
    body: TicketCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.gerir_tickets")),
):
    m = TicketModel(
        id=uuid4(), company_id=current_user.company_id, responsavel_id=current_user.id,
        estado="aberto", cliente_id=str(body.cliente_id) if body.cliente_id else None,
        **body.model_dump(exclude={"cliente_id"}),
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/tickets/{id}", response_model=TicketResponseDTO)
async def update_ticket(
    id: UUID,
    body: TicketUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.gerir_tickets")),
):
    r = await db.execute(select(TicketModel).where(TicketModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Ticket não encontrado")
    if body.estado:
        m.estado = body.estado
    await db.commit()
    return m


@router.post("/tickets/{id}/resolver", response_model=TicketResponseDTO)
async def resolver_ticket(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.gerir_tickets")),
):
    r = await db.execute(select(TicketModel).where(TicketModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Ticket não encontrado")
    m.estado = "resolvido"
    await db.commit()
    return m


# ─── Registos de Atendimento ─────────────────────────────────────────


class RegistroCreateDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    canal: str = Field(..., pattern="^(telefone|email|whatsapp|presencial|app)$")
    assunto: Optional[str] = None
    descricao: Optional[str] = None


class RegistroResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    canal: str
    assunto: Optional[str] = None
    descricao: Optional[str] = None
    responsavel_id: Optional[UUID] = None
    data_hora: datetime
    satisfacao: Optional[int] = None

    class Config:
        from_attributes = True


@router.get("/registros", response_model=List[RegistroResponseDTO])
async def list_registros(
    cliente_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.view")),
):
    stmt = select(AtendimentoRegistroModel).where(AtendimentoRegistroModel.company_id == current_user.company_id)
    if cliente_id:
        stmt = stmt.where(AtendimentoRegistroModel.cliente_id == str(cliente_id))
    stmt = stmt.order_by(AtendimentoRegistroModel.data_hora.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/registros", response_model=RegistroResponseDTO, status_code=201)
async def create_registro(
    body: RegistroCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.view")),
):
    m = AtendimentoRegistroModel(
        id=uuid4(), company_id=current_user.company_id, responsavel_id=current_user.id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        canal=body.canal, assunto=body.assunto, descricao=body.descricao,
    )
    db.add(m)
    await db.commit()
    return m


@router.post("/registros/{id}/avaliar", response_model=RegistroResponseDTO)
async def avaliar_registro(
    id: UUID,
    satisfacao: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("atendimento.view")),
):
    if satisfacao < 1 or satisfacao > 5:
        raise HTTPException(400, "Satisfação deve ser entre 1 e 5")
    r = await db.execute(select(AtendimentoRegistroModel).where(AtendimentoRegistroModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Registo não encontrado")
    m.satisfacao = satisfacao
    await db.commit()
    return m


__all__ = ["router"]
