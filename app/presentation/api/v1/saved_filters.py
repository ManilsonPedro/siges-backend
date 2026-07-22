from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional

from app.infrastructure.database import get_db
from app.infrastructure.database.models import SavedFilterModel
from app.infrastructure.auth.dependencies import get_current_user
from app.domain.entities import User

router = APIRouter()


class SavedFilterCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    route: str = Field(..., min_length=1, max_length=100)
    params: dict = Field(default_factory=dict)


class SavedFilterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    params: Optional[dict] = None


def _to_dict(f: SavedFilterModel) -> dict:
    return {
        "id": str(f.id),
        "name": f.name,
        "route": f.route,
        "params": f.params or {},
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@router.get("")
async def listar_filtros(
    route: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = [SavedFilterModel.user_id == current_user.id]
    if route:
        filters.append(SavedFilterModel.route == route)
    r = await db.execute(
        select(SavedFilterModel).where(and_(*filters)).order_by(SavedFilterModel.created_at.desc())
    )
    return [_to_dict(f) for f in r.scalars().all()]


@router.post("", status_code=201)
async def criar_filtro(
    body: SavedFilterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    f = SavedFilterModel(
        user_id=current_user.id,
        company_id=current_user.company_id,
        name=body.name,
        route=body.route,
        params=body.params,
    )
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return _to_dict(f)


@router.put("/{id}")
async def atualizar_filtro(
    id: UUID,
    body: SavedFilterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(SavedFilterModel).where(SavedFilterModel.id == id))
    f = r.scalar_one_or_none()
    if not f or f.user_id != current_user.id:
        raise HTTPException(404, "Filtro não encontrado")
    if body.name is not None:
        f.name = body.name
    if body.params is not None:
        f.params = body.params
    await db.commit()
    await db.refresh(f)
    return _to_dict(f)


@router.delete("/{id}", status_code=204)
async def eliminar_filtro(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(SavedFilterModel).where(SavedFilterModel.id == id))
    f = r.scalar_one_or_none()
    if not f or f.user_id != current_user.id:
        raise HTTPException(404, "Filtro não encontrado")
    await db.delete(f)
    await db.commit()


__all__ = ["router"]
