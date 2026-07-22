"""Endpoints para permissões e grupos."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, func, text
from uuid import UUID, uuid4
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from app.infrastructure.database import get_db
from app.infrastructure.database.models import PermissaoModel, GrupoModel, GrupoPermissaoModel, UserModel
from app.infrastructure.auth.dependencies import get_current_user, require_admin
from app.infrastructure.audit import write_audit
from app.domain.entities import User

router = APIRouter()


# ────────────────────────────────────────────────────────────────────
# Permissões (catálogo — read-only)
# ────────────────────────────────────────────────────────────────────

@router.get("/permissoes")
async def listar_permissoes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(PermissaoModel).order_by(PermissaoModel.modulo, PermissaoModel.menu, PermissaoModel.acao))
    return [
        {
            "id": str(p.id),
            "codigo": p.codigo,
            "modulo": p.modulo,
            "menu": p.menu,
            "acao": p.acao,
            "descricao": p.descricao,
        }
        for p in r.scalars().all()
    ]


# ────────────────────────────────────────────────────────────────────
# Grupos
# ────────────────────────────────────────────────────────────────────

class GrupoCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    descricao: Optional[str] = Field(None, max_length=255)


class GrupoUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=60)
    descricao: Optional[str] = Field(None, max_length=255)


class GrupoPermissoesDTO(BaseModel):
    permissao_ids: List[UUID] = []


@router.get("/grupos")
async def listar_grupos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(GrupoModel).where(GrupoModel.company_id == current_user.company_id).order_by(GrupoModel.is_system.desc(), GrupoModel.nome)
    )
    grupos = r.scalars().all()

    # Contar utilizadores e permissões por grupo (SQL textual para evitar mismatch UUID/varchar)
    out = []
    for g in grupos:
        gid_str = str(g.id)
        nperm_r = await db.execute(
            text("SELECT COUNT(*) FROM grupo_permissoes WHERE grupo_id::text = :gid"),
            {"gid": gid_str},
        )
        n_perm = nperm_r.scalar_one() or 0
        nuser_r = await db.execute(
            text("SELECT COUNT(*) FROM users WHERE grupo_id::text = :gid AND deleted_at IS NULL"),
            {"gid": gid_str},
        )
        n_user = nuser_r.scalar_one() or 0
        out.append({
            "id": gid_str,
            "nome": g.nome,
            "descricao": g.descricao,
            "is_system": g.is_system,
            "n_permissoes": n_perm,
            "n_utilizadores": n_user,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        })
    return out


@router.post("/grupos", status_code=201)
async def criar_grupo(
    req: Request,
    body: GrupoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # Nome único por empresa
    exist_r = await db.execute(
        select(GrupoModel).where(GrupoModel.company_id == current_user.company_id, GrupoModel.nome == body.nome)
    )
    if exist_r.scalar_one_or_none():
        raise HTTPException(409, "Já existe um grupo com este nome")

    g = GrupoModel(
        id=uuid4(),
        company_id=current_user.company_id,
        nome=body.nome,
        descricao=body.descricao,
        is_system=False,
    )
    db.add(g)
    await db.flush()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "grupo", g.id,
        dados_novos={"nome": g.nome, "descricao": g.descricao},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"id": str(g.id), "nome": g.nome, "descricao": g.descricao, "is_system": False}


@router.put("/grupos/{id}")
async def atualizar_grupo(
    id: UUID,
    req: Request,
    body: GrupoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    r = await db.execute(select(GrupoModel).where(GrupoModel.id == id))
    g = r.scalar_one_or_none()
    if not g or g.company_id != current_user.company_id:
        raise HTTPException(404, "Grupo não encontrado")
    if g.is_system and body.nome and body.nome != g.nome:
        raise HTTPException(400, "Não é possível renomear grupos de sistema")
    ant = {"nome": g.nome, "descricao": g.descricao}
    if body.nome is not None and not g.is_system:
        g.nome = body.nome
    if body.descricao is not None:
        g.descricao = body.descricao
    g.updated_at = datetime.utcnow()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizado", "grupo", id,
        dados_anteriores=ant,
        dados_novos={"nome": g.nome, "descricao": g.descricao},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"id": str(g.id), "nome": g.nome, "descricao": g.descricao, "is_system": g.is_system}


@router.delete("/grupos/{id}", status_code=204)
async def eliminar_grupo(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    r = await db.execute(select(GrupoModel).where(GrupoModel.id == id))
    g = r.scalar_one_or_none()
    if not g or g.company_id != current_user.company_id:
        raise HTTPException(404, "Grupo não encontrado")
    if g.is_system:
        raise HTTPException(400, "Não é possível eliminar grupos de sistema")
    # Verificar se há utilizadores neste grupo
    u_r = await db.execute(
        text("SELECT 1 FROM users WHERE grupo_id::text = :gid LIMIT 1"),
        {"gid": str(id)},
    )
    if u_r.scalar_one_or_none():
        raise HTTPException(400, "Existem utilizadores neste grupo. Reatribua-os antes de eliminar.")
    await db.execute(delete(GrupoPermissaoModel).where(GrupoPermissaoModel.grupo_id == id))
    await db.delete(g)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "eliminado", "grupo", id,
        dados_anteriores={"nome": g.nome},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


@router.get("/grupos/{id}/permissoes")
async def listar_permissoes_do_grupo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    g_r = await db.execute(select(GrupoModel).where(GrupoModel.id == id))
    g = g_r.scalar_one_or_none()
    if not g or g.company_id != current_user.company_id:
        raise HTTPException(404, "Grupo não encontrado")
    r = await db.execute(
        select(GrupoPermissaoModel.permissao_id).where(GrupoPermissaoModel.grupo_id == id)
    )
    return [str(pid) for pid in r.scalars().all()]


@router.put("/grupos/{id}/permissoes")
async def atualizar_permissoes_do_grupo(
    id: UUID,
    req: Request,
    body: GrupoPermissoesDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    g_r = await db.execute(select(GrupoModel).where(GrupoModel.id == id))
    g = g_r.scalar_one_or_none()
    if not g or g.company_id != current_user.company_id:
        raise HTTPException(404, "Grupo não encontrado")
    # Apagar tudo e inserir
    await db.execute(delete(GrupoPermissaoModel).where(GrupoPermissaoModel.grupo_id == id))
    for pid in body.permissao_ids:
        db.add(GrupoPermissaoModel(grupo_id=id, permissao_id=pid))
    await write_audit(
        db, current_user.id, current_user.company_id,
        "permissoes_atualizadas", "grupo", id,
        dados_novos={"n_permissoes": len(body.permissao_ids), "grupo_nome": g.nome},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"grupo_id": str(id), "n_permissoes": len(body.permissao_ids)}


# ────────────────────────────────────────────────────────────────────
# Atribuir grupo a utilizador
# ────────────────────────────────────────────────────────────────────

class UserGrupoDTO(BaseModel):
    grupo_id: Optional[UUID] = None


@router.put("/users/{user_id}/grupo")
async def atribuir_grupo_user(
    user_id: UUID,
    req: Request,
    body: UserGrupoDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # Verificar user (cast a varchar para evitar mismatch UUID/varchar)
    u_r = await db.execute(
        text("SELECT grupo_id, company_id FROM users WHERE id::text = :uid"),
        {"uid": str(user_id)},
    )
    row = u_r.first()
    if not row:
        raise HTTPException(404, "Utilizador não encontrado")
    ant_grupo, company_id = row[0], row[1]
    if str(company_id) != str(current_user.company_id):
        raise HTTPException(404, "Utilizador não encontrado")

    if body.grupo_id:
        g_r = await db.execute(
            text("SELECT 1 FROM grupos WHERE id::text = :gid AND company_id::text = :cid"),
            {"gid": str(body.grupo_id), "cid": str(current_user.company_id)},
        )
        if not g_r.scalar_one_or_none():
            raise HTTPException(400, "Grupo inválido")
        await db.execute(
            text("UPDATE users SET grupo_id = :gid, updated_at = NOW() WHERE id::text = :uid"),
            {"gid": str(body.grupo_id), "uid": str(user_id)},
        )
    else:
        await db.execute(
            text("UPDATE users SET grupo_id = NULL, updated_at = NOW() WHERE id::text = :uid"),
            {"uid": str(user_id)},
        )
    await write_audit(
        db, current_user.id, current_user.company_id,
        "grupo_atribuido", "user", user_id,
        dados_anteriores={"grupo_id": str(ant_grupo) if ant_grupo else None},
        dados_novos={"grupo_id": str(body.grupo_id) if body.grupo_id else None},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"user_id": str(user_id), "grupo_id": str(body.grupo_id) if body.grupo_id else None}


class UsersToGrupoDTO(BaseModel):
    user_ids: List[UUID] = []


@router.get("/grupos/{id}/utilizadores")
async def listar_utilizadores_do_grupo(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    g_r = await db.execute(select(GrupoModel).where(GrupoModel.id == id))
    g = g_r.scalar_one_or_none()
    if not g or g.company_id != current_user.company_id:
        raise HTTPException(404, "Grupo não encontrado")
    r = await db.execute(
        text("SELECT id, full_name, email FROM users WHERE grupo_id::text = :gid AND deleted_at IS NULL"),
        {"gid": str(id)},
    )
    return [
        {"id": str(row[0]), "full_name": row[1], "email": row[2]}
        for row in r.all()
    ]


@router.post("/grupos/{id}/utilizadores")
async def adicionar_utilizadores_grupo(
    id: UUID,
    req: Request,
    body: UsersToGrupoDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    g_r = await db.execute(
        text("SELECT nome FROM grupos WHERE id::text = :gid AND company_id::text = :cid"),
        {"gid": str(id), "cid": str(current_user.company_id)},
    )
    g_nome = g_r.scalar_one_or_none()
    if not g_nome:
        raise HTTPException(404, "Grupo não encontrado")
    added = 0
    for uid in body.user_ids:
        res = await db.execute(
            text(
                "UPDATE users SET grupo_id = :gid, updated_at = NOW() "
                "WHERE id::text = :uid AND company_id::text = :cid"
            ),
            {"gid": str(id), "uid": str(uid), "cid": str(current_user.company_id)},
        )
        if (res.rowcount or 0) > 0:
            added += 1
    g = type("G", (), {"nome": g_nome})()
    await write_audit(
        db, current_user.id, current_user.company_id,
        "utilizadores_adicionados", "grupo", id,
        dados_novos={"grupo_nome": g.nome, "n_utilizadores": added, "user_ids": [str(u) for u in body.user_ids]},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"grupo_id": str(id), "adicionados": added}


__all__ = ["router"]
