from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from uuid import UUID
from typing import Optional
from datetime import datetime, timedelta
from decimal import Decimal
from calendar import monthrange

from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    MovimentoFinanceiroModel, FornecedorModel, ConceptoModel, AuditLogModel, UserModel,
    FundoCarregamentoModel, FundoModel,
)
from app.infrastructure.repositories import (
    FundoRepository, MovimentoRepository, FornecedorRepository, ConceptoRepository,
)
from app.infrastructure.auth.dependencies import get_current_user
from app.domain.entities import User

router = APIRouter()


async def _mov_stats(db: AsyncSession, cid, data_inicio=None, data_fim=None) -> dict:
    filters = [MovimentoFinanceiroModel.company_id == cid, MovimentoFinanceiroModel.deleted_at == None]
    if data_inicio:
        filters.append(MovimentoFinanceiroModel.data >= data_inicio)
    if data_fim:
        filters.append(MovimentoFinanceiroModel.data <= data_fim)

    r = await db.execute(
        select(
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
            MovimentoFinanceiroModel.fundo_tipo,
            func.coalesce(func.sum(MovimentoFinanceiroModel.valor), 0).label("total"),
            func.count(MovimentoFinanceiroModel.id).label("qtd"),
        ).where(and_(*filters))
        .group_by(
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
            MovimentoFinanceiroModel.fundo_tipo,
        )
    )
    rows = r.all()

    def s(tipo_mov=None, estado=None, fundo_tipo=None) -> float:
        return sum(
            float(row.total) for row in rows
            if (tipo_mov is None or row.tipo_movimento == tipo_mov)
            and (estado is None or row.estado_pagamento == estado)
            and (fundo_tipo is None or (row.fundo_tipo or "BCS") == fundo_tipo)
        )

    def c(estado=None, fundo_tipo=None) -> int:
        return sum(
            row.qtd for row in rows
            if (estado is None or row.estado_pagamento == estado)
            and (fundo_tipo is None or (row.fundo_tipo or "BCS") == fundo_tipo)
        )

    return {
        "total_gastos": s("saida"),
        "total_gastos_bcs": s("saida", fundo_tipo="BCS"),
        "total_gastos_bfa": s("saida", fundo_tipo="BFA"),
        "total_entradas": s("entrada"),
        "total_entradas_bcs": s("entrada", fundo_tipo="BCS"),
        "total_entradas_bfa": s("entrada", fundo_tipo="BFA"),
        "valor_pendentes": s(estado="pendente"),
        "valor_pendentes_bcs": s(estado="pendente", fundo_tipo="BCS"),
        "valor_pendentes_bfa": s(estado="pendente", fundo_tipo="BFA"),
        "count_pendentes": c(estado="pendente"),
        "count_pagos": c(estado="pago"),
        "total_saidas_pagas": s("saida", "pago"),
    }


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


