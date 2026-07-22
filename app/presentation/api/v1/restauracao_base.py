"""Base Comum de Restauração: Mesas, Itens de Menu, Comandas, Reservas.

Reutilizada pelos três sub-negócios (Bar, Restaurante, Churrasqueira).
Fechar comanda gera Venda (reaproveita entidade já usada pelo POS) e
StockMovimento de saída por ingrediente via stock_service — nunca
abate stock directamente.
"""
from __future__ import annotations

import json
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
    ComandaLinhaModel,
    ComandaModel,
    ItemMenuModel,
    MesaModel,
    VendaLinhaModel,
    VendaModel,
)


router = APIRouter()


# ─── Mesas ───────────────────────────────────────────────────────────


class MesaCreateDTO(BaseModel):
    area_servico_id: Optional[UUID] = None
    numero: str = Field(..., min_length=1, max_length=10)
    capacidade: int = Field(default=4, gt=0)


class MesaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    area_servico_id: Optional[UUID] = None
    numero: str
    capacidade: int
    estado: str

    class Config:
        from_attributes = True


@router.get("/mesas", response_model=List[MesaResponseDTO])
async def list_mesas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    r = await db.execute(
        select(MesaModel)
        .where(MesaModel.company_id == current_user.company_id)
        .where(MesaModel.deleted_at.is_(None))
    )
    return list(r.scalars().all())


@router.post("/mesas", response_model=MesaResponseDTO, status_code=201)
async def create_mesa(
    body: MesaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_menu")),
):
    m = MesaModel(id=uuid4(), company_id=current_user.company_id, estado="livre", **body.model_dump())
    db.add(m)
    await db.commit()
    return m


