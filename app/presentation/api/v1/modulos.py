"""CRUD de Módulos e Páginas (catálogo do sistema, gerido por admin)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.infrastructure.database import get_db
from app.infrastructure.database.models import ModuloModel, PaginaModel
from app.infrastructure.auth.dependencies import get_current_user, require_admin
from app.infrastructure.audit import write_audit
from app.domain.entities import User

router = APIRouter()


# ────────────────────────────────────────────────────────────────────
# DTOs
# ────────────────────────────────────────────────────────────────────

class ModuloCreateDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=80)
    descricao: Optional[str] = Field(None, max_length=255)
    icone: Optional[str] = Field(None, max_length=50)
    ordem: int = 0


class ModuloUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=80)
    descricao: Optional[str] = Field(None, max_length=255)
    icone: Optional[str] = Field(None, max_length=50)
    ordem: Optional[int] = None


class PaginaCreateDTO(BaseModel):
    modulo_id: UUID
    nome: str = Field(..., min_length=1, max_length=80)
    descricao: Optional[str] = Field(None, max_length=255)
    href: Optional[str] = Field(None, max_length=150)
    icone: Optional[str] = Field(None, max_length=50)
    ordem: int = 0


class PaginaUpdateDTO(BaseModel):
    modulo_id: Optional[UUID] = None
    nome: Optional[str] = Field(None, min_length=1, max_length=80)
    descricao: Optional[str] = Field(None, max_length=255)
    href: Optional[str] = Field(None, max_length=150)
    icone: Optional[str] = Field(None, max_length=50)
    ordem: Optional[int] = None


# ────────────────────────────────────────────────────────────────────
# Módulos
# ────────────────────────────────────────────────────────────────────

@router.get("/modulos")
async def listar_modulos(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    r = await db.execute(select(ModuloModel).order_by(ModuloModel.ordem, ModuloModel.nome))
    out = []
    for m in r.scalars().all():
        # contar páginas
        c_r = await db.execute(
            text("SELECT COUNT(*) FROM paginas WHERE modulo_id::text = :mid"),
            {"mid": str(m.id)},
        )
        n_pag = c_r.scalar_one() or 0
        out.append({
            "id": str(m.id),
            "nome": m.nome,
            "descricao": m.descricao,
            "icone": m.icone,
            "ordem": m.ordem,
            "is_system": m.is_system,
            "n_paginas": n_pag,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return out


@router.post("/modulos", status_code=201)
async def criar_modulo(req: Request, body: ModuloCreateDTO, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    exists = await db.execute(select(ModuloModel).where(ModuloModel.nome == body.nome))
    if exists.scalar_one_or_none():
        raise HTTPException(409, "Já existe um módulo com este nome")
    m = ModuloModel(id=uuid4(), nome=body.nome, descricao=body.descricao, icone=body.icone, ordem=body.ordem, is_system=False)
    db.add(m)
    await db.flush()
    await write_audit(db, current_user.id, current_user.company_id, "criado", "modulo", m.id, dados_novos=body.model_dump(), ip_address=req.client.host if req.client else None)
    await db.commit()
    return {"id": str(m.id), "nome": m.nome}


@router.put("/modulos/{id}")
async def atualizar_modulo(id: UUID, req: Request, body: ModuloUpdateDTO, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    r = await db.execute(select(ModuloModel).where(ModuloModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Módulo não encontrado")
    ant = {"nome": m.nome, "descricao": m.descricao, "icone": m.icone, "ordem": m.ordem}
    if body.nome is not None: m.nome = body.nome
    if body.descricao is not None: m.descricao = body.descricao
    if body.icone is not None: m.icone = body.icone
    if body.ordem is not None: m.ordem = body.ordem
    m.updated_at = datetime.utcnow()
    await write_audit(db, current_user.id, current_user.company_id, "atualizado", "modulo", id, dados_anteriores=ant, dados_novos=body.model_dump(exclude_none=True), ip_address=req.client.host if req.client else None)
    await db.commit()
    return {"id": str(m.id), "nome": m.nome}


@router.delete("/modulos/{id}", status_code=204)
async def eliminar_modulo(id: UUID, req: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    r = await db.execute(select(ModuloModel).where(ModuloModel.id == id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Módulo não encontrado")
    if m.is_system:
        raise HTTPException(400, "Não é possível eliminar módulos de sistema")
    # Verificar páginas associadas
    pag_r = await db.execute(text("SELECT 1 FROM paginas WHERE modulo_id::text = :mid LIMIT 1"), {"mid": str(id)})
    if pag_r.scalar_one_or_none():
        raise HTTPException(400, "Existem páginas neste módulo. Reatribua-as ou elimine-as primeiro.")
    nome = m.nome
    await db.delete(m)
    await write_audit(db, current_user.id, current_user.company_id, "eliminado", "modulo", id, dados_anteriores={"nome": nome}, ip_address=req.client.host if req.client else None)
    await db.commit()


# ────────────────────────────────────────────────────────────────────
# Páginas
# ────────────────────────────────────────────────────────────────────

@router.get("/paginas")
async def listar_paginas(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    r = await db.execute(select(PaginaModel).order_by(PaginaModel.ordem, PaginaModel.nome))
    paginas = r.scalars().all()
    # mapear modulos
    mods_r = await db.execute(select(ModuloModel))
    mod_map = {str(m.id): m.nome for m in mods_r.scalars().all()}
    out = []
    for p in paginas:
        c_r = await db.execute(text("SELECT COUNT(*) FROM permissoes WHERE pagina_id::text = :pid"), {"pid": str(p.id)})
        n_perm = c_r.scalar_one() or 0
        out.append({
            "id": str(p.id),
            "modulo_id": str(p.modulo_id) if p.modulo_id else None,
            "modulo_nome": mod_map.get(str(p.modulo_id) or ""),
            "nome": p.nome,
            "descricao": p.descricao,
            "href": p.href,
            "icone": p.icone,
            "ordem": p.ordem,
            "is_system": p.is_system,
            "n_permissoes": n_perm,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return out


@router.post("/paginas", status_code=201)
async def criar_pagina(req: Request, body: PaginaCreateDTO, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    # Verificar módulo existe
    m_r = await db.execute(select(ModuloModel).where(ModuloModel.id == body.modulo_id))
    if not m_r.scalar_one_or_none():
        raise HTTPException(400, "Módulo inválido")
    # Único por módulo
    exists = await db.execute(text("SELECT 1 FROM paginas WHERE modulo_id::text = :mid AND nome = :nome LIMIT 1"), {"mid": str(body.modulo_id), "nome": body.nome})
    if exists.scalar_one_or_none():
        raise HTTPException(409, "Já existe uma página com este nome neste módulo")
    p = PaginaModel(id=uuid4(), modulo_id=str(body.modulo_id), nome=body.nome, descricao=body.descricao, href=body.href, icone=body.icone, ordem=body.ordem, is_system=False)
    db.add(p)
    await db.flush()
    await write_audit(db, current_user.id, current_user.company_id, "criado", "pagina", p.id, dados_novos={**body.model_dump(), "modulo_id": str(body.modulo_id)}, ip_address=req.client.host if req.client else None)
    await db.commit()
    return {"id": str(p.id), "nome": p.nome}


@router.put("/paginas/{id}")
async def atualizar_pagina(id: UUID, req: Request, body: PaginaUpdateDTO, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    r = await db.execute(select(PaginaModel).where(PaginaModel.id == id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Página não encontrada")
    ant = {"nome": p.nome, "modulo_id": str(p.modulo_id) if p.modulo_id else None, "href": p.href, "icone": p.icone, "ordem": p.ordem}
    if body.modulo_id is not None: p.modulo_id = str(body.modulo_id)
    if body.nome is not None: p.nome = body.nome
    if body.descricao is not None: p.descricao = body.descricao
    if body.href is not None: p.href = body.href
    if body.icone is not None: p.icone = body.icone
    if body.ordem is not None: p.ordem = body.ordem
    p.updated_at = datetime.utcnow()
    await write_audit(db, current_user.id, current_user.company_id, "atualizado", "pagina", id, dados_anteriores=ant, dados_novos=body.model_dump(exclude_none=True), ip_address=req.client.host if req.client else None)
    await db.commit()
    return {"id": str(p.id), "nome": p.nome}


@router.delete("/paginas/{id}", status_code=204)
async def eliminar_pagina(id: UUID, req: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    r = await db.execute(select(PaginaModel).where(PaginaModel.id == id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Página não encontrada")
    if p.is_system:
        raise HTTPException(400, "Não é possível eliminar páginas de sistema")
    # Permissões associadas
    perm_r = await db.execute(text("SELECT 1 FROM permissoes WHERE pagina_id::text = :pid LIMIT 1"), {"pid": str(id)})
    if perm_r.scalar_one_or_none():
        raise HTTPException(400, "Existem permissões nesta página. Mova-as ou elimine-as primeiro.")
    await db.delete(p)
    await write_audit(db, current_user.id, current_user.company_id, "eliminado", "pagina", id, dados_anteriores={"nome": p.nome}, ip_address=req.client.host if req.client else None)
    await db.commit()


# ────────────────────────────────────────────────────────────────────
# CRUD Permissões (admin)
# ────────────────────────────────────────────────────────────────────

class PermissaoCreateDTO(BaseModel):
    codigo: str = Field(..., min_length=3, max_length=80, pattern=r"^[a-z_]+\.[a-z_]+$")
    pagina_id: UUID
    acao: str = Field(..., min_length=2, max_length=50)
    descricao: Optional[str] = Field(None, max_length=255)


class PermissaoUpdateDTO(BaseModel):
    pagina_id: Optional[UUID] = None
    acao: Optional[str] = Field(None, min_length=2, max_length=50)
    descricao: Optional[str] = Field(None, max_length=255)


@router.post("/permissoes", status_code=201)
async def criar_permissao(req: Request, body: PermissaoCreateDTO, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    from app.infrastructure.database.models import PermissaoModel
    # validar página
    pag_r = await db.execute(select(PaginaModel).where(PaginaModel.id == body.pagina_id))
    pag = pag_r.scalar_one_or_none()
    if not pag:
        raise HTTPException(400, "Página inválida")
    # Obter nome do módulo para denormalização
    mod_nome = None
    if pag.modulo_id:
        m_r = await db.execute(select(ModuloModel.nome).where(ModuloModel.id == pag.modulo_id))
        mod_nome = m_r.scalar_one_or_none()
    # único codigo
    ex = await db.execute(select(PermissaoModel).where(PermissaoModel.codigo == body.codigo))
    if ex.scalar_one_or_none():
        raise HTTPException(409, "Código de permissão já existe")
    p = PermissaoModel(id=uuid4(), codigo=body.codigo, modulo=mod_nome, menu=pag.nome, acao=body.acao, descricao=body.descricao, pagina_id=str(body.pagina_id))
    db.add(p)
    await db.flush()
    await write_audit(db, current_user.id, current_user.company_id, "criado", "permissao", p.id, dados_novos={"codigo": body.codigo, "pagina": pag.nome, "acao": body.acao}, ip_address=req.client.host if req.client else None)
    await db.commit()
    return {"id": str(p.id), "codigo": p.codigo}


@router.put("/permissoes/{id}")
async def atualizar_permissao(id: UUID, req: Request, body: PermissaoUpdateDTO, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    from app.infrastructure.database.models import PermissaoModel
    r = await db.execute(select(PermissaoModel).where(PermissaoModel.id == id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Permissão não encontrada")
    ant = {"codigo": p.codigo, "acao": p.acao, "pagina_id": p.pagina_id}
    if body.pagina_id is not None:
        pag_r = await db.execute(select(PaginaModel).where(PaginaModel.id == body.pagina_id))
        pag = pag_r.scalar_one_or_none()
        if not pag:
            raise HTTPException(400, "Página inválida")
        p.pagina_id = str(body.pagina_id)
        p.menu = pag.nome
        if pag.modulo_id:
            m_r = await db.execute(select(ModuloModel.nome).where(ModuloModel.id == pag.modulo_id))
            p.modulo = m_r.scalar_one_or_none()
    if body.acao is not None: p.acao = body.acao
    if body.descricao is not None: p.descricao = body.descricao
    await write_audit(db, current_user.id, current_user.company_id, "atualizado", "permissao", id, dados_anteriores=ant, dados_novos=body.model_dump(exclude_none=True), ip_address=req.client.host if req.client else None)
    await db.commit()
    return {"id": str(p.id), "codigo": p.codigo}


@router.delete("/permissoes/{id}", status_code=204)
async def eliminar_permissao(id: UUID, req: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    from app.infrastructure.database.models import PermissaoModel, GrupoPermissaoModel
    from sqlalchemy import delete
    r = await db.execute(select(PermissaoModel).where(PermissaoModel.id == id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Permissão não encontrada")
    # apagar atribuições aos grupos primeiro
    await db.execute(delete(GrupoPermissaoModel).where(GrupoPermissaoModel.permissao_id == id))
    codigo = p.codigo
    await db.delete(p)
    await write_audit(db, current_user.id, current_user.company_id, "eliminado", "permissao", id, dados_anteriores={"codigo": codigo}, ip_address=req.client.host if req.client else None)
    await db.commit()


__all__ = ["router"]
