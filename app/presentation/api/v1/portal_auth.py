"""Autenticação do Portal do Cliente (FrontOffice).

Separada por completo do sistema de Users/RBAC interno — usa
ContaClienteModel e tokens JWT com type distinto (cliente_access/
cliente_refresh), nunca aceites pelas dependencies de colaborador.

Como o portal não tem company_id no pedido (cliente ainda não está
autenticado), o registo associa-se à primeira empresa activa do
sistema — adequado para uma instância single-tenant como esta;
revisitar se o sistema evoluir para multi-tenant público.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.auth import (
    create_cliente_access_token,
    create_cliente_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.infrastructure.auth.dependencies import get_current_cliente
from app.infrastructure.database import get_db
from app.infrastructure.database.models import ClienteModel, ContaClienteModel


router = APIRouter()


class RegistarDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    telefone: Optional[str] = None
    password: str = Field(..., min_length=8)


class LoginDTO(BaseModel):
    email: EmailStr
    password: str


class RefreshDTO(BaseModel):
    refresh_token: str


class TokenResponseDTO(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ContaClienteResponseDTO(BaseModel):
    id: UUID
    cliente_id: str
    email: str
    telefone: Optional[str] = None
    email_verificado: bool

    class Config:
        from_attributes = True


async def _get_company_id_padrao(db: AsyncSession) -> UUID:
    """Instância single-tenant: usa o company_id do primeiro Cliente já
    existente como âncora. Se não houver nenhum, gera um novo — o
    backoffice deve then associar essa empresa nas Configurações."""
    r = await db.execute(select(ClienteModel.company_id).limit(1))
    row = r.first()
    if row:
        return row[0]
    return uuid4()


@router.post("/registar", response_model=TokenResponseDTO, status_code=201)
async def registar(
    body: RegistarDTO,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ContaClienteModel).where(ContaClienteModel.email == body.email))
    if r.scalar_one_or_none():
        raise HTTPException(409, "Já existe uma conta com este email")

    company_id = await _get_company_id_padrao(db)

    cliente = ClienteModel(
        id=uuid4(), company_id=company_id, nome=body.nome, nif="",
        telefone=body.telefone, email=body.email, estado="ativo",
    )
    db.add(cliente)
    await db.flush()

    conta = ContaClienteModel(
        id=uuid4(), company_id=company_id, cliente_id=str(cliente.id),
        email=body.email, telefone=body.telefone,
        hashed_password=hash_password(body.password),
    )
    db.add(conta)
    await db.commit()

    return TokenResponseDTO(
        access_token=create_cliente_access_token(conta.id, company_id),
        refresh_token=create_cliente_refresh_token(conta.id, company_id),
    )


@router.post("/login", response_model=TokenResponseDTO)
async def login(
    body: LoginDTO,
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ContaClienteModel).where(ContaClienteModel.email == body.email))
    conta = r.scalar_one_or_none()
    if not conta or not verify_password(body.password, conta.hashed_password):
        raise HTTPException(401, "Email ou senha incorrectos")
    if not conta.activo:
        raise HTTPException(401, "Conta inactiva")

    return TokenResponseDTO(
        access_token=create_cliente_access_token(conta.id, conta.company_id),
        refresh_token=create_cliente_refresh_token(conta.id, conta.company_id),
    )


@router.post("/refresh", response_model=TokenResponseDTO)
async def refresh(
    body: RefreshDTO,
    db: AsyncSession = Depends(get_db),
):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "cliente_refresh":
        raise HTTPException(401, "Refresh token inválido")

    conta_id = payload.get("sub")
    r = await db.execute(select(ContaClienteModel).where(ContaClienteModel.id == UUID(conta_id)))
    conta = r.scalar_one_or_none()
    if not conta or not conta.activo:
        raise HTTPException(401, "Conta não encontrada ou inactiva")

    return TokenResponseDTO(
        access_token=create_cliente_access_token(conta.id, conta.company_id),
        refresh_token=create_cliente_refresh_token(conta.id, conta.company_id),
    )


@router.get("/me", response_model=ContaClienteResponseDTO)
async def me(
    conta: ContaClienteModel = Depends(get_current_cliente),
):
    return conta


__all__ = ["router"]
