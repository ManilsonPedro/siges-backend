"""BI Avançado — Operações/Lavagem: produtividade granular, rankings
semanais e alertas operacionais.

Complementa bi.py::dashboard_operacional (KPIs do dia) e
bi_lavagem_avancado.py (heatmap/LTV/cross-selling) com os cortes pedidos
na proposta de evolução do Dashboard Executivo: produtividade por
hora/box/equipa/turno, ranking semanal (vs. o ranking histórico já
existente) e alertas operacionais no mesmo padrão simples usado em
Água/Stock (sem motor de regras genérico).
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
    BoxLavagemModel,
    ClienteModel,
    EquipaLavagemModel,
    EquipaMembroModel,
    ExtraLavagemModel,
    OrdemLavagemExtraModel,
    OrdemLavagemModel,
    TipoLavagemModel,
    TurnoOperacionalModel,
    UserModel,
)

router = APIRouter()


def _hora_para_minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _turno_de(hora_atual_min: int, turnos: list[TurnoOperacionalModel]) -> Optional[TurnoOperacionalModel]:
    for t in turnos:
        ini = _hora_para_minutos(t.hora_inicio)
        fim = _hora_para_minutos(t.hora_fim)
        if ini <= fim:
            if ini <= hora_atual_min < fim:
                return t
        else:  # turno atravessa a meia-noite
            if hora_atual_min >= ini or hora_atual_min < fim:
                return t
    return None


@router.get("/lavagem/produtividade-por-hora")
async def produtividade_por_hora(
    dias: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Nº de lavagens concluídas por hora do dia (0-23), média sobre os
    últimos `dias` dias — identifica os horários de pico de conclusão."""
    desde = datetime.utcnow() - timedelta(days=dias)
    r = await db.execute(
        select(OrdemLavagemModel.concluido_em)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.concluido_em.isnot(None))
        .where(OrdemLavagemModel.concluido_em >= desde)
    )
    contagem = [0] * 24
    for (concluido,) in r.all():
        contagem[concluido.hour] += 1

    return {
        "periodo_dias": dias,
        "horas": [{"hora": h, "n_lavagens": n} for h, n in enumerate(contagem)],
    }


@router.get("/lavagem/produtividade-por-box")
async def produtividade_por_box(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Lavagens concluídas, receita e tempo médio de atendimento por box —
    sobre o histórico completo (todas as ordens concluídas com box_id)."""
    br = await db.execute(
        select(BoxLavagemModel)
        .where(BoxLavagemModel.company_id == current_user.company_id)
        .where(BoxLavagemModel.deleted_at.is_(None))
    )
    boxes = list(br.scalars().all())
    if not boxes:
        return {"boxes": []}

    or_ = await db.execute(
        select(
            OrdemLavagemModel.box_id, OrdemLavagemModel.preco_total_snapshot,
            OrdemLavagemModel.checkin_em, OrdemLavagemModel.concluido_em,
        )
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.box_id.isnot(None))
    )
    por_box: dict = {b.id: {"n": 0, "receita": Decimal("0"), "tempos": []} for b in boxes}
    for box_id, preco, checkin, concluido in or_.all():
        d = por_box.get(box_id)
        if d is None:
            continue
        d["n"] += 1
        if preco is not None:
            d["receita"] += Decimal(preco)
        if checkin and concluido:
            d["tempos"].append((concluido - checkin).total_seconds() / 60)

    resultado = [
        {
            "box_id": str(b.id), "box_codigo": b.codigo, "box_nome": b.nome,
            "n_lavagens": por_box[b.id]["n"],
            "receita": float(por_box[b.id]["receita"]),
            "tempo_medio_minutos": (
                round(sum(por_box[b.id]["tempos"]) / len(por_box[b.id]["tempos"]), 1)
                if por_box[b.id]["tempos"] else None
            ),
        }
        for b in boxes
    ]
    resultado.sort(key=lambda x: x["n_lavagens"], reverse=True)
    return {"boxes": resultado}


@router.get("/lavagem/produtividade-por-equipa")
async def produtividade_por_equipa(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Lavagens/receita/tempo médio por equipa — agrupa OrdemLavagemModel.equipa
    (CSV de user_id atribuído pela escala) resolvendo o nome da equipa por
    correspondência exacta ao conjunto de membros de EquipaLavagemModel."""
    er = await db.execute(
        select(EquipaLavagemModel)
        .where(EquipaLavagemModel.company_id == current_user.company_id)
        .where(EquipaLavagemModel.deleted_at.is_(None))
    )
    equipas = list(er.scalars().all())

    mr = await db.execute(select(EquipaMembroModel))
    membros_por_equipa: dict = {}
    for row in mr.all():
        membros_por_equipa.setdefault(row.equipa_id, set()).add(str(row.user_id))

    # csv normalizado (frozenset ordenado) -> nome da equipa
    nome_por_membros = {
        frozenset(membros_por_equipa.get(e.id, set())): e.nome
        for e in equipas
        if membros_por_equipa.get(e.id)
    }

    or_ = await db.execute(
        select(
            OrdemLavagemModel.equipa, OrdemLavagemModel.preco_total_snapshot,
            OrdemLavagemModel.checkin_em, OrdemLavagemModel.concluido_em,
        )
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.equipa.isnot(None))
    )
    agregados: dict = {}
    for equipa_csv, preco, checkin, concluido in or_.all():
        membros = frozenset(uid for uid in equipa_csv.split(",") if uid)
        if not membros:
            continue
        nome = nome_por_membros.get(membros, "Equipa não identificada")
        d = agregados.setdefault(nome, {"n": 0, "receita": Decimal("0"), "tempos": []})
        d["n"] += 1
        if preco is not None:
            d["receita"] += Decimal(preco)
        if checkin and concluido:
            d["tempos"].append((concluido - checkin).total_seconds() / 60)

    resultado = [
        {
            "equipa_nome": nome,
            "n_lavagens": d["n"],
            "receita": float(d["receita"]),
            "tempo_medio_minutos": round(sum(d["tempos"]) / len(d["tempos"]), 1) if d["tempos"] else None,
        }
        for nome, d in agregados.items()
    ]
    resultado.sort(key=lambda x: x["n_lavagens"], reverse=True)
    return {"equipas": resultado}


