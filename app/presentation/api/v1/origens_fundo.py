"""CRUD da Origem do Fundo (por empresa)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.infrastructure.database import get_db
from app.infrastructure.database.models import OrigemFundoModel
from app.infrastructure.auth.dependencies import get_current_user, require_admin
from app.infrastructure.audit import write_audit
from app.domain.entities import User

router = APIRouter()


# Seeds default (criados on-demand quando a empresa pede a lista pela primeira vez)
_DEFAULT_ORIGENS = [
    ("Aumento de Capital", "Capital injectado pelos sócios", 10),
    ("Empréstimo",         "Empréstimo bancário ou particular", 20),
    ("Receita",            "Receita operacional", 30),
    ("Outro",              "Origem diversa", 40),
]


async def _ensure_defaults(db: AsyncSession, company_id: str):
    """Cria as origens default desta empresa se ainda não existirem."""
    r = await db.execute(
        text("SELECT COUNT(*) FROM origens_fundo WHERE company_id = :cid"),
        {"cid": company_id},
    )
    if (r.scalar_one() or 0) > 0:
        return
    for nome, desc, ordem in _DEFAULT_ORIGENS:
        await db.execute(
            text(
                "INSERT INTO origens_fundo (id, company_id, nome, descricao, ordem, is_system, estado) "
                "VALUES (:id, :cid, :nome, :desc, :ordem, TRUE, 'ativo')"
            ),
            {"id": str(uuid4()), "cid": company_id, "nome": nome, "desc": desc, "ordem": ordem},
        )
    await db.commit()


class OrigemCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=80)
    descricao: Optional[str] = Field(None, max_length=255)
    ordem: int = 0
    estado: str = Field(default="ativo", pattern="^(ativo|inativo)$")


class OrigemUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=80)
    descricao: Optional[str] = Field(None, max_length=255)
    ordem: Optional[int] = None
    estado: Optional[str] = Field(None, pattern="^(ativo|inativo)$")


@router.get("")
async def listar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _ensure_defaults(db, str(current_user.company_id))
    r = await db.execute(
        select(OrigemFundoModel)
        .where(OrigemFundoModel.company_id == str(current_user.company_id))
        .order_by(OrigemFundoModel.ordem, OrigemFundoModel.nome)
    )
    return [
        {
            "id": str(o.id),
            "nome": o.nome,
            "descricao": o.descricao,
            "ordem": o.ordem,
            "is_system": o.is_system,
            "estado": o.estado,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in r.scalars().all()
    ]


@router.post("", status_code=201)
async def criar(
    req: Request,
    body: OrigemCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # Unicidade por empresa
    ex = await db.execute(
        select(OrigemFundoModel).where(
            OrigemFundoModel.company_id == str(current_user.company_id),
            OrigemFundoModel.nome == body.nome,
        )
    )
    if ex.scalar_one_or_none():
        raise HTTPException(409, "Já existe uma origem com este nome")

    o = OrigemFundoModel(
        id=uuid4(),
        company_id=str(current_user.company_id),
        nome=body.nome,
        descricao=body.descricao,
        ordem=body.ordem,
        estado=body.estado,
        is_system=False,
    )
    db.add(o)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "origem_fundo", o.id,
        dados_novos=body.model_dump(),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"id": str(o.id), "nome": o.nome}


@router.put("/{id}")
async def atualizar(
    id: UUID,
    req: Request,
    body: OrigemUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    r = await db.execute(select(OrigemFundoModel).where(OrigemFundoModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.company_id != str(current_user.company_id):
        raise HTTPException(404, "Origem não encontrada")
    if o.is_system and body.nome and body.nome != o.nome:
        raise HTTPException(400, "Origens de sistema não podem ser renomeadas")
    ant = {"nome": o.nome, "descricao": o.descricao, "ordem": o.ordem, "estado": o.estado}
    if body.nome is not None and not o.is_system:
        o.nome = body.nome
    if body.descricao is not None:
        o.descricao = body.descricao
    if body.ordem is not None:
        o.ordem = body.ordem
    if body.estado is not None:
        o.estado = body.estado
    o.updated_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizado", "origem_fundo", id,
        dados_anteriores=ant,
        dados_novos=body.model_dump(exclude_none=True),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"id": str(o.id), "nome": o.nome}


@router.delete("/{id}", status_code=204)
async def eliminar(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    r = await db.execute(select(OrigemFundoModel).where(OrigemFundoModel.id == id))
    o = r.scalar_one_or_none()
    if not o or o.company_id != str(current_user.company_id):
        raise HTTPException(404, "Origem não encontrada")
    if o.is_system:
        raise HTTPException(400, "Origens de sistema não podem ser eliminadas (apenas desactivadas)")
    nome = o.nome
    await db.delete(o)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "eliminado", "origem_fundo", id,
        dados_anteriores={"nome": nome},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


__all__ = ["router"]
