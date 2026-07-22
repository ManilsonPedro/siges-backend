"""E-Commerce — loja online (domínio Comércio).

Checkout nunca confia em preço vindo do cliente: preço é sempre
recalculado servidor-side a partir do produto_id no momento da
criação do pedido. Ao confirmar pagamento, gera-se uma VendaModel
(reaproveitando a entidade de venda já usada pelo Caixa) e um
StockMovimento de saida_venda por linha, via stock_service — nunca
directamente em StockSaldoModel.
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
from app.domain.services import stock_service
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import get_current_user, require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    ArmazemModel,
    CupaoModel,
    LojaOnlineConfigModel,
    PedidoOnlineLinhaModel,
    PedidoOnlineModel,
    ProdutoModel,
    StockSaldoModel,
    VendaLinhaModel,
    VendaModel,
)


router = APIRouter()


# ─── Config ──────────────────────────────────────────────────────────


class ConfigUpdateDTO(BaseModel):
    dominio: Optional[str] = None
    tema: Optional[str] = None
    activo: Optional[bool] = None
    metodos_entrega: Optional[List[str]] = None
    moeda: Optional[str] = None


class ConfigResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    dominio: Optional[str] = None
    tema: str
    activo: bool
    metodos_entrega: List[str]
    moeda: str
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, m: LojaOnlineConfigModel) -> "ConfigResponseDTO":
        return cls(
            id=m.id, company_id=m.company_id, dominio=m.dominio, tema=m.tema,
            activo=m.activo, metodos_entrega=m.metodos_entrega.split(","),
            moeda=m.moeda, updated_at=m.updated_at,
        )


@router.get("/config", response_model=ConfigResponseDTO)
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.view")),
):
    r = await db.execute(select(LojaOnlineConfigModel).where(LojaOnlineConfigModel.company_id == current_user.company_id))
    cfg = r.scalar_one_or_none()
    if not cfg:
        cfg = LojaOnlineConfigModel(id=uuid4(), company_id=current_user.company_id)
        db.add(cfg)
        await db.flush()
        await db.commit()
    return ConfigResponseDTO.from_model(cfg)


@router.patch("/config", response_model=ConfigResponseDTO)
async def update_config(
    body: ConfigUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.gerir_config")),
):
    r = await db.execute(select(LojaOnlineConfigModel).where(LojaOnlineConfigModel.company_id == current_user.company_id))
    cfg = r.scalar_one_or_none()
    if not cfg:
        cfg = LojaOnlineConfigModel(id=uuid4(), company_id=current_user.company_id)
        db.add(cfg)
        await db.flush()

    if body.dominio is not None:
        cfg.dominio = body.dominio
    if body.tema is not None:
        cfg.tema = body.tema
    if body.activo is not None:
        cfg.activo = body.activo
    if body.metodos_entrega is not None:
        cfg.metodos_entrega = ",".join(body.metodos_entrega)
    if body.moeda is not None:
        cfg.moeda = body.moeda
    cfg.updated_at = datetime.utcnow()
    await db.commit()
    return ConfigResponseDTO.from_model(cfg)


# ─── Cupões ──────────────────────────────────────────────────────────


class CupaoCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=30)
    tipo: str = Field(..., pattern="^(percentual|valor_fixo)$")
    valor: Decimal = Field(..., gt=0)
    validade: datetime
    uso_maximo: int = Field(default=1, ge=1)
    activo: bool = True


class CupaoUpdateDTO(BaseModel):
    valor: Optional[Decimal] = Field(None, gt=0)
    validade: Optional[datetime] = None
    uso_maximo: Optional[int] = Field(None, ge=1)
    activo: Optional[bool] = None


class CupaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    codigo: str
    tipo: str
    valor: Decimal
    validade: datetime
    uso_maximo: int
    uso_atual: int
    activo: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/cupoes", response_model=List[CupaoResponseDTO])
async def list_cupoes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.view")),
):
    r = await db.execute(
        select(CupaoModel)
        .where(CupaoModel.company_id == current_user.company_id)
        .where(CupaoModel.deleted_at.is_(None))
        .order_by(CupaoModel.created_at.desc())
    )
    return list(r.scalars().all())


@router.post("/cupoes", response_model=CupaoResponseDTO, status_code=201)
async def create_cupao(
    req: Request,
    body: CupaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.gerir_cupoes")),
):
    clash = await db.execute(
        select(CupaoModel)
        .where(CupaoModel.company_id == current_user.company_id)
        .where(CupaoModel.codigo == body.codigo)
        .where(CupaoModel.deleted_at.is_(None))
    )
    if clash.scalar_one_or_none():
        raise HTTPException(409, f"Já existe cupão com código '{body.codigo}'")

    m = CupaoModel(
        id=uuid4(), company_id=current_user.company_id, codigo=body.codigo,
        tipo=body.tipo, valor=body.valor, validade=body.validade,
        uso_maximo=body.uso_maximo, activo=body.activo,
    )
    db.add(m)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "cupao", m.id, dados_novos={"codigo": body.codigo},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return m


@router.patch("/cupoes/{id}", response_model=CupaoResponseDTO)
async def update_cupao(
    id: UUID,
    body: CupaoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.gerir_cupoes")),
):
    r = await db.execute(select(CupaoModel).where(CupaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id or m.deleted_at is not None:
        raise HTTPException(404, "Cupão não encontrado")
    if body.valor is not None:
        m.valor = body.valor
    if body.validade is not None:
        m.validade = body.validade
    if body.uso_maximo is not None:
        m.uso_maximo = body.uso_maximo
    if body.activo is not None:
        m.activo = body.activo
    await db.commit()
    return m


@router.delete("/cupoes/{id}", status_code=204)
async def delete_cupao(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.gerir_cupoes")),
):
    r = await db.execute(select(CupaoModel).where(CupaoModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Cupão não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


@router.get("/cupoes/validar")
async def validar_cupao(
    codigo: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(CupaoModel)
        .where(CupaoModel.company_id == current_user.company_id)
        .where(CupaoModel.codigo == codigo)
        .where(CupaoModel.deleted_at.is_(None))
    )
    c = r.scalar_one_or_none()
    if not c or not c.activo:
        return {"valido": False, "motivo": "Cupão inexistente ou inactivo"}
    if c.validade < datetime.utcnow():
        return {"valido": False, "motivo": "Cupão expirado"}
    if c.uso_atual >= c.uso_maximo:
        return {"valido": False, "motivo": "Cupão esgotado"}
    return {"valido": True, "cupao_id": str(c.id), "tipo": c.tipo, "valor": float(c.valor)}


# ─── Checkout / Pedidos ──────────────────────────────────────────────


class CheckoutLinhaDTO(BaseModel):
    produto_id: UUID
    quantidade: Decimal = Field(..., gt=0)


class CheckoutDTO(BaseModel):
    cliente_id: Optional[UUID] = None
    armazem_id: UUID
    linhas: List[CheckoutLinhaDTO] = Field(..., min_length=1)
    metodo_entrega: str = Field(..., pattern="^(delivery|click_collect)$")
    endereco_entrega: Optional[str] = None
    cupao_codigo: Optional[str] = None


class PedidoLinhaResponseDTO(BaseModel):
    id: UUID
    produto_id: UUID
    sku_snapshot: str
    nome_snapshot: str
    quantidade: Decimal
    preco_unitario: Decimal

    class Config:
        from_attributes = True


class PedidoOnlineResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    cliente_id: Optional[str] = None
    numero: str
    subtotal: Decimal
    desconto_cupao: Decimal
    total: Decimal
    metodo_entrega: str
    endereco_entrega: Optional[str] = None
    estado: str
    venda_id: Optional[UUID] = None
    linhas: List[PedidoLinhaResponseDTO] = []
    created_at: datetime

    class Config:
        from_attributes = True


async def _to_response(db: AsyncSession, p: PedidoOnlineModel) -> PedidoOnlineResponseDTO:
    lr = await db.execute(select(PedidoOnlineLinhaModel).where(PedidoOnlineLinhaModel.pedido_id == p.id))
    dto = PedidoOnlineResponseDTO.model_validate(p)
    dto.linhas = [PedidoLinhaResponseDTO.model_validate(l) for l in lr.scalars().all()]
    return dto


@router.post("/checkout", response_model=PedidoOnlineResponseDTO, status_code=201)
async def checkout(
    req: Request,
    body: CheckoutDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    arm_r = await db.execute(
        select(ArmazemModel)
        .where(ArmazemModel.id == body.armazem_id)
        .where(ArmazemModel.company_id == current_user.company_id)
        .where(ArmazemModel.deleted_at.is_(None))
    )
    if not arm_r.scalar_one_or_none():
        raise HTTPException(404, "Armazém não encontrado")
    if body.metodo_entrega == "delivery" and not body.endereco_entrega:
        raise HTTPException(400, "Endereço de entrega obrigatório para delivery")

    subtotal = Decimal("0")
    linhas_model: List[PedidoOnlineLinhaModel] = []
    for l in body.linhas:
        pr = await db.execute(
            select(ProdutoModel)
            .where(ProdutoModel.id == l.produto_id)
            .where(ProdutoModel.company_id == current_user.company_id)
            .where(ProdutoModel.deleted_at.is_(None))
        )
        prod = pr.scalar_one_or_none()
        if not prod or not prod.activo:
            raise HTTPException(404, f"Produto {l.produto_id} não disponível")

        sr = await db.execute(
            select(StockSaldoModel)
            .where(StockSaldoModel.produto_id == prod.id)
            .where(StockSaldoModel.armazem_id == body.armazem_id)
        )
        saldo = sr.scalar_one_or_none()
        disponivel = (Decimal(saldo.qtd_actual) - Decimal(saldo.qtd_reservada)) if saldo else Decimal("0")
        if disponivel < l.quantidade:
            raise HTTPException(409, f"Stock insuficiente para {prod.sku}: disponível={disponivel}, pedido={l.quantidade}")

        # Preço sempre recalculado servidor-side — nunca aceitar preço do cliente.
        preco = Decimal(prod.preco_base)
        subtotal += (preco * l.quantidade)
        linhas_model.append(PedidoOnlineLinhaModel(
            id=uuid4(), produto_id=prod.id, sku_snapshot=prod.sku, nome_snapshot=prod.nome,
            quantidade=l.quantidade, preco_unitario=preco,
        ))

    desconto = Decimal("0")
    cupao: Optional[CupaoModel] = None
    if body.cupao_codigo:
        cr = await db.execute(
            select(CupaoModel)
            .where(CupaoModel.company_id == current_user.company_id)
            .where(CupaoModel.codigo == body.cupao_codigo)
            .where(CupaoModel.deleted_at.is_(None))
        )
        cupao = cr.scalar_one_or_none()
        if not cupao or not cupao.activo or cupao.validade < datetime.utcnow() or cupao.uso_atual >= cupao.uso_maximo:
            raise HTTPException(400, "Cupão inválido, expirado ou esgotado")
        desconto = (subtotal * Decimal(cupao.valor) / Decimal("100")) if cupao.tipo == "percentual" else Decimal(cupao.valor)
        desconto = min(desconto, subtotal)

    total = (subtotal - desconto).quantize(Decimal("0.01"))
    numero = f"PED-{datetime.utcnow().year}-{str(uuid4())[:8].upper()}"

    pedido = PedidoOnlineModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        numero=numero, subtotal=subtotal.quantize(Decimal("0.01")),
        desconto_cupao=desconto.quantize(Decimal("0.01")), total=total,
        metodo_entrega=body.metodo_entrega, endereco_entrega=body.endereco_entrega,
        estado="pendente_pagamento", cupao_id=cupao.id if cupao else None,
        correlation_id=str(uuid4()), armazem_id=body.armazem_id,
    )
    db.add(pedido)
    await db.flush()
    for lm in linhas_model:
        lm.pedido_id = pedido.id
        db.add(lm)

    for l in body.linhas:
        await stock_service.reservar(
            db, produto_id=l.produto_id, armazem_id=body.armazem_id,
            quantidade=l.quantidade, company_id=current_user.company_id,
        )

    await write_audit(
        db, current_user.id, current_user.company_id,
        "checkout", "pedido_online", pedido.id,
        dados_novos={"numero": numero, "total": str(total)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, pedido)


@router.get("/pedidos", response_model=List[PedidoOnlineResponseDTO])
async def list_pedidos(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.view")),
):
    stmt = select(PedidoOnlineModel).where(PedidoOnlineModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(PedidoOnlineModel.estado == estado)
    stmt = stmt.order_by(PedidoOnlineModel.created_at.desc())
    r = await db.execute(stmt)
    return [await _to_response(db, p) for p in r.scalars().all()]


@router.get("/pedidos/{id}", response_model=PedidoOnlineResponseDTO)
async def get_pedido(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.view")),
):
    r = await db.execute(select(PedidoOnlineModel).where(PedidoOnlineModel.id == id))
    p = r.scalar_one_or_none()
    if not p or p.company_id != current_user.company_id:
        raise HTTPException(404, "Pedido não encontrado")
    return await _to_response(db, p)


ESTADOS_SEGUINTES = {
    "pendente_pagamento": {"pago", "cancelado"},
    "pago": {"em_preparacao", "cancelado"},
    "em_preparacao": {"pronto", "cancelado"},
    "pronto": {"em_entrega", "concluido", "cancelado"},
    "em_entrega": {"concluido", "cancelado"},
}


class AtualizarEstadoDTO(BaseModel):
    estado: str


@router.post("/pedidos/{id}/atualizar-estado", response_model=PedidoOnlineResponseDTO)
async def atualizar_estado(
    id: UUID,
    req: Request,
    body: AtualizarEstadoDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("ecommerce.processar_pedidos")),
):
    r = await db.execute(select(PedidoOnlineModel).where(PedidoOnlineModel.id == id))
    p = r.scalar_one_or_none()
    if not p or p.company_id != current_user.company_id:
        raise HTTPException(404, "Pedido não encontrado")

    permitidos = ESTADOS_SEGUINTES.get(p.estado, set())
    if body.estado not in permitidos:
        raise HTTPException(400, f"Transição inválida de '{p.estado}' para '{body.estado}'")

    if body.estado == "cancelado":
        lr = await db.execute(select(PedidoOnlineLinhaModel).where(PedidoOnlineLinhaModel.pedido_id == p.id))
        for l in lr.scalars().all():
            await stock_service.libertar(db, produto_id=l.produto_id, armazem_id=p.armazem_id, quantidade=Decimal(l.quantidade))

    if body.estado == "pago" and p.estado == "pendente_pagamento":
        # Confirmação de pagamento: gera Venda + StockMovimento saida_venda (idempotente por correlation_id).
        vr = await db.execute(select(VendaModel).where(VendaModel.correlation_id == p.correlation_id))
        venda_existente = vr.scalar_one_or_none()
        if not venda_existente:
            lr = await db.execute(select(PedidoOnlineLinhaModel).where(PedidoOnlineLinhaModel.pedido_id == p.id))
            linhas = list(lr.scalars().all())

            venda = VendaModel(
                id=uuid4(), company_id=current_user.company_id,
                cliente_id=p.cliente_id, armazem_id=p.armazem_id,
                data=datetime.utcnow(), estado="rascunho",
                correlation_id=p.correlation_id,
                observacao=f"Pedido online {p.numero}", created_by=current_user.id,
            )
            db.add(venda)
            await db.flush()

            total_bruto = Decimal("0")
            total_iva = Decimal("0")
            for l in linhas:
                pr = await db.execute(select(ProdutoModel).where(ProdutoModel.id == l.produto_id))
                prod = pr.scalar_one()
                bruto_linha = Decimal(l.preco_unitario) * Decimal(l.quantidade)
                iva_linha = (bruto_linha * Decimal(prod.iva_pct) / Decimal("100")).quantize(Decimal("0.01"))
                subtotal_linha = (bruto_linha + iva_linha).quantize(Decimal("0.01"))
                venda.linhas.append(VendaLinhaModel(
                    id=uuid4(), produto_id=l.produto_id, sku_snapshot=l.sku_snapshot,
                    nome_snapshot=l.nome_snapshot, quantidade=l.quantidade,
                    preco_unitario=l.preco_unitario, iva_pct=Decimal(prod.iva_pct),
                    desconto_pct=Decimal("0"), subtotal=subtotal_linha,
                ))
                total_bruto += bruto_linha
                total_iva += iva_linha
                await stock_service.libertar(db, produto_id=l.produto_id, armazem_id=p.armazem_id, quantidade=Decimal(l.quantidade))
                await stock_service.registar_movimento(
                    db, company_id=current_user.company_id, produto_id=l.produto_id,
                    tipo="saida_venda", quantidade=Decimal(l.quantidade),
                    armazem_origem_id=p.armazem_id, created_by=current_user.id,
                    documento_ref_tipo="pedido_online", documento_ref_id=str(p.id),
                )

            venda.total_bruto = total_bruto.quantize(Decimal("0.01"))
            venda.total_desconto = Decimal(p.desconto_cupao)
            venda.total_iva = total_iva.quantize(Decimal("0.01"))
            venda.total_liquido = Decimal(p.total)
            venda.estado = "concluida"
            venda.numero_proforma = p.numero
            p.venda_id = venda.id

            if p.cupao_id:
                cr = await db.execute(select(CupaoModel).where(CupaoModel.id == p.cupao_id))
                cupao = cr.scalar_one_or_none()
                if cupao:
                    cupao.uso_atual = int(cupao.uso_atual) + 1

    p.estado = body.estado
    p.updated_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizar_estado", "pedido_online", p.id,
        dados_novos={"novo_estado": body.estado},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, p)


__all__ = ["router"]
