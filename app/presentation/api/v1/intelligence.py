"""Inteligência Financeira (Épico 9):
  - 9.1 — Evolução de saldo por fundo (BCS, BFA)
  - 9.3 — Orçamento por conceito + alertas
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text
from datetime import datetime, timedelta
from calendar import monthrange
from decimal import Decimal
from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional

from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    MovimentoFinanceiroModel, OrcamentoModel, ConceptoModel, FundoModel,
)
from app.infrastructure.auth.dependencies import get_current_user, require_financeiro
from app.domain.entities import User

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# 9.1 — Evolução de saldo
# ─────────────────────────────────────────────────────────────────────

@router.get("/evolucao-saldo")
async def evolucao_saldo(
    meses: int = Query(default=6, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Saldo (cumulativo) por mês para BCS e BFA nos últimos N meses.
    Saldo = Entradas acumuladas − Saídas pagas acumuladas (sem considerar valor_disponivel manual,
    porque a evolução temporal vem dos movimentos).
    """
    cid = current_user.company_id
    hoje = datetime.utcnow()
    inicio = datetime(hoje.year, hoje.month, 1) - timedelta(days=meses * 31)
    inicio = datetime(inicio.year, inicio.month, 1)

    # Soma por (mes, fundo_tipo, tipo_movimento)
    r = await db.execute(
        select(
            func.extract("year", MovimentoFinanceiroModel.data).label("ano"),
            func.extract("month", MovimentoFinanceiroModel.data).label("mes"),
            MovimentoFinanceiroModel.fundo_tipo,
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
            func.coalesce(func.sum(MovimentoFinanceiroModel.valor), 0).label("total"),
        )
        .where(and_(
            MovimentoFinanceiroModel.company_id == cid,
            MovimentoFinanceiroModel.deleted_at == None,
            MovimentoFinanceiroModel.data >= inicio,
        ))
        .group_by(
            func.extract("year", MovimentoFinanceiroModel.data),
            func.extract("month", MovimentoFinanceiroModel.data),
            MovimentoFinanceiroModel.fundo_tipo,
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
        )
    )
    rows = r.all()

    # Construir série mensal
    series_bcs: list[dict] = []
    series_bfa: list[dict] = []
    acc_bcs = 0.0
    acc_bfa = 0.0

    cur = datetime(inicio.year, inicio.month, 1)
    while cur <= hoje:
        label = cur.strftime("%Y-%m")
        ent_bcs = sum(float(r.total) for r in rows if int(r.ano) == cur.year and int(r.mes) == cur.month and (r.fundo_tipo or "BCS") == "BCS" and r.tipo_movimento == "entrada")
        sai_bcs = sum(float(r.total) for r in rows if int(r.ano) == cur.year and int(r.mes) == cur.month and (r.fundo_tipo or "BCS") == "BCS" and r.tipo_movimento == "saida" and r.estado_pagamento in ("pago", "pago_total"))
        ent_bfa = sum(float(r.total) for r in rows if int(r.ano) == cur.year and int(r.mes) == cur.month and (r.fundo_tipo or "BCS") == "BFA" and r.tipo_movimento == "entrada")
        sai_bfa = sum(float(r.total) for r in rows if int(r.ano) == cur.year and int(r.mes) == cur.month and (r.fundo_tipo or "BCS") == "BFA" and r.tipo_movimento == "saida" and r.estado_pagamento in ("pago", "pago_total"))

        acc_bcs += ent_bcs - sai_bcs
        acc_bfa += ent_bfa - sai_bfa

        series_bcs.append({"mes": label, "entradas": ent_bcs, "saidas": sai_bcs, "saldo": acc_bcs})
        series_bfa.append({"mes": label, "entradas": ent_bfa, "saidas": sai_bfa, "saldo": acc_bfa})

        if cur.month == 12:
            cur = datetime(cur.year + 1, 1, 1)
        else:
            cur = datetime(cur.year, cur.month + 1, 1)

    return {
        "periodo_inicio": inicio.isoformat(),
        "periodo_fim": hoje.isoformat(),
        "bcs": series_bcs,
        "bfa": series_bfa,
    }


# ─────────────────────────────────────────────────────────────────────
# 9.1b — Evolução de saldo DIÁRIA (mês actual vs mês anterior)
# ─────────────────────────────────────────────────────────────────────

def _month_bounds(ano: int, mes: int) -> tuple[datetime, datetime]:
    last = monthrange(ano, mes)[1]
    return datetime(ano, mes, 1), datetime(ano, mes, last, 23, 59, 59)


def _prev_month(ano: int, mes: int) -> tuple[int, int]:
    if mes == 1:
        return ano - 1, 12
    return ano, mes - 1


_MES_PT = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
           "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