@router.get("/dashboard")
async def dashboard(
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    fundo_repo = FundoRepository(db)
    forn_repo = FornecedorRepository(db)
    conc_repo = ConceptoRepository(db)

    # Período actual: se sem filtro usa mês corrente
    now = datetime.utcnow()
    if not data_inicio and not data_fim:
        di = datetime(now.year, now.month, 1)
        last_day = monthrange(now.year, now.month)[1]
        df = datetime(now.year, now.month, last_day, 23, 59, 59)
        # Mês anterior
        if now.month == 1:
            prev_di = datetime(now.year - 1, 12, 1)
            prev_last = monthrange(now.year - 1, 12)[1]
            prev_df = datetime(now.year - 1, 12, prev_last, 23, 59, 59)
        else:
            prev_di = datetime(now.year, now.month - 1, 1)
            prev_last = monthrange(now.year, now.month - 1)[1]
            prev_df = datetime(now.year, now.month - 1, prev_last, 23, 59, 59)
    else:
        di = data_inicio
        df = data_fim
        # Período anterior com mesma duração
        if di and df:
            delta = df - di
            prev_df = di - timedelta(seconds=1)
            prev_di = prev_df - delta
        else:
            prev_di = prev_df = None

    fundo_bcs = await fundo_repo.get_by_company_and_tipo(cid, "BCS")
    fundo_bfa = await fundo_repo.get_by_company_and_tipo(cid, "BFA")
    stats_atual = await _mov_stats(db, cid, di, df)
    stats_prev = await _mov_stats(db, cid, prev_di, prev_df) if prev_di else None

    total_fornecedores = await forn_repo.count(cid)
    total_conceitos = await conc_repo.count(cid)

    def _f(fundo, attr):
        return float(getattr(fundo, attr, 0) or 0) if fundo else 0

    def diff(campo):
        if not stats_prev:
            return {"valor": stats_atual[campo], "delta": None, "pct": None}
        prev = stats_prev[campo]
        curr = stats_atual[campo]
        return {"valor": curr, "delta": round(curr - prev, 2), "pct": _pct_change(curr, prev)}

    return {
        "fundo": {
            "valor_disponivel": _f(fundo_bcs, "valor_disponivel") + _f(fundo_bfa, "valor_disponivel"),
            "acumulado": _f(fundo_bcs, "acumulado") + _f(fundo_bfa, "acumulado"),
            "saldo_atual": _f(fundo_bcs, "saldo_atual") + _f(fundo_bfa, "saldo_atual"),
            "bcs": {
                "valor_disponivel": _f(fundo_bcs, "valor_disponivel"),
                "acumulado": _f(fundo_bcs, "acumulado"),
                "saldo_atual": _f(fundo_bcs, "saldo_atual"),
            },
            "bfa": {
                "valor_disponivel": _f(fundo_bfa, "valor_disponivel"),
                "acumulado": _f(fundo_bfa, "acumulado"),
                "saldo_atual": _f(fundo_bfa, "saldo_atual"),
            },
        },
        "periodo": {
            "data_inicio": di.isoformat() if di else None,
            "data_fim": df.isoformat() if df else None,
        },
        "movimentos": {
            "total_gastos": diff("total_gastos"),
            "total_gastos_bcs": diff("total_gastos_bcs"),
            "total_gastos_bfa": diff("total_gastos_bfa"),
            "total_entradas": diff("total_entradas"),
            "total_entradas_bcs": diff("total_entradas_bcs"),
            "total_entradas_bfa": diff("total_entradas_bfa"),
            "valor_pendentes": diff("valor_pendentes"),
            "valor_pendentes_bcs": diff("valor_pendentes_bcs"),
            "valor_pendentes_bfa": diff("valor_pendentes_bfa"),
            "count_pendentes": stats_atual["count_pendentes"],
            "count_pagos": stats_atual["count_pagos"],
            "total_saidas_pagas": stats_atual["total_saidas_pagas"],
        },
        "fornecedores": total_fornecedores,
        "conceitos": total_conceitos,
    }


@router.get("/fundos")
async def relatorio_fundos(
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    fundo_repo = FundoRepository(db)
    fundo_bcs = await fundo_repo.get_by_company_and_tipo(cid, "BCS")
    fundo_bfa = await fundo_repo.get_by_company_and_tipo(cid, "BFA")

    mov_filters = [MovimentoFinanceiroModel.company_id == cid, MovimentoFinanceiroModel.deleted_at == None]
    if data_inicio:
        mov_filters.append(MovimentoFinanceiroModel.data >= data_inicio)
    if data_fim:
        mov_filters.append(MovimentoFinanceiroModel.data <= data_fim)

    mov_r = await db.execute(
        select(
            MovimentoFinanceiroModel.fundo_tipo,
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
            func.coalesce(func.sum(MovimentoFinanceiroModel.valor), 0).label("total"),
            func.count(MovimentoFinanceiroModel.id).label("qtd"),
        ).where(and_(*mov_filters))
        .group_by(
            MovimentoFinanceiroModel.fundo_tipo,
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
        )
    )
    mov_rows = mov_r.all()

    carr_filters = [FundoCarregamentoModel.company_id == cid]
    if data_inicio:
        carr_filters.append(FundoCarregamentoModel.created_at >= data_inicio)
    if data_fim:
        carr_filters.append(FundoCarregamentoModel.created_at <= data_fim)

    carr_r = await db.execute(
        select(
            FundoModel.tipo.label("fundo_tipo"),
            func.count(FundoCarregamentoModel.id).label("qtd"),
            func.coalesce(func.sum(FundoCarregamentoModel.valor_novo - FundoCarregamentoModel.valor_anterior), 0).label("total"),
        )
        .join(FundoModel, FundoCarregamentoModel.fundo_id == FundoModel.id)
        .where(and_(*carr_filters))
        .group_by(FundoModel.tipo)
    )
    carr_rows = carr_r.all()

    def _fund(f, tipo: str) -> dict:
        snapshot = {
            "tipo": tipo,
            "valor_disponivel": float(f.valor_disponivel) if f else 0.0,
            "acumulado": float(f.acumulado) if f else 0.0,
            "saldo_atual": float(f.saldo_atual) if f else 0.0,
        }
        ft = (lambda x: (x or "BCS") == tipo)
        entradas = sum(float(r.total) for r in mov_rows if ft(r.fundo_tipo) and r.tipo_movimento == "entrada")
        saidas_total = sum(float(r.total) for r in mov_rows if ft(r.fundo_tipo) and r.tipo_movimento == "saida")
        saidas_pagas = sum(float(r.total) for r in mov_rows if ft(r.fundo_tipo) and r.tipo_movimento == "saida" and r.estado_pagamento == "pago")
        saidas_pendentes = sum(float(r.total) for r in mov_rows if ft(r.fundo_tipo) and r.tipo_movimento == "saida" and r.estado_pagamento == "pendente")
        qtd_entradas = sum(int(r.qtd) for r in mov_rows if ft(r.fundo_tipo) and r.tipo_movimento == "entrada")
        qtd_saidas = sum(int(r.qtd) for r in mov_rows if ft(r.fundo_tipo) and r.tipo_movimento == "saida")
        carr = next(((int(r.qtd), float(r.total)) for r in carr_rows if (r.fundo_tipo or "BCS") == tipo), (0, 0.0))
        return {
            **snapshot,
            "periodo": {
                "entradas": entradas,
                "saidas": saidas_total,
                "saidas_pagas": saidas_pagas,
                "saidas_pendentes": saidas_pendentes,
                "qtd_entradas": qtd_entradas,
                "qtd_saidas": qtd_saidas,
                "carregamentos_qtd": carr[0],
                "carregamentos_total": carr[1],
            },
        }

    return {
        "periodo": {
            "data_inicio": data_inicio.isoformat() if data_inicio else None,
            "data_fim": data_fim.isoformat() if data_fim else None,
        },
        "bcs": _fund(fundo_bcs, "BCS"),
        "bfa": _fund(fundo_bfa, "BFA"),
    }


@router.get("/produtividade-users")
async def produtividade_users(
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Produtividade por utilizador — movimentos criados/fechados no período."""
    from sqlalchemy import text as _t
    di = data_inicio or (datetime.utcnow().replace(day=1))
    df = data_fim or datetime.utcnow()
    r = await db.execute(_t(
        """
        SELECT u.id, u.full_name, u.email,
          COUNT(m.id) FILTER (WHERE m.deleted_at IS NULL AND m.created_at BETWEEN :di AND :df) AS criados,
          COALESCE(SUM(m.valor) FILTER (WHERE m.deleted_at IS NULL AND m.tipo_movimento='entrada' AND m.created_at BETWEEN :di AND :df), 0) AS total_entradas,
          COALESCE(SUM(m.valor) FILTER (WHERE m.deleted_at IS NULL AND m.tipo_movimento='saida' AND m.created_at BETWEEN :di AND :df), 0) AS total_saidas,
          COUNT(m.id) FILTER (WHERE m.deleted_at IS NULL AND m.estado_movimento='fechado' AND m.created_at BETWEEN :di AND :df) AS fechados
        FROM users u
        LEFT JOIN movimentos_financeiros m ON m.created_by::text = u.id::text AND m.company_id::text = u.company_id::text
        WHERE u.company_id::text = :cid AND u.deleted_at IS NULL
        GROUP BY u.id, u.full_name, u.email
        ORDER BY criados DESC, u.full_name
        """
    ), {"cid": str(current_user.company_id), "di": di, "df": df})
    return [
        {
            "user_id": str(row[0]), "user_name": row[1], "email": row[2],
            "movimentos_criados": row[3] or 0,
            "total_entradas": float(row[4] or 0),
            "total_saidas": float(row[5] or 0),
            "movimentos_fechados": row[6] or 0,
        }
        for row in r.all()
    ]


@router.get("/auditoria")
async def auditoria(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    entidade: Optional[str] = None,
    acao: Optional[str] = None,
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    filters = [AuditLogModel.company_id == cid]
    if entidade:
        filters.append(AuditLogModel.entidade == entidade)
    if acao:
        filters.append(AuditLogModel.acao == acao)
    if data_inicio:
        filters.append(AuditLogModel.created_at >= data_inicio)
    if data_fim:
        filters.append(AuditLogModel.created_at <= data_fim)

    total_r = await db.execute(select(func.count(AuditLogModel.id)).where(and_(*filters)))
    total = total_r.scalar_one()

    skip = (page - 1) * page_size
    items_r = await db.execute(
        select(AuditLogModel, UserModel.full_name.label("user_name"), UserModel.email.label("user_email"))
        .outerjoin(UserModel, AuditLogModel.user_id == UserModel.id)
        .where(and_(*filters))
        .order_by(AuditLogModel.created_at.desc())
        .offset(skip).limit(page_size)
    )
    rows = items_r.all()

    # Recolher IDs de fornecedores e conceitos referidos nos dados, para resolver para nomes
    forn_ids: set[str] = set()
    conc_ids: set[str] = set()
    for row in rows:
        for blob in (row.AuditLogModel.dados_anteriores, row.AuditLogModel.dados_novos):
            if isinstance(blob, dict):
                if blob.get("fornecedor_id"): forn_ids.add(str(blob["fornecedor_id"]))
                if blob.get("conceito_id"): conc_ids.add(str(blob["conceito_id"]))

    forn_map: dict[str, str] = {}
    if forn_ids:
        rf = await db.execute(select(FornecedorModel.id, FornecedorModel.nome).where(FornecedorModel.id.in_(list(forn_ids))))
        forn_map = {str(fid): nome for fid, nome in rf.all()}
    conc_map: dict[str, str] = {}
    if conc_ids:
        rc = await db.execute(select(ConceptoModel.id, ConceptoModel.nome).where(ConceptoModel.id.in_(list(conc_ids))))
        conc_map = {str(cid): nome for cid, nome in rc.all()}

    def _enrich(blob):
        if not isinstance(blob, dict):
            return blob
        out = dict(blob)
        fid = out.get("fornecedor_id")
        if fid and str(fid) in forn_map:
            out["fornecedor_nome"] = forn_map[str(fid)]
        cid = out.get("conceito_id")
        if cid and str(cid) in conc_map:
            out["conceito_nome"] = conc_map[str(cid)]
        return out

    return {
        "items": [
            {
                "id": str(row.AuditLogModel.id),
                "acao": row.AuditLogModel.acao,
                "entidade": row.AuditLogModel.entidade,
                "entidade_id": str(row.AuditLogModel.entidade_id) if row.AuditLogModel.entidade_id else None,
                "user_name": row.user_name or "—",
                "user_email": row.user_email or "—",
                "dados_anteriores": _enrich(row.AuditLogModel.dados_anteriores),
                "dados_novos": _enrich(row.AuditLogModel.dados_novos),
                "ip_address": row.AuditLogModel.ip_address or "",
                "created_at": row.AuditLogModel.created_at.isoformat() if row.AuditLogModel.created_at else None,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/mensal")
async def relatorio_mensal(
    ano: int = Query(default=datetime.utcnow().year),
    mes: int = Query(default=datetime.utcnow().month, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    data_inicio = datetime(ano, mes, 1)
    data_fim = datetime(ano + 1, 1, 1) if mes == 12 else datetime(ano, mes + 1, 1)

    result = await db.execute(
        select(
            MovimentoFinanceiroModel.tipo_movimento,
            MovimentoFinanceiroModel.estado_pagamento,
            func.sum(MovimentoFinanceiroModel.valor).label("total"),
            func.count(MovimentoFinanceiroModel.id).label("qtd"),
        ).where(and_(
            MovimentoFinanceiroModel.company_id == cid,
            MovimentoFinanceiroModel.data >= data_inicio,
            MovimentoFinanceiroModel.data < data_fim,
            MovimentoFinanceiroModel.deleted_at == None,
        )).group_by(MovimentoFinanceiroModel.tipo_movimento, MovimentoFinanceiroModel.estado_pagamento)
    )
    rows = result.all()
    return {
        "periodo": {"ano": ano, "mes": mes},
        "resumo": [
            {"tipo": r.tipo_movimento, "estado": r.estado_pagamento, "total": float(r.total), "quantidade": r.qtd}
            for r in rows
        ],
    }


@router.get("/fornecedor")
async def relatorio_por_fornecedor(
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    filters = [MovimentoFinanceiroModel.company_id == cid, MovimentoFinanceiroModel.deleted_at == None]
    if data_inicio:
        filters.append(MovimentoFinanceiroModel.data >= data_inicio)
    if data_fim:
        filters.append(MovimentoFinanceiroModel.data <= data_fim)

    result = await db.execute(
        select(FornecedorModel.id, FornecedorModel.nome,
               func.sum(MovimentoFinanceiroModel.valor).label("total"),
               func.count(MovimentoFinanceiroModel.id).label("qtd"))
        .join(FornecedorModel, MovimentoFinanceiroModel.fornecedor_id == FornecedorModel.id)
        .where(and_(*filters))
        .group_by(FornecedorModel.id, FornecedorModel.nome)
        .order_by(func.sum(MovimentoFinanceiroModel.valor).desc())
    )
    return [{"fornecedor_id": str(r.id), "nome": r.nome, "total": float(r.total), "quantidade": r.qtd} for r in result.all()]


@router.get("/conceito")
async def relatorio_por_conceito(
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    filters = [MovimentoFinanceiroModel.company_id == cid, MovimentoFinanceiroModel.deleted_at == None]
    if data_inicio:
        filters.append(MovimentoFinanceiroModel.data >= data_inicio)
    if data_fim:
        filters.append(MovimentoFinanceiroModel.data <= data_fim)

    result = await db.execute(
        select(ConceptoModel.id, ConceptoModel.nome,
               func.sum(MovimentoFinanceiroModel.valor).label("total"),
               func.count(MovimentoFinanceiroModel.id).label("qtd"))
        .join(ConceptoModel, MovimentoFinanceiroModel.conceito_id == ConceptoModel.id)
        .where(and_(*filters))
        .group_by(ConceptoModel.id, ConceptoModel.nome)
        .order_by(func.sum(MovimentoFinanceiroModel.valor).desc())
    )
    return [{"conceito_id": str(r.id), "nome": r.nome, "total": float(r.total), "quantidade": r.qtd} for r in result.all()]


@router.get("/extrato")
async def extrato(
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mov_repo = MovimentoRepository(db)
    skip = (page - 1) * page_size
    items = await mov_repo.get_all(current_user.company_id, skip=skip, limit=page_size, data_inicio=data_inicio, data_fim=data_fim)
    total = await mov_repo.count(current_user.company_id, data_inicio=data_inicio, data_fim=data_fim)
    return {
        "items": [{"id": str(m.id), "data": m.data.isoformat() if m.data else None,
                   "fornecedor_id": str(m.fornecedor_id), "conceito_id": str(m.conceito_id),
                   "valor": float(m.valor), "tipo_movimento": m.tipo_movimento, "estado_pagamento": m.estado_pagamento}
                  for m in items],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


__all__ = ["router"]
