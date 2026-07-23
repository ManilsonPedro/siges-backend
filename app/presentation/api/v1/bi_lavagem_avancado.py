"""BI Avançado — Lavagem (Fase 6 do Dashboard Operacional).

Heatmap de movimento, valor por cliente/LTV e cross-selling — agregações
mais pesadas (múltiplos joins/loops), por isso mantidas fora do
dashboard principal (bi.py::dashboard_operacional), em endpoints
próprios chamados sob pedido. Ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md,
Fase 6.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    ClienteModel,
    ComandaModel,
    OrdemLavagemModel,
    VendaModel,
)

router = APIRouter()

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


@router.get("/lavagem/heatmap-movimento")
async def heatmap_movimento(
    dias: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Contagem de check-ins por hora do dia × dia da semana, nos últimos
    `dias` dias — identifica horários/dias de maior procura."""
    desde = datetime.utcnow() - timedelta(days=dias)
    r = await db.execute(
        select(OrdemLavagemModel.checkin_em)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.checkin_em.isnot(None))
        .where(OrdemLavagemModel.checkin_em >= desde)
    )
    celulas: dict[tuple[int, int], int] = {}
    for (checkin,) in r.all():
        chave = (checkin.weekday(), checkin.hour)
        celulas[chave] = celulas.get(chave, 0) + 1

    return {
        "periodo_dias": dias,
        "celulas": [
            {"dia_semana": DIAS_SEMANA[dia], "hora": hora, "n_checkins": n}
            for (dia, hora), n in sorted(celulas.items())
        ],
    }


@router.get("/lavagem/valor-por-cliente")
async def valor_por_cliente(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Valor médio por cliente (receita total / nº clientes distintos) e
    lifetime value por cliente (receita acumulada desde a primeira
    lavagem) — sobre ordens concluídas com preco_total_snapshot."""
    r = await db.execute(
        select(OrdemLavagemModel.cliente_id, OrdemLavagemModel.preco_total_snapshot, OrdemLavagemModel.concluido_em)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.cliente_id.isnot(None))
        .where(OrdemLavagemModel.preco_total_snapshot.isnot(None))
    )
    por_cliente: dict[str, dict] = {}
    for cliente_id, preco, concluido in r.all():
        d = por_cliente.setdefault(cliente_id, {"receita": Decimal("0"), "n_lavagens": 0, "primeira": concluido})
        d["receita"] += Decimal(preco)
        d["n_lavagens"] += 1
        if concluido and (d["primeira"] is None or concluido < d["primeira"]):
            d["primeira"] = concluido

    if not por_cliente:
        return {"valor_medio_por_cliente": 0.0, "clientes": []}

    nomes: dict[str, str] = {}
    cr = await db.execute(
        select(ClienteModel)
        .where(ClienteModel.company_id == current_user.company_id)
        .where(ClienteModel.id.in_([UUID(cid) for cid in por_cliente]))
    )
    nomes = {str(c.id): c.nome for c in cr.scalars().all()}

    receita_total = sum((d["receita"] for d in por_cliente.values()), Decimal("0"))
    valor_medio = receita_total / len(por_cliente)

    clientes = [
        {
            "cliente_id": cid,
            "cliente_nome": nomes.get(cid, "Cliente sem registo"),
            "lifetime_value": float(d["receita"]),
            "n_lavagens": d["n_lavagens"],
            "cliente_desde": d["primeira"].isoformat() if d["primeira"] else None,
        }
        for cid, d in por_cliente.items()
    ]
    clientes.sort(key=lambda x: x["lifetime_value"], reverse=True)

    return {
        "valor_medio_por_cliente": float(valor_medio.quantize(Decimal("0.01"))),
        "clientes": clientes[:20],
    }


@router.get("/lavagem/cross-selling")
async def cross_selling(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """De entre os clientes que fizeram pelo menos uma lavagem, quantos
    também compraram (Venda) ou consumiram (Comanda — bar/restaurante) no
    mesmo dia da lavagem — mede potencial de venda cruzada."""
    lr = await db.execute(
        select(OrdemLavagemModel.cliente_id, OrdemLavagemModel.concluido_em)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.cliente_id.isnot(None))
        .where(OrdemLavagemModel.concluido_em.isnot(None))
    )
    lavagens = [(cid, concluido.date()) for cid, concluido in lr.all()]
    clientes_lavagem = {cid for cid, _ in lavagens}

    if not clientes_lavagem:
        return {"clientes_com_lavagem": 0, "clientes_com_compra_cruzada": 0, "taxa_conversao_pct": 0.0}

    vr = await db.execute(
        select(VendaModel.cliente_id, VendaModel.data)
        .where(VendaModel.company_id == current_user.company_id)
        .where(VendaModel.estado == "concluida")
        .where(VendaModel.cliente_id.in_(clientes_lavagem))
    )
    vendas_por_dia = {(cid, data.date()) for cid, data in vr.all() if cid}

    comr = await db.execute(
        select(ComandaModel.cliente_id, ComandaModel.aberta_em)
        .where(ComandaModel.company_id == current_user.company_id)
        .where(ComandaModel.estado.in_(["fechada", "paga"]))
        .where(ComandaModel.cliente_id.in_(clientes_lavagem))
    )
    comandas_por_dia = {(cid, aberta.date()) for cid, aberta in comr.all() if cid}

    clientes_convertidos = {
        cid for cid, dia in lavagens
        if (cid, dia) in vendas_por_dia or (cid, dia) in comandas_por_dia
    }

    taxa = (len(clientes_convertidos) / len(clientes_lavagem) * 100) if clientes_lavagem else 0.0

    return {
        "clientes_com_lavagem": len(clientes_lavagem),
        "clientes_com_compra_cruzada": len(clientes_convertidos),
        "taxa_conversao_pct": round(taxa, 2),
    }


__all__ = ["router"]