async def _serie_diaria(
    db: AsyncSession, company_id, fundo_tipo: Optional[str],
    inicio: datetime, fim: datetime, limite_dia: Optional[int] = None,
) -> list[dict]:
    """Devolve [{dia, entradas, saidas, saldo}] cumulativo para o mês.
    Se fundo_tipo é None, agrega ambos.
    Se limite_dia é dado, só preenche até esse dia (para o mês actual).
    """
    filters = [
        MovimentoFinanceiroModel.company_id == company_id,
        MovimentoFinanceiroModel.deleted_at == None,
        MovimentoFinanceiroModel.data >= inicio,
        MovimentoFinanceiroModel.data <= fim,
    ]
    if fundo_tipo:
        filters.append(MovimentoFinanceiroModel.fundo_tipo == fundo_tipo)

    r = await db.execute(
        select(
            func.date(MovimentoFinanceiroModel.data).label("dia"),
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
            func.coalesce(func.sum(MovimentoFinanceiroModel.valor), 0).label("total"),
        )
        .where(and_(*filters))
        .group_by(
            func.date(MovimentoFinanceiroModel.data),
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
        )
    )
    rows = r.all()

    last_day = monthrange(inicio.year, inicio.month)[1]
    series: list[dict] = []
    acc = 0.0
    for dia in range(1, last_day + 1):
        if limite_dia is not None and dia > limite_dia:
            # Não tem dados ainda — devolve null para a UI cortar a linha
            series.append({"dia": dia, "entradas": 0.0, "saidas": 0.0, "saldo": None})
            continue
        ent = sum(
            float(row.total) for row in rows
            if row.dia.day == dia and row.tipo_movimento == "entrada"
        )
        sai = sum(
            float(row.total) for row in rows
            if row.dia.day == dia and row.tipo_movimento == "saida"
            and row.estado_pagamento in ("pago", "pago_total")
        )
        acc += ent - sai
        series.append({"dia": dia, "entradas": ent, "saidas": sai, "saldo": round(acc, 2)})
    return series


