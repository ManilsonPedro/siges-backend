from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func
from typing import Literal

from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    MovimentoFinanceiroModel, FornecedorModel, ConceptoModel,
)
from app.infrastructure.auth.dependencies import get_current_user
from app.domain.entities import User

router = APIRouter()


@router.get("")
async def pesquisa_global(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pesquisa global em movimentos, fornecedores e conceitos."""
    cid = current_user.company_id
    term = f"%{q.lower()}%"
    results: list[dict] = []

    # Movimentos (código, observação)
    r_mov = await db.execute(
        select(MovimentoFinanceiroModel)
        .where(and_(
            MovimentoFinanceiroModel.company_id == cid,
            MovimentoFinanceiroModel.deleted_at == None,
            or_(
                func.lower(MovimentoFinanceiroModel.codigo).like(term),
                func.lower(MovimentoFinanceiroModel.observacoes).like(term),
                func.lower(MovimentoFinanceiroModel.fatura_proforma).like(term),
                func.lower(MovimentoFinanceiroModel.fatura_recibo).like(term),
            ),
        ))
        .order_by(MovimentoFinanceiroModel.created_at.desc())
        .limit(limit)
    )
    for m in r_mov.scalars().all():
        results.append({
            "type": "movimento",
            "id": str(m.id),
            "label": m.codigo or f"Mov sem código",
            "sublabel": f"{m.tipo_movimento.title()} · {float(m.valor):,.2f} Kz · {m.estado_pagamento}",
            "href": f"/dashboard/movimentos?highlight={m.id}",
        })

    # Fornecedores (nome, NIF)
    r_forn = await db.execute(
        select(FornecedorModel)
        .where(and_(
            FornecedorModel.company_id == cid,
            FornecedorModel.deleted_at == None,
            or_(
                func.lower(FornecedorModel.nome).like(term),
                func.lower(FornecedorModel.nif).like(term),
                func.lower(FornecedorModel.email).like(term),
            ),
        ))
        .limit(limit)
    )
    for f in r_forn.scalars().all():
        results.append({
            "type": "fornecedor",
            "id": str(f.id),
            "label": f.nome,
            "sublabel": f"NIF {f.nif} · {f.estado}",
            "href": f"/dashboard/fornecedores?highlight={f.id}",
        })

    # Conceitos (nome, descrição)
    r_con = await db.execute(
        select(ConceptoModel)
        .where(and_(
            ConceptoModel.company_id == cid,
            ConceptoModel.deleted_at == None,
            or_(
                func.lower(ConceptoModel.nome).like(term),
                func.lower(ConceptoModel.descricao).like(term),
            ),
        ))
        .limit(limit)
    )
    for c in r_con.scalars().all():
        results.append({
            "type": "conceito",
            "id": str(c.id),
            "label": c.nome,
            "sublabel": c.descricao or "—",
            "href": f"/dashboard/conceitos?highlight={c.id}",
        })

    return {"query": q, "total": len(results), "results": results}


__all__ = ["router"]
