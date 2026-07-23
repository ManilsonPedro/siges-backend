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

from fastapi import Response
from sqlalchemy import func

from app.domain.entities import User
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    AbastecimentoAguaModel,
    AnexoModel,
    BoxLavagemModel,
    ConsumoAguaModel,
    FilialModel,
    FornecedorModel,
    MovimentoTanqueAguaModel,
    OrdemLavagemModel,
    TanqueAguaModel,
    UserModel,
)
from app.infrastructure.export.abastecimento_agua_pdf import gerar_abastecimento_pdf
from app.infrastructure.storage import get_storage_provider


router = APIRouter()


async def _gerar_numero_abastecimento(db: AsyncSession, company_id: UUID) -> str:
    """ABA-<ano>-<seq>, mesmo padrão de numero_proforma em caixa.py."""
    ano = datetime.utcnow().strftime("%Y")
    try:
        count_r = await db.execute(
            select(func.count(AbastecimentoAguaModel.id))
            .where(AbastecimentoAguaModel.company_id == company_id)
            .where(func.to_char(AbastecimentoAguaModel.data, "YYYY") == ano)
        )
        n = (count_r.scalar() or 0) + 1
    except Exception:
        count_r = await db.execute(
            select(func.count(AbastecimentoAguaModel.id))
            .where(AbastecimentoAguaModel.company_id == company_id)
        )
        n = (count_r.scalar() or 0) + 1
    return f"ABA-{ano}-{n:05d}"


async def _registar_movimento_tanque(
    db: AsyncSession, *, company_id: UUID, tanque: TanqueAguaModel, tipo: str,
    quantidade_litros: Decimal, registado_por_id: UUID,
    referencia_tipo: Optional[str] = None, referencia_id: Optional[UUID] = None,
    observacoes: Optional[str] = None,
) -> MovimentoTanqueAguaModel:
    """Aplica a variação ao nível do tanque e regista o movimento permanente
    (Fase 8). `quantidade_litros` deve ser positiva; o sinal da variação é
    determinado por `tipo`."""
    nivel_antes = Decimal(tanque.nivel_atual_litros)
    entradas = {"entrada", "ajuste_positivo"}
    if tipo in entradas:
        nivel_depois = nivel_antes + quantidade_litros
    else:
        nivel_depois = max(Decimal("0"), nivel_antes - quantidade_litros)
    tanque.nivel_atual_litros = nivel_depois

    mov = MovimentoTanqueAguaModel(
        id=uuid4(), company_id=company_id, tanque_agua_id=tanque.id, tipo=tipo,
        quantidade_litros=quantidade_litros, nivel_antes=nivel_antes, nivel_depois=nivel_depois,
        referencia_tipo=referencia_tipo, referencia_id=referencia_id,
        observacoes=observacoes, registado_por_id=registado_por_id,
    )
    db.add(mov)
    return mov


class TanqueAguaCreateDTO(BaseModel):
    filial_id: Optional[UUID] = None
    codigo: str = Field(..., min_length=1, max_length=30)
    nome: str = Field(..., min_length=1, max_length=120)
    tipo: str = Field(..., pattern="^(limpa|reciclada|tratada|pluvial)$")
    capacidade_litros: Decimal = Field(..., gt=0)
    nivel_atual_litros: Decimal = Field(default=Decimal("0"), ge=0)
    nivel_minimo_litros: Decimal = Field(default=Decimal("0"), ge=0)
    tem_sensor: bool = False
    sensor_id: Optional[str] = None


class TanqueAguaUpdateDTO(BaseModel):
    filial_id: Optional[UUID] = None
    codigo: Optional[str] = Field(None, min_length=1, max_length=30)
    nome: Optional[str] = Field(None, min_length=1, max_length=120)
    tipo: Optional[str] = Field(None, pattern="^(limpa|reciclada|tratada|pluvial)$")
    capacidade_litros: Optional[Decimal] = Field(None, gt=0)
    nivel_minimo_litros: Optional[Decimal] = Field(None, ge=0)
    estado: Optional[str] = Field(None, pattern="^(activo|manutencao|inactivo)$")
    tem_sensor: Optional[bool] = None
    sensor_id: Optional[str] = None


class TanqueAguaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    filial_id: Optional[UUID] = None
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
    estado: str

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


@router.patch("/tanques/{id}", response_model=TanqueAguaResponseDTO)
async def update_tanque(
    id: UUID,
    body: TanqueAguaUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    r = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.id == id))
    tanque = r.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id or tanque.deleted_at is not None:
        raise HTTPException(404, "Tanque de água não encontrado")

    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(tanque, campo, valor)
    await db.commit()
    return tanque


@router.delete("/tanques/{id}", status_code=204)
async def delete_tanque(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    r = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.id == id))
    tanque = r.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id or tanque.deleted_at is not None:
        raise HTTPException(404, "Tanque de água não encontrado")

    tanque.deleted_at = datetime.utcnow()
    await db.commit()


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
    await _registar_movimento_tanque(
        db, company_id=current_user.company_id, tanque=tanque, tipo="saida",
        quantidade_litros=body.litros_consumidos, registado_por_id=current_user.id,
        referencia_tipo="consumo", referencia_id=m.id,
    )
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


# ─── Abastecimentos (Fase 3) ────────────────────────────────────────


class AbastecimentoAguaCreateDTO(BaseModel):
    tanque_agua_id: UUID
    fornecedor_id: UUID
    filial_id: Optional[UUID] = None
    equipamento_id: Optional[UUID] = None
    quantidade_litros: Decimal = Field(..., gt=0)
    valor_por_litro: Decimal = Field(..., ge=0)
    metodo_pagamento: Optional[str] = None
    observacoes: Optional[str] = None
    recebido_por_id: Optional[UUID] = None


class AbastecimentoAguaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    numero: Optional[str] = None
    tanque_agua_id: UUID
    fornecedor_id: UUID
    filial_id: Optional[UUID] = None
    equipamento_id: Optional[UUID] = None
    quantidade_litros: Decimal
    valor_por_litro: Decimal
    custo_total: Decimal
    metodo_pagamento: Optional[str] = None
    observacoes: Optional[str] = None
    registado_por_id: UUID
    recebido_por_id: Optional[UUID] = None
    estado: str
    data: datetime

    class Config:
        from_attributes = True


