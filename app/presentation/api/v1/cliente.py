from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
from datetime import datetime

from app.application.dtos import ClienteCreateDTO, ClienteUpdateDTO, ClienteResponseDTO
from app.infrastructure.database import get_db
from app.infrastructure.repositories import ClienteRepository
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.audit import write_audit
from app.domain.entities import Cliente, User

router = APIRouter()


def _cli_dict(c) -> dict:
    return {
        "id": str(c.id),
        "nome": c.nome,
        "nif": c.nif,
        "telefone": c.telefone,
        "email": c.email,
        "endereco": c.endereco,
        "estado": c.estado,
        "fornecedor_id": str(c.fornecedor_id) if c.fornecedor_id else None,
    }


@router.get("", response_model=List[ClienteResponseDTO])
async def list_clientes(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    repo = ClienteRepository(db)
    return await repo.get_all(current_user.company_id)


@router.get("/{id}", response_model=ClienteResponseDTO)
async def get_cliente(id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    return c


@router.post("", response_model=ClienteResponseDTO, status_code=201)
async def create_cliente(
    req: Request,
    body: ClienteCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ClienteRepository(db)
    existing = await repo.get_by_nif(current_user.company_id, body.nif)
    if existing:
        raise HTTPException(409, "Cliente com este NIF já existe")
    entity = Cliente(
        company_id=current_user.company_id,
        nome=body.nome, nif=body.nif,
        telefone=body.telefone or "", email=body.email or "",
        endereco=body.endereco or "", estado=body.estado,
    )
    created = await repo.create(entity)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "cliente", created.id,
        dados_novos=_cli_dict(created),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return created


@router.put("/{id}", response_model=ClienteResponseDTO)
async def update_cliente(
    id: UUID,
    req: Request,
    body: ClienteUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    dados_ant = _cli_dict(c)
    if body.nome is not None: c.nome = body.nome
    if body.nif is not None: c.nif = body.nif
    if body.telefone is not None: c.telefone = body.telefone
    if body.email is not None: c.email = body.email
    if body.endereco is not None: c.endereco = body.endereco
    if body.estado is not None: c.estado = body.estado
    c.updated_at = datetime.utcnow()
    updated = await repo.update(id, c)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizado", "cliente", id,
        dados_anteriores=dados_ant,
        dados_novos=_cli_dict(updated),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return updated


@router.delete("/{id}", status_code=204)
async def delete_cliente(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    dados_ant = _cli_dict(c)
    await repo.delete(id)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "eliminado", "cliente", id,
        dados_anteriores=dados_ant,
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


@router.post("/{id}/tornar-fornecedor", response_model=dict)
async def tornar_cliente_fornecedor(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cria um Fornecedor espelho do Cliente e estabelece a ponte 1↔1."""
    from app.infrastructure.repositories import FornecedorRepository
    from app.domain.entities import Fornecedor as FornecedorEntity
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    if c.fornecedor_id:
        raise HTTPException(400, "Este cliente já está vinculado a um fornecedor")

    f_repo = FornecedorRepository(db)
    existente = await f_repo.get_by_nif(c.nif)
    if existente and existente.company_id == current_user.company_id:
        c.fornecedor_id = str(existente.id)
        existente.cliente_id = str(c.id)
        await f_repo.update(existente.id, existente)
        await repo.update(id, c)
        fornecedor_id = existente.id
    else:
        novo = FornecedorEntity(
            company_id=current_user.company_id, nome=c.nome, nif=c.nif,
            telefone=c.telefone or "", email=c.email or "", endereco=c.endereco or "",
            estado="ativo", cliente_id=str(c.id),
        )
        criado = await f_repo.create(novo)
        c.fornecedor_id = str(criado.id)
        await repo.update(id, c)
        fornecedor_id = criado.id

    await write_audit(
        db, current_user.id, current_user.company_id,
        "vinculado_fornecedor", "cliente", id,
        dados_novos={"fornecedor_id": str(fornecedor_id), "nome": c.nome, "nif": c.nif},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"fornecedor_id": str(fornecedor_id), "cliente_id": str(id)}


__all__ = ["router"]
