from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from datetime import datetime
from uuid import uuid4
from pydantic import BaseModel
from typing import Optional

from app.infrastructure.database import get_db
from app.infrastructure.database.models import PeriodoFechadoModel
from app.infrastructure.auth.dependencies import get_current_user, require_admin
from app.infrastructure.audit import write_audit
from app.domain.entities import User

router = APIRouter()


class FecharPeriodoDTO(BaseModel):
    ano: int
    mes: int
    motivo: Optional[str] = None


def _ym(ano, mes) -> tuple[str, str]:
    return (f"{int(ano):04d}", f"{int(mes):02d}")


async def is_periodo_fechado(db: AsyncSession, company_id, data: datetime) -> bool:
    """Helper para outros routers verificarem se um período está fechado."""
    ano, mes = _ym(data.year, data.month)
    r = await db.execute(select(PeriodoFechadoModel).where(and_(
        PeriodoFechadoModel.company_id == company_id,
        PeriodoFechadoModel.ano == ano,
        PeriodoFechadoModel.mes == mes,
    )))
    return r.scalar_one_or_none() is not None


@router.get("")
async def listar_periodos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(PeriodoFechadoModel)
        .where(PeriodoFechadoModel.company_id == current_user.company_id)
        .order_by(PeriodoFechadoModel.ano.desc(), PeriodoFechadoModel.mes.desc())
    )
    return [{
        "id": str(p.id),
        "ano": int(p.ano),
        "mes": int(p.mes),
        "fechado_em": p.fechado_em.isoformat() if p.fechado_em else None,
        "fechado_por": str(p.fechado_por) if p.fechado_por else None,
        "motivo": p.motivo,
    } for p in r.scalars().all()]


@router.post("/fechar", status_code=201)
async def fechar_periodo(
    body: FecharPeriodoDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if body.mes < 1 or body.mes > 12:
        raise HTTPException(400, "Mês inválido (1-12)")
    ano, mes = _ym(body.ano, body.mes)
    r = await db.execute(select(PeriodoFechadoModel).where(and_(
        PeriodoFechadoModel.company_id == current_user.company_id,
        PeriodoFechadoModel.ano == ano,
        PeriodoFechadoModel.mes == mes,
    )))
    if r.scalar_one_or_none():
        raise HTTPException(409, f"Período {ano}-{mes} já está fechado")
    p = PeriodoFechadoModel(
        id=uuid4(),
        company_id=current_user.company_id,
        ano=ano, mes=mes,
        fechado_por=current_user.id,
        motivo=body.motivo,
    )
    db.add(p)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "fechado", "periodo", p.id,
        dados_novos={"ano": int(ano), "mes": int(mes), "motivo": body.motivo},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"id": str(p.id), "ano": int(ano), "mes": int(mes)}


@router.post("/reabrir/{ano}/{mes}")
async def reabrir_periodo(
    ano: int, mes: int,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    ano_s, mes_s = _ym(ano, mes)
    r = await db.execute(select(PeriodoFechadoModel).where(and_(
        PeriodoFechadoModel.company_id == current_user.company_id,
        PeriodoFechadoModel.ano == ano_s,
        PeriodoFechadoModel.mes == mes_s,
    )))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Período não está fechado")
    await write_audit(
        db, current_user.id, current_user.company_id,
        "reaberto", "periodo", p.id,
        dados_anteriores={"ano": ano, "mes": mes},
        ip_address=req.client.host if req.client else None,
    )
    await db.delete(p)
    await db.commit()
    return {"reaberto": True, "ano": ano, "mes": mes}


__all__ = ["router", "is_periodo_fechado"]