@router.get("/abastecimentos", response_model=List[AbastecimentoAguaResponseDTO])
async def list_abastecimentos(
    tanque_agua_id: Optional[UUID] = None,
    fornecedor_id: Optional[UUID] = None,
    filial_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    valor_min: Optional[Decimal] = None,
    valor_max: Optional[Decimal] = None,
    quantidade_min: Optional[Decimal] = None,
    quantidade_max: Optional[Decimal] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    stmt = select(AbastecimentoAguaModel).where(AbastecimentoAguaModel.company_id == current_user.company_id)
    if tanque_agua_id:
        stmt = stmt.where(AbastecimentoAguaModel.tanque_agua_id == tanque_agua_id)
    if fornecedor_id:
        stmt = stmt.where(AbastecimentoAguaModel.fornecedor_id == fornecedor_id)
    if filial_id:
        stmt = stmt.where(AbastecimentoAguaModel.filial_id == filial_id)
    if estado:
        stmt = stmt.where(AbastecimentoAguaModel.estado == estado)
    if data_inicio:
        stmt = stmt.where(AbastecimentoAguaModel.data >= data_inicio)
    if data_fim:
        stmt = stmt.where(AbastecimentoAguaModel.data <= data_fim)
    if valor_min is not None:
        stmt = stmt.where(AbastecimentoAguaModel.custo_total >= valor_min)
    if valor_max is not None:
        stmt = stmt.where(AbastecimentoAguaModel.custo_total <= valor_max)
    if quantidade_min is not None:
        stmt = stmt.where(AbastecimentoAguaModel.quantidade_litros >= quantidade_min)
    if quantidade_max is not None:
        stmt = stmt.where(AbastecimentoAguaModel.quantidade_litros <= quantidade_max)
    stmt = stmt.order_by(AbastecimentoAguaModel.data.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("/abastecimentos", response_model=AbastecimentoAguaResponseDTO, status_code=201)
async def create_abastecimento(
    req: Request,
    body: AbastecimentoAguaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.gerir_abastecimentos")),
):
    tr = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.id == body.tanque_agua_id))
    tanque = tr.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id or tanque.deleted_at is not None:
        raise HTTPException(404, "Tanque de água não encontrado")

    fr = await db.execute(select(FornecedorModel).where(FornecedorModel.id == body.fornecedor_id))
    fornecedor = fr.scalar_one_or_none()
    if not fornecedor or fornecedor.company_id != current_user.company_id:
        raise HTTPException(404, "Fornecedor não encontrado")

    custo_total = body.quantidade_litros * body.valor_por_litro
    numero = await _gerar_numero_abastecimento(db, current_user.company_id)

    abastecimento = AbastecimentoAguaModel(
        id=uuid4(), company_id=current_user.company_id, numero=numero,
        tanque_agua_id=body.tanque_agua_id, fornecedor_id=body.fornecedor_id,
        filial_id=body.filial_id, equipamento_id=body.equipamento_id,
        quantidade_litros=body.quantidade_litros, valor_por_litro=body.valor_por_litro,
        custo_total=custo_total, metodo_pagamento=body.metodo_pagamento,
        observacoes=body.observacoes, registado_por_id=current_user.id,
        recebido_por_id=body.recebido_por_id,
    )
    db.add(abastecimento)
    await _registar_movimento_tanque(
        db, company_id=current_user.company_id, tanque=tanque, tipo="entrada",
        quantidade_litros=body.quantidade_litros, registado_por_id=current_user.id,
        referencia_tipo="abastecimento", referencia_id=abastecimento.id,
    )
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "abastecimento_agua", abastecimento.id,
        dados_novos={"numero": numero, "quantidade_litros": str(body.quantidade_litros),
                     "custo_total": str(custo_total), "fornecedor_id": str(body.fornecedor_id)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return abastecimento


class AbastecimentoAguaEstadoDTO(BaseModel):
    estado: str = Field(..., pattern="^(registado|aprovado|documentado|pago|concluido)$")


@router.patch("/abastecimentos/{id}/estado", response_model=AbastecimentoAguaResponseDTO)
async def atualizar_estado_abastecimento(
    id: UUID,
    req: Request,
    body: AbastecimentoAguaEstadoDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.gerir_abastecimentos")),
):
    r = await db.execute(select(AbastecimentoAguaModel).where(AbastecimentoAguaModel.id == id))
    abastecimento = r.scalar_one_or_none()
    if not abastecimento or abastecimento.company_id != current_user.company_id:
        raise HTTPException(404, "Abastecimento não encontrado")

    estado_anterior = abastecimento.estado
    abastecimento.estado = body.estado
    await write_audit(
        db, current_user.id, current_user.company_id,
        "mudanca_estado", "abastecimento_agua", abastecimento.id,
        dados_anteriores={"estado": estado_anterior}, dados_novos={"estado": body.estado},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return abastecimento


# ─── Movimentos manuais do tanque (Fase 8) ──────────────────────────


class MovimentoTanqueAguaCreateDTO(BaseModel):
    tipo: str = Field(..., pattern="^(ajuste|perda|evaporacao|vazamento|transferencia)$")
    quantidade_litros: Decimal = Field(..., gt=0)
    observacoes: Optional[str] = None


class MovimentoTanqueAguaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    tanque_agua_id: UUID
    tipo: str
    quantidade_litros: Decimal
    nivel_antes: Decimal
    nivel_depois: Decimal
    referencia_tipo: Optional[str] = None
    referencia_id: Optional[UUID] = None
    observacoes: Optional[str] = None
    registado_por_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/tanques/{id}/movimentos", response_model=List[MovimentoTanqueAguaResponseDTO])
async def list_movimentos_tanque(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    r = await db.execute(
        select(MovimentoTanqueAguaModel)
        .where(MovimentoTanqueAguaModel.company_id == current_user.company_id)
        .where(MovimentoTanqueAguaModel.tanque_agua_id == id)
        .order_by(MovimentoTanqueAguaModel.created_at.desc())
    )
    return list(r.scalars().all())


@router.post("/tanques/{id}/movimentos", response_model=MovimentoTanqueAguaResponseDTO, status_code=201)
async def create_movimento_tanque(
    id: UUID,
    body: MovimentoTanqueAguaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.registar_leitura")),
):
    tr = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.id == id))
    tanque = tr.scalar_one_or_none()
    if not tanque or tanque.company_id != current_user.company_id or tanque.deleted_at is not None:
        raise HTTPException(404, "Tanque de água não encontrado")

    # ajuste é tratado como entrada (correcção para cima); os restantes tipos
    # manuais (perda, evaporação, vazamento, transferência) são sempre saída.
    tipo_efectivo = "ajuste_positivo" if body.tipo == "ajuste" else body.tipo
    mov = await _registar_movimento_tanque(
        db, company_id=current_user.company_id, tanque=tanque, tipo=tipo_efectivo,
        quantidade_litros=body.quantidade_litros, registado_por_id=current_user.id,
        referencia_tipo="ajuste_manual", observacoes=body.observacoes,
    )
    mov.tipo = body.tipo  # preserva o tipo de negócio original na resposta/histórico
    await db.commit()
    return mov


# ─── Documentos de Abastecimento (Fase 5) ───────────────────────────

_TIPOS_DOCUMENTO_ABASTECIMENTO = {"proforma", "fatura", "fatura_recibo", "recibo", "ordem_recepcao"}


@router.post("/abastecimentos/{id}/documentos/{tipo}")
async def gerar_documento_abastecimento(
    id: UUID,
    tipo: str,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.gerir_abastecimentos")),
):
    if tipo not in _TIPOS_DOCUMENTO_ABASTECIMENTO:
        raise HTTPException(400, f"Tipo de documento inválido: {tipo}")

    r = await db.execute(select(AbastecimentoAguaModel).where(AbastecimentoAguaModel.id == id))
    abastecimento = r.scalar_one_or_none()
    if not abastecimento or abastecimento.company_id != current_user.company_id:
        raise HTTPException(404, "Abastecimento não encontrado")

    fr = await db.execute(select(FornecedorModel).where(FornecedorModel.id == abastecimento.fornecedor_id))
    fornecedor = fr.scalar_one_or_none()
    tr = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.id == abastecimento.tanque_agua_id))
    tanque = tr.scalar_one_or_none()
    filial_nome = None
    if abastecimento.filial_id:
        flr = await db.execute(select(FilialModel).where(FilialModel.id == abastecimento.filial_id))
        filial = flr.scalar_one_or_none()
        filial_nome = filial.nome if filial else None

    pdf_bytes = gerar_abastecimento_pdf(
        abastecimento, tipo,
        fornecedor_nome=fornecedor.nome if fornecedor else "",
        fornecedor_nif=fornecedor.nif if fornecedor else "",
        tanque_nome=tanque.nome if tanque else "",
        filial_nome=filial_nome,
    )

    versao_r = await db.execute(
        select(func.max(AnexoModel.versao))
        .where(AnexoModel.company_id == current_user.company_id)
        .where(AnexoModel.entity_type == "abastecimento_agua")
        .where(AnexoModel.entity_id == abastecimento.id)
        .where(AnexoModel.tipo_documento == tipo)
    )
    versao = (versao_r.scalar() or 0) + 1
    file_key = f"anexos/abastecimento_agua/{abastecimento.id}/{tipo}_v{versao}_{uuid4().hex[:8]}.pdf"

    storage = get_storage_provider()
    import io as _io
    await storage.upload(file_key, _io.BytesIO(pdf_bytes), content_type="application/pdf")

    file_name = f"{tipo}-{abastecimento.numero or abastecimento.id}.pdf"
    anexo = AnexoModel(
        id=uuid4(), company_id=current_user.company_id,
        entity_type="abastecimento_agua", entity_id=abastecimento.id,
        tipo_documento=tipo, versao=versao,
        file_path=file_key, file_name=file_name,
        mime_type="application/pdf", size_bytes=len(pdf_bytes),
        uploaded_by=current_user.id,
    )
    db.add(anexo)

    if tipo in ("fatura", "fatura_recibo") and abastecimento.estado in ("registado", "aprovado"):
        abastecimento.estado = "documentado"

    await write_audit(
        db, current_user.id, current_user.company_id,
        "documento_gerado", "abastecimento_agua", abastecimento.id,
        dados_novos={"tipo_documento": tipo, "versao": versao},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()

    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{file_name}"'},
    )


