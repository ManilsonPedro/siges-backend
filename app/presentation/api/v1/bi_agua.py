"""BI — Gestão da Água (Fase 10 do módulo de Gestão de Recursos Hídricos).

KPIs, evolução de consumo/custos e rankings (fornecedores, filiais).
Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fase 10.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    AbastecimentoAguaModel,
    ConsumoAguaModel,
    FilialModel,
    FornecedorModel,
    OrdemLavagemModel,
    TanqueAguaModel,
    TipoLavagemModel,
)

router = APIRouter()


@router.get("/agua/dashboard")
async def dashboard_agua(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    agora = datetime.utcnow()
    hoje_ini = datetime(agora.year, agora.month, agora.day)
    mes_ini = datetime(agora.year, agora.month, 1)

    tr = await db.execute(
        select(TanqueAguaModel)
        .where(TanqueAguaModel.company_id == current_user.company_id)
        .where(TanqueAguaModel.deleted_at.is_(None))
        .where(TanqueAguaModel.estado == "activo")
    )
    tanques = list(tr.scalars().all())
    agua_disponivel = sum((Decimal(t.nivel_atual_litros) for t in tanques), Decimal("0"))
    reciclada = sum((Decimal(t.nivel_atual_litros) for t in tanques if t.tipo in ("reciclada", "tratada")), Decimal("0"))
    pct_reutilizacao = (reciclada / agua_disponivel * 100) if agua_disponivel > 0 else Decimal("0")

    cr = await db.execute(
        select(ConsumoAguaModel).where(ConsumoAguaModel.company_id == current_user.company_id)
    )
    consumos = list(cr.scalars().all())
    consumida_hoje = sum((Decimal(c.litros_consumidos) for c in consumos if c.data >= hoje_ini), Decimal("0"))
    consumida_mes = sum((Decimal(c.litros_consumidos) for c in consumos if c.data >= mes_ini), Decimal("0"))
    custo_total_consumo = sum((Decimal(c.custo_total) for c in consumos if c.custo_total), Decimal("0"))

    ar = await db.execute(
        select(AbastecimentoAguaModel).where(AbastecimentoAguaModel.company_id == current_user.company_id)
    )
    abastecimentos = list(ar.scalars().all())
    valor_gasto_abastecimentos = sum((Decimal(a.custo_total) for a in abastecimentos), Decimal("0"))
    n_abastecimentos = len(abastecimentos)
    custo_medio_litro = (
        sum((Decimal(a.valor_por_litro) for a in abastecimentos), Decimal("0")) / n_abastecimentos
        if n_abastecimentos else Decimal("0")
    )

    lavagens_r = await db.execute(
        select(OrdemLavagemModel.id)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
    )
    n_lavagens = len(lavagens_r.all())
    consumo_lavagem = sum(
        (Decimal(c.litros_consumidos) for c in consumos if c.referencia_tipo == "ordem_lavagem"), Decimal("0")
    )
    custo_lavagem = sum(
        (Decimal(c.custo_total) for c in consumos if c.referencia_tipo == "ordem_lavagem" and c.custo_total),
        Decimal("0"),
    )
    custo_por_lavagem = (custo_lavagem / n_lavagens) if n_lavagens else Decimal("0")
    eficiencia_hidrica = (Decimal(consumo_lavagem) / n_lavagens) if n_lavagens else Decimal("0")

    return {
        "agua_disponivel_litros": float(agua_disponivel),
        "agua_consumida_hoje_litros": float(consumida_hoje),
        "agua_consumida_mes_litros": float(consumida_mes),
        "custo_total_agua": float(custo_total_consumo + valor_gasto_abastecimentos),
        "custo_medio_por_litro": float(custo_medio_litro.quantize(Decimal("0.0001"))),
        "custo_por_lavagem": float(custo_por_lavagem.quantize(Decimal("0.01"))),
        "eficiencia_hidrica_litros_por_lavagem": float(eficiencia_hidrica.quantize(Decimal("0.01"))),
        "percentual_reutilizacao": float(pct_reutilizacao.quantize(Decimal("0.01"))),
        "numero_abastecimentos": n_abastecimentos,
        "valor_gasto_abastecimentos": float(valor_gasto_abastecimentos),
    }


@router.get("/agua/evolucao-custos")
async def evolucao_custos_agua(
    meses: int = 6,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    desde = datetime.utcnow() - timedelta(days=meses * 31)
    r = await db.execute(
        select(AbastecimentoAguaModel.data, AbastecimentoAguaModel.custo_total)
        .where(AbastecimentoAguaModel.company_id == current_user.company_id)
        .where(AbastecimentoAguaModel.data >= desde)
    )
    por_mes: dict[str, Decimal] = {}
    for data, custo in r.all():
        chave = data.strftime("%Y-%m")
        por_mes[chave] = por_mes.get(chave, Decimal("0")) + Decimal(custo)

    return {
        "meses": [
            {"mes": chave, "custo_total": float(valor)}
            for chave, valor in sorted(por_mes.items())
        ]
    }


@router.get("/agua/consumo-por-servico")
async def consumo_por_servico(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Consumo de água agregado por tipo de lavagem (Lavagem Simples,
    Completa, Premium, etc.) — cruza ConsumoAguaModel via
    referencia_tipo='ordem_lavagem' com OrdemLavagemModel.tipo_lavagem_id."""
    cr = await db.execute(
        select(ConsumoAguaModel)
        .where(ConsumoAguaModel.company_id == current_user.company_id)
        .where(ConsumoAguaModel.referencia_tipo == "ordem_lavagem")
    )
    consumos = list(cr.scalars().all())
    if not consumos:
        return {"itens": []}

    ordens_r = await db.execute(
        select(OrdemLavagemModel.id, OrdemLavagemModel.tipo_lavagem_id)
        .where(OrdemLavagemModel.id.in_([c.referencia_id for c in consumos]))
    )
    tipo_por_ordem = {oid: tid for oid, tid in ordens_r.all()}

    tipos_r = await db.execute(
        select(TipoLavagemModel).where(TipoLavagemModel.company_id == current_user.company_id)
    )
    nomes_tipo = {t.id: t.nome for t in tipos_r.scalars().all()}

    agregados: dict[str, Decimal] = {}
    contagem: dict[str, int] = {}
    labels: dict[str, str] = {}
    for c in consumos:
        tipo_id = tipo_por_ordem.get(c.referencia_id)
        chave = str(tipo_id) if tipo_id else "sem_tipo"
        agregados[chave] = agregados.get(chave, Decimal("0")) + Decimal(c.litros_consumidos)
        contagem[chave] = contagem.get(chave, 0) + 1
        labels[chave] = nomes_tipo.get(tipo_id, "Sem tipo") if tipo_id else "Sem tipo"

    itens = [
        {
            "tipo_lavagem_id": None if chave == "sem_tipo" else chave,
            "tipo_lavagem_nome": labels[chave],
            "litros": float(litros), "n_lavagens": contagem[chave],
        }
        for chave, litros in agregados.items()
    ]
    itens.sort(key=lambda x: x["litros"], reverse=True)
    return {"itens": itens}


