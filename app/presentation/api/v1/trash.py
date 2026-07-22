from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from uuid import UUID
from datetime import datetime
from typing import Literal

from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    FornecedorModel, ConceptoModel, MovimentoFinanceiroModel,
)
from app.infrastructure.auth.dependencies import require_admin
from app.infrastructure.audit import write_audit
from app.domain.entities import User

router = APIRouter()

_MODELS = {
    "fornecedores": FornecedorModel,
    "conceitos": ConceptoModel,
    "movimentos": MovimentoFinanceiroModel,
}


@router.get("")
async def listar_lixeira(
    tipo: Literal["fornecedores", "conceitos", "movimentos"],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    Model = _MODELS[tipo]
    r = await db.execute(
        select(Model).where(and_(
            Model.company_id == current_user.company_id,
            Model.deleted_at.isnot(None),
        )).order_by(Model.deleted_at.desc()).limit(100)
    )
    items = []
    for m in r.scalars().all():
        item = {
            "id": str(m.id),
            "deleted_at": m.deleted_at.isoformat() if m.deleted_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        if tipo == "fornecedores":
            item.update({"nome": m.nome, "nif": m.nif, "telefone": m.telefone})
        elif tipo == "conceitos":
            item.update({"nome": m.nome, "descricao": m.descricao})
        elif tipo == "movimentos":
            item.update({
                "codigo": m.codigo,
                "tipo_movimento": m.tipo_movimento,
                "valor": float(m.valor),
                "data": m.data.isoformat() if m.data else None,
                "observacoes": m.observacoes,
            })
        items.append(item)
    return items


@router.post("/{tipo}/{id}/restore")
async def restaurar(
    tipo: Literal["fornecedores", "conceitos", "movimentos"],
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    Model = _MODELS[tipo]
    r = await db.execute(select(Model).where(and_(
        Model.id == id, Model.company_id == current_user.company_id,
    )))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Registo não encontrado")
    if m.deleted_at is None:
        raise HTTPException(400, "Registo não está apagado")
    m.deleted_at = None
    await write_audit(
        db, current_user.id, current_user.company_id,
        "restaurado", tipo.rstrip("s"), id,
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"restaurado": True, "id": str(id), "tipo": tipo}


@router.delete("/{tipo}/{id}", status_code=204)
async def apagar_definitivamente(
    tipo: Literal["fornecedores", "conceitos", "movimentos"],
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Apaga permanentemente um registo já em soft-delete."""
    Model = _MODELS[tipo]
    r = await db.execute(select(Model).where(and_(
        Model.id == id, Model.company_id == current_user.company_id,
    )))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Registo não encontrado")
    if m.deleted_at is None:
        raise HTTPException(400, "Para apagar permanentemente, o registo tem de estar primeiro na Lixeira")
    await write_audit(
        db, current_user.id, current_user.company_id,
        "apagado_permanentemente", tipo.rstrip("s"), id,
        ip_address=req.client.host if req.client else None,
    )
    await db.delete(m)
    await db.commit()


__all__ = ["router"]