# ─── Consumo por dimensão operacional (Fase 7) ──────────────────────


@router.get("/consumo-por-dimensao")
async def consumo_por_dimensao(
    dimensao: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    """Agrega ConsumoAguaModel (referencia_tipo='ordem_lavagem') por
    box, colaborador responsável ou equipa. `turno` não é suportado nesta
    fase — OrdemLavagemModel não tem turno_id directo, apenas `equipa`
    (CSV) atribuída via EscalaTurno; cruzar por turno exigiria inferência
    indirecta (box+data+escala) que não é confiável o suficiente para um
    KPI. Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fase 7."""
    if dimensao not in ("box", "colaborador", "equipa"):
        raise HTTPException(400, "Dimensão inválida. Use: box, colaborador ou equipa")

    cr = await db.execute(
        select(ConsumoAguaModel)
        .where(ConsumoAguaModel.company_id == current_user.company_id)
        .where(ConsumoAguaModel.referencia_tipo == "ordem_lavagem")
    )
    consumos = list(cr.scalars().all())
    if not consumos:
        return {"dimensao": dimensao, "itens": []}

    ordens_r = await db.execute(
        select(OrdemLavagemModel).where(OrdemLavagemModel.id.in_([c.referencia_id for c in consumos]))
    )
    ordens_por_id = {o.id: o for o in ordens_r.scalars().all()}

    agregados: dict[str, Decimal] = {}
    contagem: dict[str, int] = {}

    labels: dict[str, str] = {}
    if dimensao == "box":
        boxes_r = await db.execute(select(BoxLavagemModel).where(BoxLavagemModel.company_id == current_user.company_id))
        nomes_box = {b.id: f"{b.codigo} — {b.nome}" for b in boxes_r.scalars().all()}

        def chave_de(ordem):
            return (str(ordem.box_id), nomes_box.get(ordem.box_id, "Sem box")) if ordem and ordem.box_id else ("sem_box", "Sem box")

    elif dimensao == "colaborador":
        users_r = await db.execute(select(UserModel).where(UserModel.company_id == current_user.company_id))
        nomes_user = {u.id: u.full_name for u in users_r.scalars().all()}

        def chave_de(ordem):
            if ordem and ordem.colaborador_responsavel_id:
                return str(ordem.colaborador_responsavel_id), nomes_user.get(ordem.colaborador_responsavel_id, "Sem colaborador")
            return "sem_colaborador", "Sem colaborador"

    else:  # equipa
        def chave_de(ordem):
            equipa = ordem.equipa if ordem else None
            return (equipa, equipa) if equipa else ("sem_equipa", "Sem equipa")

    for c in consumos:
        ordem = ordens_por_id.get(c.referencia_id)
        chave, label = chave_de(ordem)
        agregados[chave] = agregados.get(chave, Decimal("0")) + Decimal(c.litros_consumidos)
        contagem[chave] = contagem.get(chave, 0) + 1
        labels[chave] = label

    itens = [
        {"chave": chave, "label": labels[chave], "litros": float(litros), "n_lavagens": contagem[chave]}
        for chave, litros in agregados.items()
    ]
    itens.sort(key=lambda x: x["litros"], reverse=True)
    return {"dimensao": dimensao, "itens": itens}


# ─── Alertas de Água (Fase 9) ────────────────────────────────────────
# Âmbito específico de água (regras hardcoded, mesmo padrão de
# estoque.py::alertas-stock-minimo) — sem motor de alertas genérico
# nesta fase. Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fase 9.

_DIAS_DOCUMENTACAO_PENDENTE = 7
_JANELA_CUSTO_MEDIO_DIAS = 90
_FACTOR_CONSUMO_ANORMAL = 2


@router.get("/alertas")
async def alertas_agua(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    from datetime import timedelta

    agora = datetime.utcnow()
    alertas: list[dict] = []

    tr = await db.execute(
        select(TanqueAguaModel)
        .where(TanqueAguaModel.company_id == current_user.company_id)
        .where(TanqueAguaModel.deleted_at.is_(None))
    )
    tanques = list(tr.scalars().all())
    for t in tanques:
        if Decimal(t.nivel_atual_litros) < Decimal(t.nivel_minimo_litros):
            alertas.append({
                "tipo": "nivel_minimo", "severidade": "alta",
                "mensagem": f"Tanque {t.codigo} abaixo do nível mínimo ({t.nivel_atual_litros}L / mín. {t.nivel_minimo_litros}L)",
                "tanque_agua_id": str(t.id),
            })
        if Decimal(t.nivel_atual_litros) >= Decimal(t.capacidade_litros):
            alertas.append({
                "tipo": "capacidade_maxima", "severidade": "media",
                "mensagem": f"Tanque {t.codigo} atingiu a capacidade máxima ({t.capacidade_litros}L)",
                "tanque_agua_id": str(t.id),
            })

    # Consumo anormal: consumo de hoje vs. média móvel dos últimos 30 dias
    janela_r = await db.execute(
        select(ConsumoAguaModel)
        .where(ConsumoAguaModel.company_id == current_user.company_id)
        .where(ConsumoAguaModel.data >= agora - timedelta(days=30))
    )
    consumos_30d = list(janela_r.scalars().all())
    consumo_hoje = sum((Decimal(c.litros_consumidos) for c in consumos_30d if c.data.date() == agora.date()), Decimal("0"))
    dias_com_dados = len({c.data.date() for c in consumos_30d}) or 1
    media_diaria = sum((Decimal(c.litros_consumidos) for c in consumos_30d), Decimal("0")) / dias_com_dados
    if media_diaria > 0 and consumo_hoje > media_diaria * _FACTOR_CONSUMO_ANORMAL:
        alertas.append({
            "tipo": "consumo_anormal", "severidade": "media",
            "mensagem": f"Consumo de hoje ({consumo_hoje:.0f}L) mais do que o dobro da média diária dos últimos 30 dias ({media_diaria:.0f}L)",
            "tanque_agua_id": None,
        })

    # Abastecimento pendente de documentação
    abast_r = await db.execute(
        select(AbastecimentoAguaModel)
        .where(AbastecimentoAguaModel.company_id == current_user.company_id)
        .where(AbastecimentoAguaModel.estado.notin_(["documentado", "pago", "concluido"]))
        .where(AbastecimentoAguaModel.data <= agora - timedelta(days=_DIAS_DOCUMENTACAO_PENDENTE))
    )
    for a in abast_r.scalars().all():
        alertas.append({
            "tipo": "documentacao_pendente", "severidade": "media",
            "mensagem": f"Abastecimento {a.numero or a.id} sem documentação há mais de {_DIAS_DOCUMENTACAO_PENDENTE} dias",
            "abastecimento_id": str(a.id),
        })

    # Abastecimento acima do custo médio (últimos 90 dias)
    custo_r = await db.execute(
        select(AbastecimentoAguaModel)
        .where(AbastecimentoAguaModel.company_id == current_user.company_id)
        .where(AbastecimentoAguaModel.data >= agora - timedelta(days=_JANELA_CUSTO_MEDIO_DIAS))
    )
    abastecimentos_90d = list(custo_r.scalars().all())
    if abastecimentos_90d:
        custo_medio_litro = sum((Decimal(a.valor_por_litro) for a in abastecimentos_90d), Decimal("0")) / len(abastecimentos_90d)
        for a in abastecimentos_90d:
            if Decimal(a.valor_por_litro) > custo_medio_litro * Decimal("1.2"):
                alertas.append({
                    "tipo": "custo_acima_media", "severidade": "baixa",
                    "mensagem": f"Abastecimento {a.numero or a.id} acima do custo médio por litro ({a.valor_por_litro} Kz vs. média {custo_medio_litro:.2f} Kz)",
                    "abastecimento_id": str(a.id),
                })

    return {"alertas": alertas, "total": len(alertas)}


# ─── Custos Consolidados (Fase 11) ──────────────────────────────────


@router.get("/custos")
async def custos_agua(
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("operacoes.agua.view")),
):
    """Relatórios de custo consolidados: por abastecimento, fornecedor,
    filial, tanque, e evolução mensal do preço médio da água. Custo por
    serviço (tipo de lavagem) é servido por
    GET /bi/agua/consumo-por-servico (cruza custo via ConsumoAguaModel).
    """
    stmt = select(AbastecimentoAguaModel).where(AbastecimentoAguaModel.company_id == current_user.company_id)
    if data_inicio:
        stmt = stmt.where(AbastecimentoAguaModel.data >= data_inicio)
    if data_fim:
        stmt = stmt.where(AbastecimentoAguaModel.data <= data_fim)
    r = await db.execute(stmt)
    abastecimentos = list(r.scalars().all())

    por_abastecimento = [
        {"abastecimento_id": str(a.id), "numero": a.numero, "custo_total": float(a.custo_total), "data": a.data.isoformat()}
        for a in abastecimentos
    ]

    por_fornecedor: dict[str, Decimal] = {}
    por_filial: dict[str, Decimal] = {}
    por_tanque: dict[str, Decimal] = {}
    por_mes: dict[str, list[Decimal]] = {}
    for a in abastecimentos:
        custo = Decimal(a.custo_total)
        fid = str(a.fornecedor_id)
        por_fornecedor[fid] = por_fornecedor.get(fid, Decimal("0")) + custo
        if a.filial_id:
            flid = str(a.filial_id)
            por_filial[flid] = por_filial.get(flid, Decimal("0")) + custo
        tid = str(a.tanque_agua_id)
        por_tanque[tid] = por_tanque.get(tid, Decimal("0")) + custo
        mes = a.data.strftime("%Y-%m")
        por_mes.setdefault(mes, []).append(Decimal(a.valor_por_litro))

    fr = await db.execute(select(FornecedorModel).where(FornecedorModel.company_id == current_user.company_id))
    nomes_fornecedor = {str(f.id): f.nome for f in fr.scalars().all()}
    flr = await db.execute(select(FilialModel).where(FilialModel.company_id == current_user.company_id))
    nomes_filial = {str(f.id): f.nome for f in flr.scalars().all()}
    tr = await db.execute(select(TanqueAguaModel).where(TanqueAguaModel.company_id == current_user.company_id))
    nomes_tanque = {str(t.id): t.codigo for t in tr.scalars().all()}

    evolucao_preco = [
        {"mes": mes, "preco_medio_litro": float((sum(precos, Decimal("0")) / len(precos)).quantize(Decimal("0.0001")))}
        for mes, precos in sorted(por_mes.items())
    ]

    return {
        "por_abastecimento": por_abastecimento,
        "por_fornecedor": [
            {"fornecedor_id": fid, "fornecedor_nome": nomes_fornecedor.get(fid, "—"), "custo_total": float(v)}
            for fid, v in sorted(por_fornecedor.items(), key=lambda x: x[1], reverse=True)
        ],
        "por_filial": [
            {"filial_id": flid, "filial_nome": nomes_filial.get(flid, "—"), "custo_total": float(v)}
            for flid, v in sorted(por_filial.items(), key=lambda x: x[1], reverse=True)
        ],
        "por_tanque": [
            {"tanque_agua_id": tid, "tanque_codigo": nomes_tanque.get(tid, "—"), "custo_total": float(v)}
            for tid, v in sorted(por_tanque.items(), key=lambda x: x[1], reverse=True)
        ],
        "evolucao_preco_medio_litro": evolucao_preco,
    }


__all__ = ["router"]