@router.get("/lavagem/produtividade-por-turno")
async def produtividade_por_turno(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Lavagens/receita por turno operacional — classifica cada ordem pelo
    turno cuja janela horária (hora_inicio/hora_fim) contém o checkin_em."""
    tr = await db.execute(
        select(TurnoOperacionalModel)
        .where(TurnoOperacionalModel.company_id == current_user.company_id)
        .where(TurnoOperacionalModel.deleted_at.is_(None))
    )
    turnos = list(tr.scalars().all())
    if not turnos:
        return {"turnos": []}

    or_ = await db.execute(
        select(OrdemLavagemModel.checkin_em, OrdemLavagemModel.preco_total_snapshot)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.checkin_em.isnot(None))
    )
    agregados: dict = {t.id: {"n": 0, "receita": Decimal("0")} for t in turnos}
    for checkin, preco in or_.all():
        minutos = checkin.hour * 60 + checkin.minute
        turno = _turno_de(minutos, turnos)
        if not turno:
            continue
        agregados[turno.id]["n"] += 1
        if preco is not None:
            agregados[turno.id]["receita"] += Decimal(preco)

    resultado = [
        {"turno_id": str(t.id), "turno_nome": t.nome, "n_lavagens": agregados[t.id]["n"], "receita": float(agregados[t.id]["receita"])}
        for t in turnos
    ]
    resultado.sort(key=lambda x: x["n_lavagens"], reverse=True)
    return {"turnos": resultado}


@router.get("/lavagem/ranking-clientes-periodo")
async def ranking_clientes_periodo(
    periodo: str = "semana",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Top clientes por nº de lavagens concluídas, no período indicado
    (semana | mes) — distinto de lavagem_top_clientes (histórico completo,
    já em bi.py)."""
    if periodo not in ("semana", "mes"):
        periodo = "semana"
    desde = datetime.utcnow() - (timedelta(days=7) if periodo == "semana" else timedelta(days=30))

    r = await db.execute(
        select(OrdemLavagemModel.cliente_id)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.cliente_id.isnot(None))
        .where(OrdemLavagemModel.concluido_em >= desde)
    )
    contagem: dict = {}
    for (cliente_id,) in r.all():
        contagem[cliente_id] = contagem.get(cliente_id, 0) + 1
    if not contagem:
        return {"periodo": periodo, "clientes": []}

    cr = await db.execute(
        select(ClienteModel).where(ClienteModel.id.in_([UUID(cid) for cid in contagem]))
    )
    nomes = {str(c.id): c.nome for c in cr.scalars().all()}

    clientes = [
        {"cliente_id": cid, "cliente_nome": nomes.get(cid, "Cliente sem registo"), "n_lavagens": n}
        for cid, n in contagem.items()
    ]
    clientes.sort(key=lambda x: x["n_lavagens"], reverse=True)
    return {"periodo": periodo, "clientes": clientes[:20]}