@router.get("/agua/ranking-fornecedores")
async def ranking_fornecedores_agua(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    r = await db.execute(
        select(AbastecimentoAguaModel).where(AbastecimentoAguaModel.company_id == current_user.company_id)
    )
    abastecimentos = list(r.scalars().all())
    if not abastecimentos:
        return {"fornecedores": []}

    por_fornecedor: dict[str, dict] = {}
    for a in abastecimentos:
        fid = str(a.fornecedor_id)
        d = por_fornecedor.setdefault(fid, {"quantidade": Decimal("0"), "faturacao": Decimal("0"), "n_abastecimentos": 0})
        d["quantidade"] += Decimal(a.quantidade_litros)
        d["faturacao"] += Decimal(a.custo_total)
        d["n_abastecimentos"] += 1

    fr = await db.execute(
        select(FornecedorModel).where(FornecedorModel.company_id == current_user.company_id)
    )
    nomes = {str(f.id): f.nome for f in fr.scalars().all()}

    fornecedores = [
        {
            "fornecedor_id": fid,
            "fornecedor_nome": nomes.get(fid, "Fornecedor sem registo"),
            "quantidade_total_litros": float(d["quantidade"]),
            "faturacao_total": float(d["faturacao"]),
            "preco_medio_litro": float((d["faturacao"] / d["quantidade"]).quantize(Decimal("0.0001"))) if d["quantidade"] else 0.0,
            "n_abastecimentos": d["n_abastecimentos"],
        }
        for fid, d in por_fornecedor.items()
    ]
    fornecedores.sort(key=lambda x: x["quantidade_total_litros"], reverse=True)
    return {"fornecedores": fornecedores}


@router.get("/agua/ranking-filiais")
async def ranking_filiais_agua(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    fr = await db.execute(
        select(FilialModel)
        .where(FilialModel.company_id == current_user.company_id)
        .where(FilialModel.deleted_at.is_(None))
    )
    filiais = list(fr.scalars().all())
    if not filiais:
        return {"filiais": []}

    cr = await db.execute(
        select(ConsumoAguaModel.tanque_agua_id, ConsumoAguaModel.litros_consumidos)
        .where(ConsumoAguaModel.company_id == current_user.company_id)
    )
    consumos = list(cr.all())

    tr = await db.execute(
        select(TanqueAguaModel.id, TanqueAguaModel.filial_id)
        .where(TanqueAguaModel.company_id == current_user.company_id)
    )
    filial_por_tanque = {tid: fid for tid, fid in tr.all()}

    por_filial: dict = {f.id: Decimal("0") for f in filiais}
    for tanque_id, litros in consumos:
        filial_id = filial_por_tanque.get(tanque_id)
        if filial_id and filial_id in por_filial:
            por_filial[filial_id] += Decimal(litros)

    filiais_out = [
        {"filial_id": str(f.id), "filial_nome": f.nome, "consumo_total_litros": float(por_filial[f.id])}
        for f in filiais
    ]
    filiais_out.sort(key=lambda x: x["consumo_total_litros"], reverse=True)
    return {"filiais": filiais_out}


__all__ = ["router"]
