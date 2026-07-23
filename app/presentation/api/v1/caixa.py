"""Caixa / Vendas — POS interno.

Fluxo:
  1. POST /sessoes/abrir
  2. POST /vendas → cria rascunho com linhas
  3. POST /vendas/{id}/pagamentos (1..N)
  4. POST /vendas/{id}/concluir
       → confere stock disponível (por linha)
       → gera nº de proforma sequencial (idempotente)
       → stock_service.registar_movimento (saida_venda) por linha
       → devolve venda com numero_proforma
  5. GET  /vendas/{id}/proforma.pdf
  6. POST /sessoes/{id}/fechar (apura diferenca)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.domain.services import stock_service
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    ArmazemModel,
    CaixaSessaoModel,
    ProdutoModel,
    StockSaldoModel,
    VendaLinhaModel,
    VendaModel,
    VendaPagamentoModel,
)
from app.infrastructure.export.proforma_pdf import gerar_proforma_pdf


router = APIRouter()


async def _emitir_numero_proforma(db: AsyncSession, *, company_id: UUID, venda: VendaModel) -> str:
    """Gera o nº sequencial de proforma (PRF-<ano>-<seq>) para a venda.

    Idempotente: se a venda já tiver número atribuído, devolve o mesmo
    (chamar duas vezes para a mesma venda nunca gera dois números).
    """
    if venda.numero_proforma:
        return venda.numero_proforma

    ano = (venda.data or datetime.utcnow()).strftime("%Y")
    try:
        count_r = await db.execute(
            select(func.count(VendaModel.id))
            .where(VendaModel.company_id == company_id)
            .where(VendaModel.numero_proforma.isnot(None))
            .where(func.to_char(VendaModel.data, "YYYY") == ano)
        )
        n = (count_r.scalar() or 0) + 1
    except Exception:
        # Fallback p/ SQLite (sem to_char) — usa contador absoluto
        count_r = await db.execute(
            select(func.count(VendaModel.id))
            .where(VendaModel.company_id == company_id)
            .where(VendaModel.numero_proforma.isnot(None))
        )
        n = (count_r.scalar() or 0) + 1

    numero = f"PRF-{ano}-{n:05d}"
    venda.numero_proforma = numero
    return numero


# ─── DTOs ────────────────────────────────────────────────────────────


class SessaoAbrirDTO(BaseModel):
    armazem_id: UUID
    fundo_inicial: Decimal = Field(default=Decimal("0"), ge=0)
    observacao: Optional[str] = None


class SessaoFecharDTO(BaseModel):
    fundo_contado: Decimal = Field(..., ge=0)
    observacao: Optional[str] = None


class SessaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    utilizador_id: UUID
    armazem_id: UUID
    abertura_em: datetime
    fundo_inicial: Decimal
    fecho_em: Optional[datetime] = None
    fundo_apurado: Optional[Decimal] = None
    fundo_contado: Optional[Decimal] = None
    diferenca: Optional[Decimal] = None
    observacao: Optional[str] = None
    estado: str

    class Config:
        from_attributes = True


class LinhaCreateDTO(BaseModel):
    produto_id: UUID
    quantidade: Decimal = Field(..., gt=0)
    preco_unitario: Optional[Decimal] = None  # default = preco_base do produto
    iva_pct: Optional[Decimal] = None
    desconto_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class VendaCreateDTO(BaseModel):
    sessao_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None
    armazem_id: UUID
    linhas: List[LinhaCreateDTO] = Field(default_factory=list)
    observacao: Optional[str] = None


class PagamentoCreateDTO(BaseModel):
    forma: str = Field(..., pattern="^(numerario|tpa|transferencia|cheque)$")
    valor: Decimal = Field(..., gt=0)
    ref_externa: Optional[str] = None


class LinhaResponseDTO(BaseModel):
    id: UUID
    produto_id: UUID
    sku_snapshot: str
    nome_snapshot: str
    quantidade: Decimal
    preco_unitario: Decimal
    iva_pct: Decimal
    desconto_pct: Decimal
    subtotal: Decimal

    class Config:
        from_attributes = True


class PagamentoResponseDTO(BaseModel):
    id: UUID
    forma: str
    valor: Decimal
    ref_externa: Optional[str] = None
    data: datetime

    class Config:
        from_attributes = True


class VendaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    sessao_id: Optional[UUID] = None
    cliente_id: Optional[str] = None
    armazem_id: UUID
    numero_proforma: Optional[str] = None
    data: datetime
    total_bruto: Decimal
    total_desconto: Decimal
    total_iva: Decimal
    total_liquido: Decimal
    estado: str
    correlation_id: str
    numero_fatura_interna: Optional[str] = None
    observacao: Optional[str] = None
    linhas: List[LinhaResponseDTO] = []
    pagamentos: List[PagamentoResponseDTO] = []

    class Config:
        from_attributes = True


# ─── Helpers ─────────────────────────────────────────────────────────


def _calc_subtotal(qtd: Decimal, preco: Decimal, iva_pct: Decimal,
                   desc_pct: Decimal) -> Decimal:
    bruto = qtd * preco
    desconto = bruto * (desc_pct / Decimal("100"))
    base = bruto - desconto
    iva = base * (iva_pct / Decimal("100"))
    return (base + iva).quantize(Decimal("0.01"))


def _recalc_totais(venda: VendaModel) -> None:
    bruto = Decimal("0")
    desc = Decimal("0")
    iva = Decimal("0")
    liq = Decimal("0")
    for ln in venda.linhas:
        b = Decimal(ln.quantidade) * Decimal(ln.preco_unitario)
        d = b * (Decimal(ln.desconto_pct) / Decimal("100"))
        base = b - d
        i = base * (Decimal(ln.iva_pct) / Decimal("100"))
        bruto += b
        desc += d
        iva += i
        liq += (base + i)
    venda.total_bruto = bruto.quantize(Decimal("0.01"))
    venda.total_desconto = desc.quantize(Decimal("0.01"))
    venda.total_iva = iva.quantize(Decimal("0.01"))
    venda.total_liquido = liq.quantize(Decimal("0.01"))


async def _load_venda(db: AsyncSession, id: UUID, company_id: UUID) -> VendaModel:
    r = await db.execute(
        select(VendaModel)
        .where(VendaModel.id == id)
        .options(selectinload(VendaModel.linhas),
                 selectinload(VendaModel.pagamentos))
    )
    v = r.scalar_one_or_none()
    if not v or v.company_id != company_id:
        raise HTTPException(404, "Venda não encontrada")
    return v


# ─── Sessões de Caixa ────────────────────────────────────────────────


@router.post("/sessoes/abrir", response_model=SessaoResponseDTO, status_code=201)
async def abrir_sessao(
    req: Request,
    body: SessaoAbrirDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Não permitir duas sessões abertas em paralelo para o mesmo utilizador.
    r = await db.execute(
        select(CaixaSessaoModel)
        .where(CaixaSessaoModel.utilizador_id == current_user.id)
        .where(CaixaSessaoModel.estado == "aberta")
    )
    if r.scalar_one_or_none():
        raise HTTPException(409, "Já existe uma sessão aberta para este utilizador")

    s = CaixaSessaoModel(
        id=uuid4(), company_id=current_user.company_id,
        utilizador_id=current_user.id,
        armazem_id=body.armazem_id,
        abertura_em=datetime.utcnow(),
        fundo_inicial=body.fundo_inicial,
        observacao=body.observacao, estado="aberta",
    )
    db.add(s)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "caixa_abrir_sessao", "caixa_sessao", s.id,
        dados_novos={"armazem_id": str(body.armazem_id),
                     "fundo_inicial": str(body.fundo_inicial)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return s


@router.post("/sessoes/{id}/fechar", response_model=SessaoResponseDTO)
async def fechar_sessao(
    id: UUID,
    req: Request,
    body: SessaoFecharDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(CaixaSessaoModel).where(CaixaSessaoModel.id == id))
    s = r.scalar_one_or_none()
    if not s or s.company_id != current_user.company_id:
        raise HTTPException(404, "Sessão não encontrada")
    if s.estado == "fechada":
        raise HTTPException(409, "Sessão já está fechada")

    # Apurado = fundo_inicial + Σ pagamentos numerário das vendas concluídas da sessão
    vr = await db.execute(
        select(VendaModel).options(selectinload(VendaModel.pagamentos))
        .where(VendaModel.sessao_id == id)
        .where(VendaModel.estado == "concluida")
    )
    apurado = Decimal(s.fundo_inicial)
    for v in vr.scalars().all():
        for p in v.pagamentos:
            if p.forma == "numerario":
                apurado += Decimal(p.valor)
    s.fundo_apurado = apurado.quantize(Decimal("0.01"))
    s.fundo_contado = body.fundo_contado
    s.diferenca = (Decimal(body.fundo_contado) - apurado).quantize(Decimal("0.01"))
    s.fecho_em = datetime.utcnow()
    s.estado = "fechada"
    if body.observacao:
        s.observacao = (s.observacao or "") + f"\n[fecho] {body.observacao}"

    await write_audit(
        db, current_user.id, current_user.company_id,
        "caixa_fechar_sessao", "caixa_sessao", s.id,
        dados_novos={"apurado": str(s.fundo_apurado),
                     "contado": str(s.fundo_contado),
                     "diferenca": str(s.diferenca)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return s


@router.get("/sessoes", response_model=List[SessaoResponseDTO])
async def list_sessoes(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (select(CaixaSessaoModel)
            .where(CaixaSessaoModel.company_id == current_user.company_id)
            .order_by(CaixaSessaoModel.abertura_em.desc()))
    if estado:
        stmt = stmt.where(CaixaSessaoModel.estado == estado)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.get("/sessoes/activa", response_model=Optional[SessaoResponseDTO])
async def sessao_activa(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(CaixaSessaoModel)
        .where(CaixaSessaoModel.utilizador_id == current_user.id)
        .where(CaixaSessaoModel.estado == "aberta")
    )
    return r.scalar_one_or_none()


# ─── Vendas ──────────────────────────────────────────────────────────


@router.post("/vendas", response_model=VendaResponseDTO, status_code=201)
async def criar_venda(
    req: Request,
    body: VendaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Carregar produtos para snapshots e preços default
    venda = VendaModel(
        id=uuid4(), company_id=current_user.company_id,
        sessao_id=body.sessao_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        armazem_id=body.armazem_id,
        data=datetime.utcnow(), estado="rascunho",
        correlation_id=str(uuid4()),
        observacao=body.observacao, created_by=current_user.id,
    )
    db.add(venda)

    for ln_in in body.linhas:
        pr = await db.execute(select(ProdutoModel).where(ProdutoModel.id == ln_in.produto_id))
        prod = pr.scalar_one_or_none()
        if not prod or prod.company_id != current_user.company_id:
            raise HTTPException(404, f"Produto {ln_in.produto_id} não encontrado")
        preco = ln_in.preco_unitario if ln_in.preco_unitario is not None else Decimal(prod.preco_base)
        iva = ln_in.iva_pct if ln_in.iva_pct is not None else Decimal(prod.iva_pct)
        sub = _calc_subtotal(ln_in.quantidade, preco, iva, ln_in.desconto_pct)
        venda.linhas.append(VendaLinhaModel(
            id=uuid4(), produto_id=prod.id,
            sku_snapshot=prod.sku, nome_snapshot=prod.nome,
            quantidade=ln_in.quantidade, preco_unitario=preco,
            iva_pct=iva, desconto_pct=ln_in.desconto_pct, subtotal=sub,
        ))
    _recalc_totais(venda)
    await db.flush()
    await db.commit()
    return await _load_venda(db, venda.id, current_user.company_id)


@router.post("/vendas/{id}/linhas", response_model=VendaResponseDTO)
async def adicionar_linha(
    id: UUID, body: LinhaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    v = await _load_venda(db, id, current_user.company_id)
    if v.estado != "rascunho":
        raise HTTPException(409, "Só é possível alterar vendas em rascunho")
    pr = await db.execute(select(ProdutoModel).where(ProdutoModel.id == body.produto_id))
    prod = pr.scalar_one_or_none()
    if not prod:
        raise HTTPException(404, "Produto não encontrado")
    preco = body.preco_unitario if body.preco_unitario is not None else Decimal(prod.preco_base)
    iva = body.iva_pct if body.iva_pct is not None else Decimal(prod.iva_pct)
    sub = _calc_subtotal(body.quantidade, preco, iva, body.desconto_pct)
    v.linhas.append(VendaLinhaModel(
        id=uuid4(), produto_id=prod.id,
        sku_snapshot=prod.sku, nome_snapshot=prod.nome,
        quantidade=body.quantidade, preco_unitario=preco,
        iva_pct=iva, desconto_pct=body.desconto_pct, subtotal=sub,
    ))
    _recalc_totais(v)
    await db.commit()
    return await _load_venda(db, v.id, current_user.company_id)


@router.delete("/vendas/{id}/linhas/{lid}", response_model=VendaResponseDTO)
async def remover_linha(
    id: UUID, lid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    v = await _load_venda(db, id, current_user.company_id)
    if v.estado != "rascunho":
        raise HTTPException(409, "Só é possível alterar vendas em rascunho")
    target = next((ln for ln in v.linhas if ln.id == lid), None)
    if not target:
        raise HTTPException(404, "Linha não encontrada")
    v.linhas.remove(target)
    await db.delete(target)
    _recalc_totais(v)
    await db.commit()
    return await _load_venda(db, v.id, current_user.company_id)


@router.post("/vendas/{id}/pagamentos", response_model=VendaResponseDTO)
async def adicionar_pagamento(
    id: UUID, body: PagamentoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    v = await _load_venda(db, id, current_user.company_id)
    if v.estado not in ("rascunho", "concluida"):
        raise HTTPException(409, "Estado de venda não permite pagamento")
    p = VendaPagamentoModel(
        id=uuid4(), venda_id=v.id, forma=body.forma,
        valor=body.valor, ref_externa=body.ref_externa,
        data=datetime.utcnow(),
    )
    db.add(p)
    await db.commit()
    return await _load_venda(db, v.id, current_user.company_id)


@router.post("/vendas/{id}/concluir", response_model=VendaResponseDTO)
async def concluir_venda(
    id: UUID, req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    v = await _load_venda(db, id, current_user.company_id)

    # Idempotência: se já está concluida, devolve-a sem refazer side-effects.
    if v.estado == "concluida":
        return v
    if v.estado == "anulada":
        raise HTTPException(409, "Venda anulada não pode ser concluída")
    if not v.linhas:
        raise HTTPException(400, "Venda sem linhas")

    pago = sum((Decimal(p.valor) for p in v.pagamentos), Decimal("0"))
    if pago < Decimal(v.total_liquido):
        raise HTTPException(
            400,
            f"Pagamento insuficiente: pago={pago}, total={v.total_liquido}"
        )

    # 1) Verifica stock disponível em cada linha
    for ln in v.linhas:
        sr = await db.execute(
            select(StockSaldoModel)
            .where(StockSaldoModel.produto_id == ln.produto_id)
            .where(StockSaldoModel.armazem_id == v.armazem_id)
        )
        saldo = sr.scalar_one_or_none()
        disp = (Decimal(saldo.qtd_actual) - Decimal(saldo.qtd_reservada)) if saldo else Decimal("0")
        if disp < Decimal(ln.quantidade):
            raise HTTPException(
                409,
                f"Stock insuficiente para {ln.sku_snapshot}: "
                f"disponível={disp}, pedido={ln.quantidade}",
            )

    # 2) Dá baixa de stock — saida_venda por linha
    for ln in v.linhas:
        await stock_service.registar_movimento(
            db,
            company_id=current_user.company_id,
            produto_id=ln.produto_id,
            tipo="saida_venda",
            quantidade=Decimal(ln.quantidade),
            armazem_origem_id=v.armazem_id,
            documento_ref_tipo="venda",
            documento_ref_id=str(v.id),
            created_by=current_user.id,
        )

    # 3) Gera nº de proforma sequencial (idempotente)
    await _emitir_numero_proforma(db, company_id=current_user.company_id, venda=v)
    v.estado = "concluida"
    v.updated_at = datetime.utcnow()

    await write_audit(
        db, current_user.id, current_user.company_id,
        "venda_concluir", "venda", v.id,
        dados_novos={"numero_proforma": v.numero_proforma,
                     "total": str(v.total_liquido)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _load_venda(db, v.id, current_user.company_id)


@router.post("/vendas/{id}/anular", response_model=VendaResponseDTO)
async def anular_venda(
    id: UUID, req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    v = await _load_venda(db, id, current_user.company_id)
    if v.estado == "anulada":
        return v
    if v.estado == "concluida":
        # Estornar baixa de stock
        for ln in v.linhas:
            await stock_service.registar_movimento(
                db,
                company_id=current_user.company_id,
                produto_id=ln.produto_id,
                tipo="entrada_ajuste",
                quantidade=Decimal(ln.quantidade),
                armazem_destino_id=v.armazem_id,
                motivo=f"Anulação de venda {v.numero_proforma or v.id}",
                created_by=current_user.id,
            )
    v.estado = "anulada"
    v.updated_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "venda_anular", "venda", v.id,
        dados_novos={"motivo": "anulacao manual"},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _load_venda(db, v.id, current_user.company_id)


@router.get("/vendas", response_model=List[VendaResponseDTO])
async def list_vendas(
    estado: Optional[str] = None,
    sessao_id: Optional[UUID] = None,
    pendente_faturacao: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(VendaModel)
        .where(VendaModel.company_id == current_user.company_id)
        .options(selectinload(VendaModel.linhas),
                 selectinload(VendaModel.pagamentos))
    )
    if estado:
        stmt = stmt.where(VendaModel.estado == estado)
    if sessao_id:
        stmt = stmt.where(VendaModel.sessao_id == sessao_id)
    if pendente_faturacao:
        stmt = stmt.where(VendaModel.estado == "concluida") \
                   .where(VendaModel.numero_fatura_interna.is_(None))
    stmt = stmt.order_by(VendaModel.data.desc()) \
               .offset((page - 1) * page_size).limit(page_size)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.get("/vendas/{id}", response_model=VendaResponseDTO)
async def get_venda(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load_venda(db, id, current_user.company_id)


@router.get("/vendas/{id}/proforma.pdf")
async def proforma_pdf(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    v = await _load_venda(db, id, current_user.company_id)
    # Nomes opcionais (armazém + cliente)
    armazem_nome = None
    if v.armazem_id:
        ar = await db.execute(select(ArmazemModel).where(ArmazemModel.id == v.armazem_id))
        a = ar.scalar_one_or_none()
        armazem_nome = a.nome if a else None
    pdf = gerar_proforma_pdf(v, armazem_nome=armazem_nome)
    fname = f"proforma-{v.numero_proforma or v.id}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


# ─── Faturação interna ────────────────────────────────────────────────


class MarcarFaturadaDTO(BaseModel):
    numero_fatura_interna: str = Field(..., min_length=1, max_length=50)


@router.post("/vendas/{id}/marcar-faturada", response_model=VendaResponseDTO)
async def marcar_faturada(
    id: UUID, req: Request, body: MarcarFaturadaDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regista o nº de fatura interna emitida para a venda concluída —
    faturação própria da aplicação, sem depender de ERP externo."""
    v = await _load_venda(db, id, current_user.company_id)
    if v.estado != "concluida":
        raise HTTPException(409, "Só vendas concluídas podem ser faturadas")
    if v.numero_fatura_interna:
        raise HTTPException(409, f"Venda já faturada com nº {v.numero_fatura_interna}")
    v.numero_fatura_interna = body.numero_fatura_interna
    v.faturada_em = datetime.utcnow()
    v.faturada_por = current_user.id
    await write_audit(
        db, current_user.id, current_user.company_id,
        "venda_marcar_faturada", "venda", v.id,
        dados_novos={"numero_fatura_interna": body.numero_fatura_interna},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _load_venda(db, v.id, current_user.company_id)


__all__ = ["router"]