@router.delete("/mesas/{id}", status_code=204)
async def delete_mesa(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_menu")),
):
    r = await db.execute(select(MesaModel).where(MesaModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Mesa não encontrada")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Itens de Menu ───────────────────────────────────────────────────


class ItemMenuCreateDTO(BaseModel):
    tipo_negocio: str = Field(..., pattern="^(bar|restaurante|churrasqueira)$")
    nome: str = Field(..., min_length=1, max_length=150)
    descricao: Optional[str] = None
    preco: Decimal = Field(..., gt=0)
    categoria: Optional[str] = None
    ingredientes: List[dict] = Field(default_factory=list)  # [{produto_id, quantidade}]
    activo: bool = True


class ItemMenuResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    tipo_negocio: str
    nome: str
    descricao: Optional[str] = None
    preco: Decimal
    categoria: Optional[str] = None
    activo: bool
    ingredientes: List[dict] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, m: ItemMenuModel) -> "ItemMenuResponseDTO":
        return cls(
            id=m.id, company_id=m.company_id, tipo_negocio=m.tipo_negocio, nome=m.nome,
            descricao=m.descricao, preco=m.preco, categoria=m.categoria, activo=m.activo,
            ingredientes=json.loads(m.ingredientes) if m.ingredientes else [],
        )


@router.get("/itens-menu", response_model=List[ItemMenuResponseDTO])
async def list_itens_menu(
    tipo_negocio: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    stmt = (
        select(ItemMenuModel)
        .where(ItemMenuModel.company_id == current_user.company_id)
        .where(ItemMenuModel.deleted_at.is_(None))
    )
    if tipo_negocio:
        stmt = stmt.where(ItemMenuModel.tipo_negocio == tipo_negocio)
    r = await db.execute(stmt)
    return [ItemMenuResponseDTO.from_model(m) for m in r.scalars().all()]


@router.post("/itens-menu", response_model=ItemMenuResponseDTO, status_code=201)
async def create_item_menu(
    body: ItemMenuCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_menu")),
):
    m = ItemMenuModel(
        id=uuid4(), company_id=current_user.company_id, tipo_negocio=body.tipo_negocio,
        nome=body.nome, descricao=body.descricao, preco=body.preco, categoria=body.categoria,
        activo=body.activo, ingredientes=json.dumps(body.ingredientes),
    )
    db.add(m)
    await db.commit()
    return ItemMenuResponseDTO.from_model(m)


@router.delete("/itens-menu/{id}", status_code=204)
async def delete_item_menu(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.gerir_menu")),
):
    r = await db.execute(select(ItemMenuModel).where(ItemMenuModel.id == id))
    m = r.scalar_one_or_none()
    if not m or m.company_id != current_user.company_id:
        raise HTTPException(404, "Item de menu não encontrado")
    m.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Comandas ────────────────────────────────────────────────────────


class ComandaCreateDTO(BaseModel):
    mesa_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None


class ComandaLinhaCreateDTO(BaseModel):
    item_id: UUID
    quantidade: Decimal = Field(default=Decimal("1"), gt=0)
    observacoes: Optional[str] = None


class ComandaLinhaResponseDTO(BaseModel):
    id: UUID
    item_id: UUID
    nome_snapshot: str
    preco_snapshot: Decimal
    quantidade: Decimal
    observacoes: Optional[str] = None
    estado: str

    class Config:
        from_attributes = True


class ComandaResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    mesa_id: Optional[UUID] = None
    cliente_id: Optional[str] = None
    aberta_em: datetime
    fechada_em: Optional[datetime] = None
    estado: str
    venda_id: Optional[UUID] = None
    linhas: List[ComandaLinhaResponseDTO] = []

    class Config:
        from_attributes = True


async def _to_comanda_response(db: AsyncSession, c: ComandaModel) -> ComandaResponseDTO:
    lr = await db.execute(select(ComandaLinhaModel).where(ComandaLinhaModel.comanda_id == c.id))
    dto = ComandaResponseDTO.model_validate(c)
    dto.linhas = [ComandaLinhaResponseDTO.model_validate(l) for l in lr.scalars().all()]
    return dto


@router.get("/comandas", response_model=List[ComandaResponseDTO])
async def list_comandas(
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.view")),
):
    stmt = select(ComandaModel).where(ComandaModel.company_id == current_user.company_id)
    if estado:
        stmt = stmt.where(ComandaModel.estado == estado)
    stmt = stmt.order_by(ComandaModel.aberta_em.desc())
    r = await db.execute(stmt)
    return [await _to_comanda_response(db, c) for c in r.scalars().all()]


@router.post("/comandas", response_model=ComandaResponseDTO, status_code=201)
async def create_comanda(
    body: ComandaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_comanda")),
):
    c = ComandaModel(
        id=uuid4(), company_id=current_user.company_id, mesa_id=body.mesa_id,
        cliente_id=str(body.cliente_id) if body.cliente_id else None,
        garcom_id=current_user.id, estado="aberta",
    )
    db.add(c)
    if body.mesa_id:
        mr = await db.execute(select(MesaModel).where(MesaModel.id == body.mesa_id))
        mesa = mr.scalar_one_or_none()
        if mesa:
            mesa.estado = "ocupada"
    await db.flush()
    await db.commit()
    return await _to_comanda_response(db, c)


@router.post("/comandas/{id}/linhas", response_model=ComandaResponseDTO)
async def adicionar_linha(
    id: UUID,
    body: ComandaLinhaCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_comanda")),
):
    cr = await db.execute(select(ComandaModel).where(ComandaModel.id == id))
    comanda = cr.scalar_one_or_none()
    if not comanda or comanda.company_id != current_user.company_id:
        raise HTTPException(404, "Comanda não encontrada")
    if comanda.estado != "aberta":
        raise HTTPException(400, "Só é possível adicionar linhas a comandas abertas")

    ir = await db.execute(select(ItemMenuModel).where(ItemMenuModel.id == body.item_id))
    item = ir.scalar_one_or_none()
    if not item or not item.activo:
        raise HTTPException(404, "Item de menu não disponível")

    db.add(ComandaLinhaModel(
        id=uuid4(), comanda_id=comanda.id, item_id=item.id, nome_snapshot=item.nome,
        preco_snapshot=item.preco, quantidade=body.quantidade, observacoes=body.observacoes, estado="pedido",
    ))
    await db.commit()
    return await _to_comanda_response(db, comanda)


class MudarEstadoLinhaDTO(BaseModel):
    estado: str = Field(..., pattern="^(em_preparacao|pronto|entregue|cancelado)$")


@router.patch("/comandas/{id}/linhas/{lid}", response_model=ComandaResponseDTO)
async def mudar_estado_linha(
    id: UUID,
    lid: UUID,
    body: MudarEstadoLinhaDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_comanda")),
):
    cr = await db.execute(select(ComandaModel).where(ComandaModel.id == id))
    comanda = cr.scalar_one_or_none()
    if not comanda or comanda.company_id != current_user.company_id:
        raise HTTPException(404, "Comanda não encontrada")
    lr = await db.execute(select(ComandaLinhaModel).where(ComandaLinhaModel.id == lid))
    linha = lr.scalar_one_or_none()
    if not linha or linha.comanda_id != comanda.id:
        raise HTTPException(404, "Linha não encontrada")
    linha.estado = body.estado
    await db.commit()
    return await _to_comanda_response(db, comanda)


@router.delete("/comandas/{id}/linhas/{lid}", response_model=ComandaResponseDTO)
async def cancelar_linha(
    id: UUID,
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_comanda")),
):
    cr = await db.execute(select(ComandaModel).where(ComandaModel.id == id))
    comanda = cr.scalar_one_or_none()
    if not comanda or comanda.company_id != current_user.company_id:
        raise HTTPException(404, "Comanda não encontrada")
    lr = await db.execute(select(ComandaLinhaModel).where(ComandaLinhaModel.id == lid))
    linha = lr.scalar_one_or_none()
    if not linha or linha.comanda_id != comanda.id:
        raise HTTPException(404, "Linha não encontrada")
    linha.estado = "cancelado"
    await db.commit()
    return await _to_comanda_response(db, comanda)


@router.post("/comandas/{id}/fechar", response_model=ComandaResponseDTO)
async def fechar_comanda(
    id: UUID,
    req: Request,
    armazem_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("restauracao.operar_comanda")),
):
    cr = await db.execute(select(ComandaModel).where(ComandaModel.id == id))
    comanda = cr.scalar_one_or_none()
    if not comanda or comanda.company_id != current_user.company_id:
        raise HTTPException(404, "Comanda não encontrada")
    if comanda.estado != "aberta":
        raise HTTPException(400, "Comanda já foi fechada")

    lr = await db.execute(
        select(ComandaLinhaModel)
        .where(ComandaLinhaModel.comanda_id == comanda.id)
        .where(ComandaLinhaModel.estado != "cancelado")
    )
    linhas = list(lr.scalars().all())
    if not linhas:
        raise HTTPException(400, "Comanda sem linhas válidas para fechar")

    venda = VendaModel(
        id=uuid4(), company_id=current_user.company_id,
        cliente_id=comanda.cliente_id, armazem_id=armazem_id,
        data=datetime.utcnow(), estado="rascunho", correlation_id=str(comanda.id),
        observacao=f"Comanda {comanda.id}", created_by=current_user.id,
    )
    db.add(venda)
    await db.flush()

    total_bruto = Decimal("0")
    for linha in linhas:
        subtotal = (Decimal(linha.preco_snapshot) * Decimal(linha.quantidade)).quantize(Decimal("0.01"))
        total_bruto += subtotal
        venda.linhas.append(VendaLinhaModel(
            id=uuid4(), produto_id=linha.item_id, sku_snapshot=str(linha.item_id)[:8],
            nome_snapshot=linha.nome_snapshot, quantidade=linha.quantidade,
            preco_unitario=linha.preco_snapshot, iva_pct=Decimal("0"),
            desconto_pct=Decimal("0"), subtotal=subtotal,
        ))

        ir = await db.execute(select(ItemMenuModel).where(ItemMenuModel.id == linha.item_id))
        item = ir.scalar_one_or_none()
        if item and item.ingredientes:
            for ingrediente in json.loads(item.ingredientes):
                await stock_service.registar_movimento(
                    db, company_id=current_user.company_id,
                    produto_id=UUID(ingrediente["produto_id"]), tipo="saida_venda",
                    quantidade=Decimal(str(ingrediente["quantidade"])) * Decimal(linha.quantidade),
                    armazem_origem_id=armazem_id, created_by=current_user.id,
                    documento_ref_tipo="comanda", documento_ref_id=str(comanda.id),
                )

    venda.total_bruto = total_bruto
    venda.total_desconto = Decimal("0")
    venda.total_iva = Decimal("0")
    venda.total_liquido = total_bruto
    venda.estado = "concluida"
    venda.numero_proforma = f"COM-{datetime.utcnow().year}-{str(comanda.id)[:8].upper()}"

    comanda.venda_id = venda.id
    comanda.estado = "fechada"
    comanda.fechada_em = datetime.utcnow()
    if comanda.mesa_id:
        mr = await db.execute(select(MesaModel).where(MesaModel.id == comanda.mesa_id))
        mesa = mr.scalar_one_or_none()
        if mesa:
            mesa.estado = "limpeza"

    await write_audit(
        db, current_user.id, current_user.company_id,
        "fechada", "comanda", comanda.id,
        dados_novos={"venda_id": str(venda.id), "total": str(total_bruto)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_comanda_response(db, comanda)


__all__ = ["router"]