@router.get("/evolucao-saldo-diaria")
async def evolucao_saldo_diaria(
    fundo: str = Query(default="todos", pattern="^(BCS|BFA|todos)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evolução diária do saldo para o mês actual + mês anterior.
    O mês anterior aparece completo; o actual pára no dia de hoje."""
    cid = current_user.company_id
    hoje = datetime.utcnow()
    fundo_tipo = None if fundo == "todos" else fundo

    # Mês actual
    inicio_a, fim_a = _month_bounds(hoje.year, hoje.month)
    serie_actual = await _serie_diaria(db, cid, fundo_tipo, inicio_a, fim_a, limite_dia=hoje.day)
    dias_no_mes_a = monthrange(hoje.year, hoje.month)[1]

    # Mês anterior
    ano_p, mes_p = _prev_month(hoje.year, hoje.month)
    inicio_p, fim_p = _month_bounds(ano_p, mes_p)
    serie_anterior = await _serie_diaria(db, cid, fundo_tipo, inicio_p, fim_p)
    dias_no_mes_p = monthrange(ano_p, mes_p)[1]

    # Comparativo: saldo de hoje vs mesmo dia mês anterior
    saldo_actual = next((s["saldo"] for s in reversed(serie_actual) if s["saldo"] is not None), 0.0) or 0.0
    # Mesmo dia (ou último dia se mês anterior tem menos dias)
    dia_comp = min(hoje.day, dias_no_mes_p)
    saldo_anterior_mesmo_dia = next((s["saldo"] for s in serie_anterior if s["dia"] == dia_comp), 0.0) or 0.0
    delta = saldo_actual - saldo_anterior_mesmo_dia
    delta_pct = (delta / saldo_anterior_mesmo_dia * 100) if saldo_anterior_mesmo_dia else None

    return {
        "fundo": fundo,
        "mes_actual": {
            "label": f"{_MES_PT[hoje.month]} {hoje.year}",
            "ano": hoje.year, "mes": hoje.month,
            "dias_no_mes": dias_no_mes_a,
            "ultimo_dia_com_dados": hoje.day,
            "serie": serie_actual,
        },
        "mes_anterior": {
            "label": f"{_MES_PT[mes_p]} {ano_p}",
            "ano": ano_p, "mes": mes_p,
            "dias_no_mes": dias_no_mes_p,
            "ultimo_dia_com_dados": dias_no_mes_p,
            "serie": serie_anterior,
        },
        "comparativo": {
            "saldo_actual": saldo_actual,
            "saldo_mes_anterior_mesmo_dia": saldo_anterior_mesmo_dia,
            "delta": delta,
            "delta_pct": delta_pct,
            "dia_comparacao": dia_comp,
        },
    }


# ─────────────────────────────────────────────────────────────────────
# 9.3 — Orçamentos
# ─────────────────────────────────────────────────────────────────────

class OrcamentoCreateDTO(BaseModel):
    conceito_id: UUID
    ano: int = Field(..., ge=2020, le=2100)
    mes: int = Field(..., ge=1, le=12)
    valor_planeado: Decimal = Field(..., ge=0)


class OrcamentoUpdateDTO(BaseModel):
    valor_planeado: Decimal = Field(..., ge=0)


def _orc_to_dict(o: OrcamentoModel, conceito_nome: Optional[str] = None, gasto: float = 0) -> dict:
    planeado = float(o.valor_planeado or 0)
    pct = (gasto / planeado * 100) if planeado > 0 else 0
    alerta = "ok"
    if pct >= 100:
        alerta = "ultrapassado"
    elif pct >= 80:
        alerta = "perto_limite"
    return {
        "id": str(o.id),
        "conceito_id": str(o.conceito_id),
        "conceito_nome": conceito_nome,
        "ano": int(o.ano),
        "mes": int(o.mes),
        "valor_planeado": planeado,
        "valor_gasto": gasto,
        "percentagem": round(pct, 1),
        "alerta": alerta,
    }


async def _gasto_real(db: AsyncSession, company_id, conceito_id, ano: int, mes: int) -> float:
    inicio = datetime(ano, mes, 1)
    ultimo_dia = monthrange(ano, mes)[1]
    fim = datetime(ano, mes, ultimo_dia, 23, 59, 59)
    r = await db.execute(
        select(func.coalesce(func.sum(MovimentoFinanceiroModel.valor), 0))
        .where(and_(
            MovimentoFinanceiroModel.company_id == company_id,
            MovimentoFinanceiroModel.conceito_id == conceito_id,
            MovimentoFinanceiroModel.tipo_movimento == "saida",
            MovimentoFinanceiroModel.estado_pagamento.in_(["pago", "pago_total"]),
            MovimentoFinanceiroModel.deleted_at == None,
            MovimentoFinanceiroModel.data >= inicio,
            MovimentoFinanceiroModel.data <= fim,
        ))
    )
    return float(r.scalar_one() or 0)


@router.get("/orcamentos")
async def listar_orcamentos(
    ano: int = Query(default=None),
    mes: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista orçamentos do mês com valor real gasto e % de utilização."""
    cid = current_user.company_id
    hoje = datetime.utcnow()
    ano = ano or hoje.year
    mes = mes or hoje.month
    ano_s = f"{ano:04d}"
    mes_s = f"{mes:02d}"

    r = await db.execute(
        select(OrcamentoModel, ConceptoModel.nome)
        .join(ConceptoModel, OrcamentoModel.conceito_id == ConceptoModel.id)
        .where(and_(
            OrcamentoModel.company_id == cid,
            OrcamentoModel.ano == ano_s,
            OrcamentoModel.mes == mes_s,
        ))
    )
    rows = r.all()
    items = []
    for o, conceito_nome in rows:
        gasto = await _gasto_real(db, cid, o.conceito_id, ano, mes)
        items.append(_orc_to_dict(o, conceito_nome, gasto))
    items.sort(key=lambda x: x["percentagem"], reverse=True)
    return {"ano": ano, "mes": mes, "items": items}


@router.post("/orcamentos", status_code=201)
async def criar_orcamento(
    body: OrcamentoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    ano_s = f"{body.ano:04d}"
    mes_s = f"{body.mes:02d}"
    # Upsert
    r = await db.execute(select(OrcamentoModel).where(and_(
        OrcamentoModel.company_id == current_user.company_id,
        OrcamentoModel.conceito_id == body.conceito_id,
        OrcamentoModel.ano == ano_s,
        OrcamentoModel.mes == mes_s,
    )))
    o = r.scalar_one_or_none()
    if o:
        o.valor_planeado = body.valor_planeado
    else:
        o = OrcamentoModel(
            company_id=current_user.company_id,
            conceito_id=body.conceito_id,
            ano=ano_s,
            mes=mes_s,
            valor_planeado=body.valor_planeado,
        )
        db.add(o)
    await db.commit()
    await db.refresh(o)
    gasto = await _gasto_real(db, current_user.company_id, o.conceito_id, body.ano, body.mes)
    r2 = await db.execute(select(ConceptoModel.nome).where(ConceptoModel.id == o.conceito_id))
    nome = r2.scalar_one_or_none()
    return _orc_to_dict(o, nome, gasto)


@router.delete("/orcamentos/{id}", status_code=204)
async def eliminar_orcamento(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    r = await db.execute(select(OrcamentoModel).where(OrcamentoModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.company_id != current_user.company_id:
        raise HTTPException(404, "Orçamento não encontrado")
    await db.delete(o)
    await db.commit()


__all__ = ["router"]