@router.get("/lavagem/ranking-servicos")
async def ranking_servicos(
    ordenar_por: str = "quantidade",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Ranking de tipos de lavagem por quantidade ou por receita/rentabilidade
    (histórico completo de ordens concluídas)."""
    if ordenar_por not in ("quantidade", "receita"):
        ordenar_por = "quantidade"

    r = await db.execute(
        select(OrdemLavagemModel.tipo_lavagem_id, OrdemLavagemModel.preco_total_snapshot)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
    )
    agregados: dict = {}
    for tipo_id, preco in r.all():
        d = agregados.setdefault(tipo_id, {"n": 0, "receita": Decimal("0")})
        d["n"] += 1
        if preco is not None:
            d["receita"] += Decimal(preco)
    if not agregados:
        return {"ordenar_por": ordenar_por, "servicos": []}

    tr = await db.execute(
        select(TipoLavagemModel).where(TipoLavagemModel.company_id == current_user.company_id)
    )
    nomes = {t.id: t.nome for t in tr.scalars().all()}

    servicos = [
        {
            "tipo_lavagem_id": str(tid), "tipo_lavagem_nome": nomes.get(tid, "Serviço sem registo"),
            "n_lavagens": d["n"], "receita": float(d["receita"]),
            "receita_media": float((d["receita"] / d["n"]).quantize(Decimal("0.01"))) if d["n"] else 0.0,
        }
        for tid, d in agregados.items()
    ]
    chave = "n_lavagens" if ordenar_por == "quantidade" else "receita"
    servicos.sort(key=lambda x: x[chave], reverse=True)
    return {"ordenar_por": ordenar_por, "servicos": servicos}


_MINUTOS_BOX_PARADO = 45
_FACTOR_PRODUTIVIDADE_BAIXA = Decimal("0.7")


@router.get("/lavagem/alertas")
async def alertas_operacionais(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Alertas operacionais no mesmo padrão simples usado em Água/Stock —
    sem motor de regras genérico. Ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md."""
    agora = datetime.utcnow()
    alertas: list[dict] = []

    # Box com ordem em curso há mais que o limite, sem concluir
    or_ = await db.execute(
        select(OrdemLavagemModel, BoxLavagemModel.codigo)
        .join(BoxLavagemModel, OrdemLavagemModel.box_id == BoxLavagemModel.id)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["em_curso", "controlo_qualidade"]))
        .where(OrdemLavagemModel.iniciado_em.isnot(None))
    )
    for ordem, box_codigo in or_.all():
        minutos = (agora - ordem.iniciado_em).total_seconds() / 60
        if minutos > _MINUTOS_BOX_PARADO:
            alertas.append({
                "tipo": "box_demorado", "severidade": "alta",
                "mensagem": f"Box {box_codigo} com lavagem em curso há {int(minutos)} minutos",
                "ordem_id": str(ordem.id),
            })

    # Equipa com produtividade abaixo da média do dia (nº lavagens hoje)
    hoje_ini = datetime(agora.year, agora.month, agora.day)
    membros_r = await db.execute(select(EquipaMembroModel))
    membros_por_equipa: dict = {}
    for row in membros_r.all():
        membros_por_equipa.setdefault(row.equipa_id, set()).add(str(row.user_id))
    equipas_r = await db.execute(
        select(EquipaLavagemModel)
        .where(EquipaLavagemModel.company_id == current_user.company_id)
        .where(EquipaLavagemModel.deleted_at.is_(None))
    )
    equipas = list(equipas_r.scalars().all())
    nome_por_membros = {
        frozenset(membros_por_equipa.get(e.id, set())): e.nome
        for e in equipas if membros_por_equipa.get(e.id)
    }

    hoje_r = await db.execute(
        select(OrdemLavagemModel.equipa)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.concluido_em >= hoje_ini)
        .where(OrdemLavagemModel.equipa.isnot(None))
    )
    contagem_hoje: dict = {}
    for (equipa_csv,) in hoje_r.all():
        membros = frozenset(uid for uid in equipa_csv.split(",") if uid)
        nome = nome_por_membros.get(membros)
        if nome:
            contagem_hoje[nome] = contagem_hoje.get(nome, 0) + 1

    if len(contagem_hoje) > 1:
        media = sum(contagem_hoje.values()) / len(contagem_hoje)
        for nome, n in contagem_hoje.items():
            if Decimal(n) < Decimal(media) * _FACTOR_PRODUTIVIDADE_BAIXA:
                alertas.append({
                    "tipo": "produtividade_baixa", "severidade": "media",
                    "mensagem": f"{nome}: {n} lavagens hoje, abaixo da média das equipas ({media:.1f})",
                    "ordem_id": None,
                })

    # Lavagem acima do tempo esperado (tipo_lavagem.duracao_estimada_minutos)
    tipos_r = await db.execute(
        select(TipoLavagemModel).where(TipoLavagemModel.company_id == current_user.company_id)
    )
    duracao_por_tipo = {t.id: t.duracao_estimada_minutos for t in tipos_r.scalars().all()}
    ativas_r = await db.execute(
        select(OrdemLavagemModel)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado == "em_curso")
        .where(OrdemLavagemModel.iniciado_em.isnot(None))
    )
    for ordem in ativas_r.scalars().all():
        duracao_esperada = duracao_por_tipo.get(ordem.tipo_lavagem_id)
        if not duracao_esperada:
            continue
        minutos_decorridos = (agora - ordem.iniciado_em).total_seconds() / 60
        if minutos_decorridos > duracao_esperada * 1.5:
            alertas.append({
                "tipo": "lavagem_atrasada", "severidade": "media",
                "mensagem": f"Ordem em curso há {int(minutos_decorridos)} min, esperado {duracao_esperada} min",
                "ordem_id": str(ordem.id),
            })

    return {"alertas": alertas, "total": len(alertas)}


__all__ = ["router"]
