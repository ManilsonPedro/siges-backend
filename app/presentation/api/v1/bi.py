"""BI & Analytics (domínio Inteligência Empresarial) — camada de
agregação sobre dados reais de todos os domínios. Nenhum endpoint aqui
inventa dados: se o domínio de origem ainda não tiver dados reais, a
métrica correspondente devolve zero/vazio, nunca um valor fixo.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    BoxLavagemModel,
    CategoriaVeiculoModel,
    ClienteModel,
    ColaboradorModel,
    ConsumoAguaModel,
    ControloQualidadeLavagemModel,
    ExtraLavagemModel,
    FaltaModel,
    FeriasModel,
    FundoModel,
    MovimentoFinanceiroModel,
    OrdemLavagemExtraModel,
    OrdemLavagemModel,
    PedidoOnlineModel,
    ProdutoModel,
    StockSaldoModel,
    ViaturaModel,
    VendaLinhaModel,
    VendaModel,
)


router = APIRouter()


@router.get("/dashboards/financeiro")
async def dashboard_financeiro(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    fr = await db.execute(select(FundoModel).where(FundoModel.company_id == current_user.company_id))
    fundos = list(fr.scalars().all())

    inicio_mes = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    mr = await db.execute(
        select(MovimentoFinanceiroModel)
        .where(and_(
            MovimentoFinanceiroModel.company_id == current_user.company_id,
            MovimentoFinanceiroModel.deleted_at.is_(None),
            MovimentoFinanceiroModel.data >= inicio_mes,
        ))
    )
    movimentos_mes = list(mr.scalars().all())
    entradas = sum((Decimal(m.valor) for m in movimentos_mes if m.tipo_movimento == "entrada"), Decimal("0"))
    saidas = sum((Decimal(m.valor) for m in movimentos_mes if m.tipo_movimento == "saida"), Decimal("0"))

    return {
        "saldos_fundos": [{"tipo": f.tipo, "saldo_atual": float(f.saldo_atual)} for f in fundos],
        "movimentos_mes": {"entradas": float(entradas), "saidas": float(saidas), "liquido": float(entradas - saidas)},
    }


@router.get("/dashboards/comercial")
async def dashboard_comercial(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    hoje = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    vr = await db.execute(
        select(VendaModel)
        .where(and_(
            VendaModel.company_id == current_user.company_id,
            VendaModel.estado == "concluida",
            VendaModel.data >= hoje,
        ))
    )
    vendas_hoje = list(vr.scalars().all())
    total_vendido_hoje = sum((Decimal(v.total_liquido) for v in vendas_hoje), Decimal("0"))
    ticket_medio = (total_vendido_hoje / len(vendas_hoje)) if vendas_hoje else Decimal("0")

    lr = await db.execute(
        select(VendaLinhaModel.produto_id, VendaLinhaModel.nome_snapshot)
        .join(VendaModel, VendaModel.id == VendaLinhaModel.venda_id)
        .where(VendaModel.company_id == current_user.company_id)
        .where(VendaModel.estado == "concluida")
    )
    contagem: dict[str, int] = {}
    nomes: dict[str, str] = {}
    for produto_id, nome in lr.all():
        chave = str(produto_id)
        contagem[chave] = contagem.get(chave, 0) + 1
        nomes[chave] = nome
    top_produtos = sorted(contagem.items(), key=lambda x: x[1], reverse=True)[:5]

    pr = await db.execute(
        select(PedidoOnlineModel)
        .where(PedidoOnlineModel.company_id == current_user.company_id)
        .where(PedidoOnlineModel.estado.in_(["pendente_pagamento", "pago", "em_preparacao"]))
    )
    pedidos_pendentes = len(list(pr.scalars().all()))

    return {
        "vendas_hoje": {"total": float(total_vendido_hoje), "n_vendas": len(vendas_hoje), "ticket_medio": float(ticket_medio.quantize(Decimal("0.01")))},
        "top_produtos": [{"produto_id": k, "nome": nomes[k], "n_vendas": v} for k, v in top_produtos],
        "pedidos_ecommerce_pendentes": pedidos_pendentes,
    }


@router.get("/dashboards/operacional")
async def dashboard_operacional(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    lr = await db.execute(
        select(OrdemLavagemModel)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["checkin", "em_curso", "controlo_qualidade"]))
    )
    ordens_em_curso = len(list(lr.scalars().all()))

    # Lavagem: walk-ins vs. reservas hoje, ocupação de boxes, água por categoria (Sprint 6)
    hoje = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    lhr = await db.execute(
        select(OrdemLavagemModel)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.created_at >= hoje)
    )
    ordens_hoje = list(lhr.scalars().all())
    walkins_hoje = sum(1 for o in ordens_hoje if o.origem == "backoffice_walkin")
    reservas_hoje = sum(1 for o in ordens_hoje if o.origem in ("portal_cliente", "backoffice_telefone"))
    lavagens_hoje = len(ordens_hoje)
    agendadas_hoje = sum(1 for o in ordens_hoje if o.estado in ("agendada", "confirmada"))
    concluidas_hoje = sum(1 for o in ordens_hoje if o.estado in ("concluida", "paga"))

    # Top clientes por nº de lavagens concluídas (histórico completo, não só hoje)
    concl_r = await db.execute(
        select(OrdemLavagemModel)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
        .where(OrdemLavagemModel.estado.in_(["concluida", "paga"]))
        .where(OrdemLavagemModel.cliente_id.isnot(None))
    )
    contagem_cliente: dict[str, int] = {}
    for o in concl_r.scalars().all():
        contagem_cliente[o.cliente_id] = contagem_cliente.get(o.cliente_id, 0) + 1
    top_clientes_ids = sorted(contagem_cliente.items(), key=lambda x: x[1], reverse=True)[:5]
    nomes_clientes: dict[str, str] = {}
    if top_clientes_ids:
        cr = await db.execute(
            select(ClienteModel)
            .where(ClienteModel.company_id == current_user.company_id)
            .where(ClienteModel.id.in_([UUID(cid) for cid, _ in top_clientes_ids]))
        )
        nomes_clientes = {str(c.id): c.nome for c in cr.scalars().all()}
    top_clientes = [
        {"cliente_id": cid, "cliente_nome": nomes_clientes.get(cid, "Cliente sem registo"), "n_lavagens": n}
        for cid, n in top_clientes_ids
    ]

    # Avaliação média de qualidade (controlo de qualidade, todas as ordens da empresa)
    ordens_empresa_r = await db.execute(
        select(OrdemLavagemModel.id).where(OrdemLavagemModel.company_id == current_user.company_id)
    )
    ordem_ids = [row[0] for row in ordens_empresa_r.all()]
    avaliacao_media = 0.0
    if ordem_ids:
        cq_r = await db.execute(
            select(ControloQualidadeLavagemModel.pontuacao)
            .where(ControloQualidadeLavagemModel.ordem_lavagem_id.in_(ordem_ids))
        )
        pontuacoes = [float(p) for (p,) in cq_r.all()]
        if pontuacoes:
            avaliacao_media = sum(pontuacoes) / len(pontuacoes)

    # Cancelamentos hoje e taxa de retrabalho (re-lavagens oferecidas)
    cancelamentos_hoje = sum(1 for o in ordens_hoje if o.estado == "cancelada")

    todas_r = await db.execute(
        select(OrdemLavagemModel.estado, OrdemLavagemModel.re_lavagem_de_id)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
    )
    todas = todas_r.all()
    concluidas_total = sum(1 for estado, _ in todas if estado in ("concluida", "paga"))
    re_lavagens = sum(1 for _, re_id in todas if re_id is not None)
    taxa_retrabalho_pct = (re_lavagens / concluidas_total * 100) if concluidas_total else 0.0

    # Top extras mais vendidos (por contagem, todas as ordens da empresa)
    extras_r = await db.execute(
        select(OrdemLavagemExtraModel.extra_id)
        .join(OrdemLavagemModel, OrdemLavagemModel.id == OrdemLavagemExtraModel.ordem_lavagem_id)
        .where(OrdemLavagemModel.company_id == current_user.company_id)
    )
    contagem_extra: dict[UUID, int] = {}
    for (extra_id,) in extras_r.all():
        contagem_extra[extra_id] = contagem_extra.get(extra_id, 0) + 1
    top_extras_ids = sorted(contagem_extra.items(), key=lambda x: x[1], reverse=True)[:5]
    nomes_extras: dict[UUID, str] = {}
    if top_extras_ids:
        er = await db.execute(
            select(ExtraLavagemModel)
            .where(ExtraLavagemModel.company_id == current_user.company_id)
            .where(ExtraLavagemModel.id.in_([eid for eid, _ in top_extras_ids]))
        )
        nomes_extras = {e.id: e.nome for e in er.scalars().all()}
    top_extras = [
        {"extra_id": str(eid), "extra_nome": nomes_extras.get(eid, "Extra sem registo"), "n_vendas": n}
        for eid, n in top_extras_ids
    ]

    br = await db.execute(
        select(BoxLavagemModel)
        .where(BoxLavagemModel.company_id == current_user.company_id)
        .where(BoxLavagemModel.deleted_at.is_(None))
    )
    boxes = list(br.scalars().all())
    boxes_ocupados = sum(1 for b in boxes if b.estado == "ocupado")
    taxa_ocupacao_boxes_pct = (boxes_ocupados / len(boxes) * 100) if boxes else 0.0

    car_r = await db.execute(
        select(ConsumoAguaModel)
        .where(ConsumoAguaModel.company_id == current_user.company_id)
        .where(ConsumoAguaModel.referencia_tipo == "ordem_lavagem")
    )
    consumos_lavagem = list(car_r.scalars().all())
    agua_por_categoria: dict[str, float] = {}
    if consumos_lavagem:
        ordens_por_id = {
            o.id: o for o in (
                await db.execute(
                    select(OrdemLavagemModel)
                    .where(OrdemLavagemModel.id.in_([c.referencia_id for c in consumos_lavagem]))
                )
            ).scalars().all()
        }
        categorias_r = await db.execute(
            select(CategoriaVeiculoModel).where(CategoriaVeiculoModel.company_id == current_user.company_id)
        )
        categorias_por_id = {c.id: c.nome for c in categorias_r.scalars().all()}
        for consumo in consumos_lavagem:
            ordem = ordens_por_id.get(consumo.referencia_id)
            categoria_nome = "Sem categoria"
            if ordem and ordem.viatura_id:
                vr = await db.execute(select(ViaturaModel).where(ViaturaModel.id == UUID(ordem.viatura_id)))
                viatura = vr.scalar_one_or_none()
                if viatura and viatura.categoria_veiculo_id:
                    categoria_nome = categorias_por_id.get(viatura.categoria_veiculo_id, "Sem categoria")
            agua_por_categoria[categoria_nome] = agua_por_categoria.get(categoria_nome, 0.0) + float(consumo.litros_consumidos)

    return {
        "ordens_lavagem_em_curso": ordens_em_curso,
        "lavagem_walkins_hoje": walkins_hoje,
        "lavagem_reservas_hoje": reservas_hoje,
        "lavagem_taxa_ocupacao_boxes_pct": round(taxa_ocupacao_boxes_pct, 2),
        "lavagem_agua_por_categoria_litros": agua_por_categoria,
        "lavagem_hoje": lavagens_hoje,
        "lavagem_agendadas_hoje": agendadas_hoje,
        "lavagem_concluidas_hoje": concluidas_hoje,
        "lavagem_top_clientes": top_clientes,
        "lavagem_avaliacao_media": round(avaliacao_media, 2),
        "lavagem_cancelamentos_hoje": cancelamentos_hoje,
        "lavagem_taxa_retrabalho_pct": round(taxa_retrabalho_pct, 2),
        "lavagem_top_extras": top_extras,
    }


@router.get("/dashboards/rh")
async def dashboard_rh(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    fr = await db.execute(
        select(FeriasModel)
        .join(ColaboradorModel, ColaboradorModel.id == FeriasModel.colaborador_id)
        .where(ColaboradorModel.company_id == current_user.company_id)
        .where(FeriasModel.estado == "em_curso")
    )
    ferias_em_curso = len(list(fr.scalars().all()))

    cr = await db.execute(
        select(ColaboradorModel)
        .where(ColaboradorModel.company_id == current_user.company_id)
        .where(ColaboradorModel.estado == "ativo")
        .where(ColaboradorModel.deleted_at.is_(None))
    )
    colaboradores_ativos = list(cr.scalars().all())

    faltas_total = 0
    for c in colaboradores_ativos:
        fal_r = await db.execute(select(FaltaModel).where(FaltaModel.colaborador_id == c.id))
        faltas_total += len(list(fal_r.scalars().all()))

    assiduidade_media_pct = 100.0
    if colaboradores_ativos:
        # aproximação simples: 1 falta = -1pp na assiduidade média (sem histórico de dias úteis reais)
        assiduidade_media_pct = max(0.0, 100.0 - (faltas_total / len(colaboradores_ativos)))

    return {
        "colaboradores_ativos": len(colaboradores_ativos),
        "ferias_em_curso": ferias_em_curso,
        "assiduidade_media_pct": round(assiduidade_media_pct, 2),
    }


@router.get("/analytics/comparativo")
async def comparativo(
    indicador: str,
    periodo_a_inicio: datetime,
    periodo_a_fim: datetime,
    periodo_b_inicio: datetime,
    periodo_b_fim: datetime,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.ver")),
):
    """Comparativo simples entre dois períodos para o indicador 'vendas'
    (único implementado com dados reais suficientes hoje)."""
    if indicador != "vendas":
        return {"erro": f"Indicador '{indicador}' ainda não suportado em analytics"}

    async def total_vendas(inicio: datetime, fim: datetime) -> Decimal:
        r = await db.execute(
            select(VendaModel)
            .where(and_(
                VendaModel.company_id == current_user.company_id,
                VendaModel.estado == "concluida",
                VendaModel.data >= inicio,
                VendaModel.data <= fim,
            ))
        )
        return sum((Decimal(v.total_liquido) for v in r.scalars().all()), Decimal("0"))

    total_a = await total_vendas(periodo_a_inicio, periodo_a_fim)
    total_b = await total_vendas(periodo_b_inicio, periodo_b_fim)
    variacao_pct = ((total_b - total_a) / total_a * Decimal("100")) if total_a > 0 else Decimal("0")

    return {
        "periodo_a": {"total": float(total_a)},
        "periodo_b": {"total": float(total_b)},
        "variacao_pct": float(variacao_pct.quantize(Decimal("0.01"))),
    }


__all__ = ["router"]
