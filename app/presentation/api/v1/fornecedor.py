from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
from app.application.dtos import (
    FornecedorCreateDTO,
    FornecedorUpdateDTO,
    FornecedorResponseDTO,
)
from app.infrastructure.database import get_db
from app.infrastructure.repositories import FornecedorRepository
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.audit import write_audit
from app.domain.entities import Fornecedor, User
from datetime import datetime

router = APIRouter()


def _forn_dict(f) -> dict:
    return {
        "id": str(f.id),
        "nome": f.nome,
        "nif": f.nif,
        "telefone": f.telefone,
        "email": f.email,
        "endereco": f.endereco,
        "estado": f.estado,
        "tipo_pessoa": f.tipo_pessoa,
    }


@router.get("", response_model=List[FornecedorResponseDTO])
async def list_fornecedores(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FornecedorRepository(db)
    fornecedores = await repo.get_all(current_user.company_id)
    return fornecedores


@router.get("/{id}", response_model=FornecedorResponseDTO)
async def get_fornecedor(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FornecedorRepository(db)
    fornecedor = await repo.get_by_id(id)
    if not fornecedor or fornecedor.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor não encontrado")
    return fornecedor


@router.post("", response_model=FornecedorResponseDTO, status_code=status.HTTP_201_CREATED)
async def create_fornecedor(
    req: Request,
    body: FornecedorCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FornecedorRepository(db)
    existing = await repo.get_by_nif(body.nif)
    if existing and existing.company_id == current_user.company_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Fornecedor com este NIF já existe")

    fornecedor = Fornecedor(
        company_id=current_user.company_id,
        nome=body.nome,
        nif=body.nif,
        telefone=body.telefone,
        email=body.email,
        endereco=body.endereco,
        estado=body.estado,
        tipo_pessoa=body.tipo_pessoa,
    )
    created = await repo.create(fornecedor)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "fornecedor", created.id,
        dados_novos=_forn_dict(created),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return created


@router.put("/{id}", response_model=FornecedorResponseDTO)
async def update_fornecedor(
    id: UUID,
    req: Request,
    body: FornecedorUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FornecedorRepository(db)
    fornecedor = await repo.get_by_id(id)
    if not fornecedor or fornecedor.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor não encontrado")

    dados_ant = _forn_dict(fornecedor)

    if body.nome is not None:
        fornecedor.nome = body.nome
    if body.nif is not None:
        fornecedor.nif = body.nif
    if body.telefone is not None:
        fornecedor.telefone = body.telefone
    if body.email is not None:
        fornecedor.email = body.email
    if body.endereco is not None:
        fornecedor.endereco = body.endereco
    if body.estado is not None:
        fornecedor.estado = body.estado
    if body.tipo_pessoa is not None:
        fornecedor.tipo_pessoa = body.tipo_pessoa
    fornecedor.updated_at = datetime.utcnow()

    updated = await repo.update(id, fornecedor)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizado", "fornecedor", id,
        dados_anteriores=dados_ant,
        dados_novos=_forn_dict(updated),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return updated


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fornecedor(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FornecedorRepository(db)
    fornecedor = await repo.get_by_id(id)
    if not fornecedor or fornecedor.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor não encontrado")

    dados_ant = _forn_dict(fornecedor)
    await repo.delete(id)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "eliminado", "fornecedor", id,
        dados_anteriores=dados_ant,
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


@router.post("/{id}/tornar-cliente", response_model=dict)
async def tornar_fornecedor_cliente(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cria um Cliente espelho do Fornecedor e estabelece a ponte 1↔1."""
    from app.infrastructure.repositories import ClienteRepository
    from app.domain.entities import Cliente as ClienteEntity
    repo = FornecedorRepository(db)
    f = await repo.get_by_id(id)
    if not f or f.company_id != current_user.company_id:
        raise HTTPException(404, "Fornecedor não encontrado")
    if f.cliente_id:
        raise HTTPException(400, "Este fornecedor já está vinculado a um cliente")

    cli_repo = ClienteRepository(db)
    existente = await cli_repo.get_by_nif(current_user.company_id, f.nif)
    if existente:
        # Já existe cliente com mesmo NIF — apenas estabelecer ponte
        f.cliente_id = str(existente.id)
        existente.fornecedor_id = str(f.id)
        await cli_repo.update(existente.id, existente)
        await repo.update(id, f)
        cliente_id = existente.id
    else:
        novo = ClienteEntity(
            company_id=current_user.company_id, nome=f.nome, nif=f.nif,
            telefone=f.telefone or "", email=f.email or "", endereco=f.endereco or "",
            estado="ativo", fornecedor_id=str(f.id),
        )
        criado = await cli_repo.create(novo)
        f.cliente_id = str(criado.id)
        await repo.update(id, f)
        cliente_id = criado.id

    await write_audit(
        db, current_user.id, current_user.company_id,
        "vinculado_cliente", "fornecedor", id,
        dados_novos={"cliente_id": str(cliente_id), "nome": f.nome, "nif": f.nif},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"cliente_id": str(cliente_id), "fornecedor_id": str(id)}


__all__ = ["router"]
