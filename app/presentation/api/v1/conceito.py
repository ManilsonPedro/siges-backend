from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
from app.application.dtos import ConceptoCreateDTO, ConceptoUpdateDTO, ConceptoResponseDTO
from app.infrastructure.database import get_db
from app.infrastructure.repositories import ConceptoRepository
from app.infrastructure.auth.dependencies import get_current_user, require_financeiro
from app.infrastructure.audit import write_audit
from app.domain.entities import User, Conceito

router = APIRouter()


def _conc_dict(c) -> dict:
    return {"id": str(c.id), "nome": c.nome, "descricao": c.descricao, "estado": c.estado}


@router.get("", response_model=List[ConceptoResponseDTO])
async def listar_conceitos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ConceptoRepository(db)
    items = await repo.get_all(current_user.company_id)
    return [_to_dto(c) for c in items]


@router.get("/{id}", response_model=ConceptoResponseDTO)
async def obter_conceito(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ConceptoRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conceito não encontrado")
    return _to_dto(c)


@router.post("", response_model=ConceptoResponseDTO, status_code=status.HTTP_201_CREATED)
async def criar_conceito(
    req: Request,
    body: ConceptoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    repo = ConceptoRepository(db)
    entity = Conceito(
        company_id=current_user.company_id,
        nome=body.nome,
        descricao=body.descricao or "",
        estado=body.estado,
    )
    created = await repo.create(entity)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "conceito", created.id,
        dados_novos=_conc_dict(created),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return _to_dto(created)


@router.put("/{id}", response_model=ConceptoResponseDTO)
async def atualizar_conceito(
    id: UUID,
    req: Request,
    body: ConceptoUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    repo = ConceptoRepository(db)
    existing = await repo.get_by_id(id)
    if not existing or existing.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conceito não encontrado")

    dados_ant = _conc_dict(existing)
    updated_entity = Conceito(
        id=existing.id,
        company_id=existing.company_id,
        nome=body.nome if body.nome is not None else existing.nome,
        descricao=body.descricao if body.descricao is not None else existing.descricao,
        estado=body.estado if body.estado is not None else existing.estado,
    )
    updated = await repo.update(id, updated_entity)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizado", "conceito", id,
        dados_anteriores=dados_ant,
        dados_novos=_conc_dict(updated),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return _to_dto(updated)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_conceito(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    repo = ConceptoRepository(db)
    existing = await repo.get_by_id(id)
    if not existing or existing.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conceito não encontrado")

    dados_ant = _conc_dict(existing)
    await repo.delete(id)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "eliminado", "conceito", id,
        dados_anteriores=dados_ant,
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


def _to_dto(c: Conceito) -> ConceptoResponseDTO:
    return ConceptoResponseDTO(
        id=c.id, company_id=c.company_id, nome=c.nome, descricao=c.descricao,
        estado=c.estado, created_at=c.created_at, updated_at=c.updated_at, deleted_at=c.deleted_at,
    )


__all__ = ["router"]
