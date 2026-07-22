"""Inventários (contagem física de stock) — domínio Supply Chain.

Fluxo: rascunho -> iniciar (snapshot de qtd_sistema) -> registar linhas
(qtd_contada) -> concluir (gera StockMovimento de ajuste por divergência,
via app.domain.services.stock_service, respeitando as invariantes já
validadas para Estoque).
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
    InventarioLinhaModel,
    InventarioModel,
    ProdutoModel,
    StockSaldoModel,
)


router = APIRouter()


# ─── DTOs ────────────────────────────────────────────────────────────


class InventarioCreateDTO(BaseModel):
    armazem_id: UUID


class InventarioResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    armazem_id: UUID
    data_inicio: Optional[datetime] = None
    data_fim: Optional[datetime] = None
    estado: str
    responsavel_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InventarioLinhaContagemDTO(BaseModel):
    produto_id: UUID
    localizacao_id: Optional[UUID] = None
    quantidade_contada: Decimal = Field(..., ge=0)


class InventarioLinhaResponseDTO(BaseModel):
    id: UUID
    inventario_id: UUID
    produto_id: UUID
    localizacao_id: Optional[UUID] = None
    quantidade_sistema: Decimal
    quantidade_contada: Optional[Decimal] = None
    divergencia: Optional[Decimal] = None
    contado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


def _to_linha_dto(l: InventarioLinhaModel) -> InventarioLinhaResponseDTO:
    div = None
    if l.quantidade_contada is not None:
        div = Decimal(l.quantidade_contada) - Decimal(l.quantidade_sistema)
    return InventarioLinhaResponseDTO(
        id=l.id, inventario_id=l.inventario_id, produto_id=l.produto_id,
        localizacao_id=l.localizacao_id,
        quantidade_sistema=Decimal(l.quantidade_sistema),
        quantidade_contada=Decimal(l.quantidade_contada) if l.quantidade_contada is not None else None,
        divergencia=div, contado_em=l.contado_em,
    )


# ─── Endpoints ───────────────────────────────────────────────────────


@router.get("", response_model=List[InventarioResponseDTO])
async def list_inventarios(
    armazem_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.ver")),
):
    stmt = select(InventarioModel).where(InventarioModel.company_id == current_user.company_id)
    if armazem_id:
        stmt = stmt.where(InventarioModel.armazem_id == armazem_id)
    if estado:
        stmt = stmt.where(InventarioModel.estado == estado)
    stmt = stmt.order_by(InventarioModel.created_at.desc())
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.post("", response_model=InventarioResponseDTO, status_code=201)
async def create_inventario(
    req: Request,
    body: InventarioCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.realizar_inventario")),
):
    arm = await db.execute(
        select(ArmazemModel)
        .where(ArmazemModel.id == body.armazem_id)
        .where(ArmazemModel.company_id == current_user.company_id)
        .where(ArmazemModel.deleted_at.is_(None))
    )
    if not arm.scalar_one_or_none():
        raise HTTPException(404, "Armazém não encontrado")

    inv = InventarioModel(
        id=uuid4(), company_id=current_user.company_id,
        armazem_id=body.armazem_id, estado="rascunho",
        responsavel_id=current_user.id,
    )
    db.add(inv)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "inventario", inv.id,
        dados_novos={"armazem_id": str(body.armazem_id)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return inv


@router.post("/{id}/iniciar", response_model=List[InventarioLinhaResponseDTO])
async def iniciar_inventario(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.realizar_inventario")),
):
    """Gera snapshot de quantidade_sistema para todos os produtos com
    saldo no armazém (mesmo zero), a partir do StockSaldoModel actual."""
    r = await db.execute(select(InventarioModel).where(InventarioModel.id == id))
    inv = r.scalar_one_or_none()
    if not inv or inv.company_id != current_user.company_id:
        raise HTTPException(404, "Inventário não encontrado")
    if inv.estado != "rascunho":
        raise HTTPException(400, "Inventário já foi iniciado")

    saldos_r = await db.execute(
        select(StockSaldoModel, ProdutoModel)
        .join(ProdutoModel, ProdutoModel.id == StockSaldoModel.produto_id)
        .where(StockSaldoModel.armazem_id == inv.armazem_id)
        .where(ProdutoModel.deleted_at.is_(None))
    )
    linhas: List[InventarioLinhaModel] = []
    for saldo, _prod in saldos_r.all():
        linha = InventarioLinhaModel(
            id=uuid4(), inventario_id=inv.id, produto_id=saldo.produto_id,
            quantidade_sistema=Decimal(saldo.qtd_actual),
        )
        db.add(linha)
        linhas.append(linha)

    inv.estado = "em_curso"
    inv.data_inicio = datetime.utcnow()
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "iniciado", "inventario", inv.id,
        dados_novos={"n_produtos": len(linhas)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return [_to_linha_dto(l) for l in linhas]


@router.get("/{id}/linhas", response_model=List[InventarioLinhaResponseDTO])
async def list_linhas(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.ver")),
):
    inv_r = await db.execute(select(InventarioModel).where(InventarioModel.id == id))
    inv = inv_r.scalar_one_or_none()
    if not inv or inv.company_id != current_user.company_id:
        raise HTTPException(404, "Inventário não encontrado")
    r = await db.execute(
        select(InventarioLinhaModel).where(InventarioLinhaModel.inventario_id == id)
    )
    return [_to_linha_dto(l) for l in r.scalars().all()]


@router.post("/{id}/linhas", response_model=InventarioLinhaResponseDTO)
async def registar_contagem(
    id: UUID,
    body: InventarioLinhaContagemDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.realizar_inventario")),
):
    inv_r = await db.execute(select(InventarioModel).where(InventarioModel.id == id))
    inv = inv_r.scalar_one_or_none()
    if not inv or inv.company_id != current_user.company_id:
        raise HTTPException(404, "Inventário não encontrado")
    if inv.estado != "em_curso":
        raise HTTPException(400, "Inventário não está em curso")

    r = await db.execute(
        select(InventarioLinhaModel)
        .where(InventarioLinhaModel.inventario_id == id)
        .where(InventarioLinhaModel.produto_id == body.produto_id)
    )
    linha = r.scalar_one_or_none()
    if not linha:
        # produto sem saldo prévio no armazém (snapshot = 0)
        linha = InventarioLinhaModel(
            id=uuid4(), inventario_id=id, produto_id=body.produto_id,
            quantidade_sistema=Decimal("0"),
        )
        db.add(linha)

    linha.localizacao_id = body.localizacao_id
    linha.quantidade_contada = body.quantidade_contada
    linha.contado_em = datetime.utcnow()
    linha.contado_por = current_user.id
    await db.flush()
    await db.commit()
    return _to_linha_dto(linha)


@router.post("/{id}/concluir", response_model=InventarioResponseDTO)
async def concluir_inventario(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("estoque.realizar_inventario")),
):
    """Gera StockMovimento de ajuste por cada linha divergente, respeitando
    as invariantes de app.domain.services.stock_service (motivo obrigatório
    em ajustes)."""
    inv_r = await db.execute(select(InventarioModel).where(InventarioModel.id == id))
    inv = inv_r.scalar_one_or_none()
    if not inv or inv.company_id != current_user.company_id:
        raise HTTPException(404, "Inventário não encontrado")
    if inv.estado != "em_curso":
        raise HTTPException(400, "Inventário não está em curso")

    linhas_r = await db.execute(
        select(InventarioLinhaModel).where(InventarioLinhaModel.inventario_id == id)
    )
    linhas = list(linhas_r.scalars().all())

    ajustes_gerados = 0
    for linha in linhas:
        if linha.quantidade_contada is None:
            raise HTTPException(400, f"Produto {linha.produto_id} ainda não foi contado")
        divergencia = Decimal(linha.quantidade_contada) - Decimal(linha.quantidade_sistema)
        if divergencia == 0:
            continue
        motivo = f"Ajuste de inventário #{inv.id}"
        if divergencia > 0:
            await stock_service.registar_movimento(
                db, company_id=current_user.company_id, produto_id=linha.produto_id,
                tipo="entrada_ajuste", quantidade=divergencia,
                armazem_destino_id=inv.armazem_id, motivo=motivo,
                created_by=current_user.id,
                documento_ref_tipo="inventario", documento_ref_id=str(inv.id),
            )
        else:
            await stock_service.registar_movimento(
                db, company_id=current_user.company_id, produto_id=linha.produto_id,
                tipo="saida_ajuste", quantidade=abs(divergencia),
                armazem_origem_id=inv.armazem_id, motivo=motivo,
                created_by=current_user.id, permitir_negativo=True,
                documento_ref_tipo="inventario", documento_ref_id=str(inv.id),
            )
        ajustes_gerados += 1

    inv.estado = "concluido"
    inv.data_fim = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "concluido", "inventario", inv.id,
        dados_novos={"ajustes_gerados": ajustes_gerados},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return inv


__all__ = ["router"]
