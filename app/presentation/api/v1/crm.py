"""CRM (domínio Gestão Comercial): Leads, Pipeline, Oportunidades, Viaturas,
Fidelização, Visitas, Tarefas."""
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
from app.infrastructure.database.models import (
    ClienteModel,
    EtapaPipelineModel,
    LeadModel,
    OportunidadeModel,
    ProgramaFidelizacaoModel,
    SaldoFidelizacaoModel,
    TarefaModel,
    VisitaModel,
    ViaturaModel,
)


router = APIRouter()


# ─── Leads ───────────────────────────────────────────────────────────


class LeadCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=150)
    empresa: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    origem: str = Field(default="outro", pattern="^(indicacao|site|feira|redes_sociais|outro)$")


class LeadUpdateDTO(BaseModel):
    nome: Optional[str] = None
    empresa: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    estado: Optional[str] = Field(None, pattern="^(novo|qualificado|descartado|convertido)$")
    responsavel_id: Optional[UUID] = None


class LeadResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    empresa: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    origem: str
    estado: str
    responsavel_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/leads", response_model=List[LeadResponseDTO])
async def list_leads(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    stmt = (
        select(LeadModel)
        .where(LeadModel.company_id == current_user.company_id)
        .where(LeadModel.deleted_at.is_(None))
    )
    if estado:
        stmt = stmt.where(LeadModel.estado == estado)
    stmt = stmt.order_by(LeadModel.created_at.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/leads", response_model=LeadResponseDTO, status_code=201)
async def create_lead(
    body: LeadCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.create")),
):
    m = LeadModel(id=uuid4(), company_id=current_user.company_id, estado="novo", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/leads/{id}", response_model=LeadResponseDTO)
async def update_lead(
    id: UUID,
    body: LeadUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    r = await db.execute(select(LeadModel).where(LeadModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Lead não encontrado")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.commit()
    return m


@router.post("/leads/{id}/converter")
async def converter_lead(
    id: UUID,
    req: Request,
    etapa_pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    lr = await db.execute(select(LeadModel).where(LeadModel.id == id))
    lead = lr.scalar_one_or_none()
    if not lead or lead.company_id != current_user.company_id:
        raise HTTPException(404, "Lead não encontrado")
    if lead.estado == "convertido":
        raise HTTPException(400, "Lead já foi convertido")

    cliente = ClienteModel(
        id=uuid4(), company_id=current_user.company_id, nome=lead.nome,
        nif="", telefone=lead.telefone, email=lead.email, estado="ativo",
    )
    db.add(cliente)
    await db.flush()

    oportunidade = OportunidadeModel(
        id=uuid4(), company_id=current_user.company_id, lead_id=lead.id,
        cliente_id=str(cliente.id),
        titulo=f"Oportunidade — {lead.nome}", etapa_pipeline_id=etapa_pipeline_id,
        responsavel_id=lead.responsavel_id, estado="aberta",
    )
    db.add(oportunidade)
    lead.estado = "convertido"
    await write_audit(
        db, current_user.id, current_user.company_id,
        "convertido", "lead", lead.id,
        dados_novos={"oportunidade_id": str(oportunidade.id)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"cliente_id": str(cliente.id), "oportunidade_id": str(oportunidade.id)}


# ─── Pipeline / Oportunidades ────────────────────────────────────────


class EtapaCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    ordem: int = Field(default=0, ge=0)
    cor: Optional[str] = None


class EtapaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    ordem: int
    cor: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/pipeline/etapas", response_model=List[EtapaResponseDTO])
async def list_etapas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    r = await db.execute(
        select(EtapaPipelineModel)
        .where(EtapaPipelineModel.company_id == current_user.company_id)
        .where(EtapaPipelineModel.deleted_at.is_(None))
        .order_by(EtapaPipelineModel.ordem)
    )
    return list(r.scalars().all())


@router.post("/pipeline/etapas", response_model=EtapaResponseDTO, status_code=201)
async def create_etapa(
    body: EtapaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.gerir_pipeline")),
):
    m = EtapaPipelineModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/pipeline/etapas/{id}", status_code=204)
async def delete_etapa(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.gerir_pipeline")),
):
    r = await db.execute(select(EtapaPipelineModel).where(EtapaPipelineModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Etapa não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


class OportunidadeCreateDTO(BaseModel):
    lead_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None
    titulo: str = Field(..., min_length=1, max_length=150)
    valor_estimado: Decimal = Field(default=Decimal("0"), ge=0)
    probabilidade_pct: Decimal = Field(default=Decimal("50"), ge=0, le=100)
    etapa_pipeline_id: UUID
    data_fecho_prevista: Optional[datetime] = None


class OportunidadeUpdateDTO(BaseModel):
    titulo: Optional[str] = None
    valor_estimado: Optional[Decimal] = None
    probabilidade_pct: Optional[Decimal] = None
    data_fecho_prevista: Optional[datetime] = None


class OportunidadeResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    lead_id: Optional[UUID] = None
    cliente_id: Optional[str] = None
    titulo: str
    valor_estimado: Decimal
    probabilidade_pct: Decimal
    etapa_pipeline_id: UUID
    responsavel_id: Optional[UUID] = None
    data_fecho_prevista: Optional[datetime] = None
    estado: str
    motivo_perda: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/oportunidades", response_model=List[OportunidadeResponseDTO])
async def list_oportunidades(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    stmt = select(OportunidadeModel).where(OportunidadeModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(OportunidadeModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/oportunidades", response_model=OportunidadeResponseDTO, status_code=201)
async def create_oportunidade(
    body: OportunidadeCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.create")),
):
    m = OportunidadeModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        responsavel_id=current_user.id, estado="aberta",
        **body.model_dump(exclude={"cliente_id"}),
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/oportunidades/{id}", response_model=OportunidadeResponseDTO)
async def update_oportunidade(
    id: UUID,
    body: OportunidadeUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    r = await db.execute(select(OportunidadeModel).where(OportunidadeModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Oportunidade não encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


@router.post("/oportunidades/{id}/mover-etapa", response_model=OportunidadeResponseDTO)
async def mover_etapa(
    id: UUID,
    etapa_pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.gerir_pipeline")),
):
    r = await db.execute(select(OportunidadeModel).where(OportunidadeModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Oportunidade não encontrada")
    if m.estado != "aberta":
        raise HTTPException(400, "Só é possível mover oportunidades abertas")
    m.etapa_pipeline_id = etapa_pipeline_id
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


@router.post("/oportunidades/{id}/ganhar", response_model=OportunidadeResponseDTO)
async def ganhar_oportunidade(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    r = await db.execute(select(OportunidadeModel).where(OportunidadeModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Oportunidade não encontrada")
    m.estado = "ganha"
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


class PerderDTO(BaseModel):
    motivo: str = Field(..., min_length=1)


@router.post("/oportunidades/{id}/perder", response_model=OportunidadeResponseDTO)
async def perder_oportunidade(
    id: UUID,
    body: PerderDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    r = await db.execute(select(OportunidadeModel).where(OportunidadeModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Oportunidade não encontrada")
    m.estado = "perdida"
    m.motivo_perda = body.motivo
    m.updated_at = datetime.utcnow()
    await db.commit()
    return m


# ─── Viaturas ────────────────────────────────────────────────────────


class ViaturaCreateDTO(BaseModel):
    cliente_id: UUID
    matricula: str = Field(..., min_length=1, max_length=20)
    marca: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None
    vin: Optional[str] = None


class ViaturaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: str
    matricula: str
    marca: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None
    vin: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/viaturas", response_model=List[ViaturaResponseDTO])
async def list_viaturas(
    cliente_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    stmt = (
        select(ViaturaModel)
        .where(ViaturaModel.company_id == current_user.company_id)
        .where(ViaturaModel.deleted_at.is_(None))
    )
    if cliente_id:
        stmt = stmt.where(ViaturaModel.cliente_id == str(cliente_id))
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/viaturas", response_model=ViaturaResponseDTO, status_code=201)
async def create_viatura(
    body: ViaturaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.create")),
):
    m = ViaturaModel(
        id=uuid4(), company_id=current_user.company_id, cliente_id=str(body.cliente_id),
        matricula=body.matricula, marca=body.marca, modelo=body.modelo, cor=body.cor, vin=body.vin,
    )
    db.add(m)
    await db.commit()
    return m


@router.delete("/viaturas/{id}", status_code=204)
async def delete_viatura(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    r = await db.execute(select(ViaturaModel).where(ViaturaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Viatura não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Fidelização ─────────────────────────────────────────────────────


class ProgramaFidelizacaoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    pontos_por_1000kz: Decimal = Field(default=Decimal("1"), gt=0)
    activo: bool = True


class ProgramaFidelizacaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    nome: str
    pontos_por_1000kz: Decimal
    activo: bool

    class Config:
        from_attributes = True


@router.get("/fidelizacao/programas", response_model=List[ProgramaFidelizacaoResponseDTO])
async def list_programas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    r = await db.execute(select(ProgramaFidelizacaoModel).where(ProgramaFidelizacaoModel.company_id == current_user.company_id))
    return list(r.scalars().all())


@router.post("/fidelizacao/programas", response_model=ProgramaFidelizacaoResponseDTO, status_code=201)
async def create_programa(
    body: ProgramaFidelizacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.gerir_fidelizacao")),
):
    m = ProgramaFidelizacaoModel(id=uuid4(), company_id=current_user.company_id, **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.patch("/fidelizacao/programas/{id}", response_model=ProgramaFidelizacaoResponseDTO)
async def update_programa(
    id: UUID,
    body: ProgramaFidelizacaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.gerir_fidelizacao")),
):
    r = await db.execute(select(ProgramaFidelizacaoModel).where(ProgramaFidelizacaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Programa não encontrado")
    for field, value in body.model_dump().items():
        setattr(m, field, value)
    await db.commit()
    return m


@router.get("/fidelizacao/{cliente_id}/saldo")
async def get_saldo_fidelizacao(
    cliente_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    r = await db.execute(select(SaldoFidelizacaoModel).where(SaldoFidelizacaoModel.cliente_id == str(cliente_id)))
    saldos = list(r.scalars().all())
    return [{"programa_id": str(s.programa_id), "pontos_acumulados": float(s.pontos_acumulados), "cashback_saldo": float(s.cashback_saldo)} for s in saldos]


@router.post("/fidelizacao/acumular")
async def acumular_pontos(
    cliente_id: UUID,
    valor_gasto: Decimal,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.gerir_fidelizacao")),
):
    """Chamado explicitamente pelo fluxo de conclusão de venda (domínio
    Comércio) quando o cliente tem programa de fidelização activo — não
    há mensageria assíncrona no projeto, integração é síncrona e directa."""
    pr = await db.execute(
        select(ProgramaFidelizacaoModel)
        .where(ProgramaFidelizacaoModel.company_id == current_user.company_id)
        .where(ProgramaFidelizacaoModel.activo.is_(True))
    )
    programa = pr.scalars().first()
    if not programa:
        return {"pontos_ganhos": 0}

    pontos_ganhos = (valor_gasto / Decimal("1000")) * Decimal(programa.pontos_por_1000kz)
    sr = await db.execute(
        select(SaldoFidelizacaoModel)
        .where(SaldoFidelizacaoModel.cliente_id == str(cliente_id))
        .where(SaldoFidelizacaoModel.programa_id == programa.id)
    )
    saldo = sr.scalar_one_or_none()
    if not saldo:
        saldo = SaldoFidelizacaoModel(id=uuid4(), cliente_id=str(cliente_id), programa_id=programa.id, pontos_acumulados=Decimal("0"), cashback_saldo=Decimal("0"))
        db.add(saldo)
    saldo.pontos_acumulados = Decimal(saldo.pontos_acumulados) + pontos_ganhos
    await db.commit()
    return {"pontos_ganhos": float(pontos_ganhos)}


# ─── Visitas ─────────────────────────────────────────────────────────


class VisitaCreateDTO(BaseModel):
    oportunidade_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None
    data_hora: datetime
    tipo: str = Field(default="presencial", pattern="^(presencial|remota)$")
    notas: Optional[str] = None


class VisitaUpdateDTO(BaseModel):
    estado: Optional[str] = Field(None, pattern="^(agendada|realizada|cancelada)$")
    notas: Optional[str] = None


class VisitaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    oportunidade_id: Optional[UUID] = None
    cliente_id: Optional[str] = None
    data_hora: datetime
    tipo: str
    responsavel_id: Optional[UUID] = None
    notas: Optional[str] = None
    estado: str

    class Config:
        from_attributes = True


@router.get("/visitas", response_model=List[VisitaResponseDTO])
async def list_visitas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    r = await db.execute(select(VisitaModel).where(VisitaModel.company_id == current_user.company_id).order_by(VisitaModel.data_hora))
    return list(r.scalars().all())


@router.post("/visitas", response_model=VisitaResponseDTO, status_code=201)
async def create_visita(
    body: VisitaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.create")),
):
    m = VisitaModel(
        id=uuid4(), company_id=current_user.company_id, responsavel_id=current_user.id,
        estado="agendada", cliente_id=str(body.cliente_id) if body.cliente_id else None,
        **body.model_dump(exclude={"cliente_id"}),
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/visitas/{id}", response_model=VisitaResponseDTO)
async def update_visita(
    id: UUID,
    body: VisitaUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    r = await db.execute(select(VisitaModel).where(VisitaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Visita não encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.commit()
    return m


# ─── Tarefas ─────────────────────────────────────────────────────────


class TarefaCreateDTO(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=150)
    descricao: Optional[str] = None
    tipo: str = Field(default="followup", pattern="^(chamada|email|reuniao|followup)$")
    relacionado_tipo: Optional[str] = Field(None, pattern="^(lead|oportunidade|cliente)$")
    relacionado_id: Optional[UUID] = None
    prazo: Optional[datetime] = None
    prioridade: str = Field(default="media", pattern="^(baixa|media|alta)$")


class TarefaUpdateDTO(BaseModel):
    estado: Optional[str] = Field(None, pattern="^(pendente|concluida)$")


class TarefaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    titulo: str
    descricao: Optional[str] = None
    tipo: str
    responsavel_id: Optional[UUID] = None
    relacionado_tipo: Optional[str] = None
    relacionado_id: Optional[str] = None
    prazo: Optional[datetime] = None
    estado: str
    prioridade: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/tarefas", response_model=List[TarefaResponseDTO])
async def list_tarefas(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.view")),
):
    stmt = select(TarefaModel).where(TarefaModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(TarefaModel.estado == estado)
    stmt = stmt.order_by(TarefaModel.prazo)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/tarefas", response_model=TarefaResponseDTO, status_code=201)
async def create_tarefa(
    body: TarefaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.create")),
):
    m = TarefaModel(
        id=uuid4(), company_id=current_user.company_id, responsavel_id=current_user.id,
        estado="pendente", relacionado_id=str(body.relacionado_id) if body.relacionado_id else None,
        **body.model_dump(exclude={"relacionado_id"}),
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/tarefas/{id}", response_model=TarefaResponseDTO)
async def update_tarefa(
    id: UUID,
    body: TarefaUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("crm.edit")),
):
    r = await db.execute(select(TarefaModel).where(TarefaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Tarefa não encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.commit()
    return m


__all__ = ["router"]
