from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import Optional
from decimal import Decimal


# USER DTOs
class UserBaseDTO(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)


class UserCreateDTO(UserBaseDTO):
    password: Optional[str] = Field(None, min_length=6)  # opcional: se omitido, usa-se o email


class UserResponseDTO(UserBaseDTO):
    id: UUID
    company_id: UUID
    is_active: bool
    is_superadmin: bool = False
    must_change_password: bool = False
    grupo_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# FORNECEDOR DTOs
class FornecedorBaseDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=255)
    nif: str = Field(..., min_length=5, max_length=20)
    telefone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    endereco: Optional[str] = Field(None, max_length=500)
    estado: str = Field(default="ativo", pattern="^(ativo|inativo|suspenso)$")
    tipo_pessoa: Optional[str] = Field(None, pattern="^(singular|empresa)$")


class FornecedorCreateDTO(FornecedorBaseDTO):
    pass


class FornecedorUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=255)
    nif: Optional[str] = Field(None, min_length=5, max_length=20)
    telefone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    endereco: Optional[str] = Field(None, max_length=500)
    estado: Optional[str] = Field(None, pattern="^(ativo|inativo|suspenso)$")
    tipo_pessoa: Optional[str] = Field(None, pattern="^(singular|empresa)$")


class FornecedorResponseDTO(FornecedorBaseDTO):
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    cliente_id: Optional[UUID] = None

    class Config:
        from_attributes = True


# CLIENTE DTOs (espelho de Fornecedor)
class ClienteBaseDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=255)
    nif: str = Field(..., min_length=5, max_length=20)
    telefone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    endereco: Optional[str] = Field(None, max_length=500)
    estado: str = Field(default="ativo", pattern="^(ativo|inativo|suspenso)$")


class ClienteCreateDTO(ClienteBaseDTO):
    pass


class ClienteUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=255)
    nif: Optional[str] = Field(None, min_length=5, max_length=20)
    telefone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    endereco: Optional[str] = Field(None, max_length=500)
    estado: Optional[str] = Field(None, pattern="^(ativo|inativo|suspenso)$")


class ClienteResponseDTO(ClienteBaseDTO):
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    fornecedor_id: Optional[UUID] = None

    class Config:
        from_attributes = True


# CONCEITO DTOs
class ConceptoBaseDTO(BaseModel):
    nome: str = Field(..., min_length=1, max_length=255)
    descricao: Optional[str] = Field(None, max_length=500)
    estado: str = Field(default="ativo", pattern="^(ativo|inativo)$")


class ConceptoCreateDTO(ConceptoBaseDTO):
    pass


class ConceptoUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=255)
    descricao: Optional[str] = Field(None, max_length=500)
    estado: Optional[str] = Field(None, pattern="^(ativo|inativo)$")


class ConceptoResponseDTO(ConceptoBaseDTO):
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# FUNDO DTOs
class FundoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    tipo: str
    data: Optional[datetime] = None
    descricao: Optional[str] = None
    valor_disponivel: Decimal
    acumulado: Decimal
    saldo_atual: Decimal
    total_entradas: Decimal = Decimal("0")
    total_saidas: Decimal = Decimal("0")
    observacao: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FundoUpdateDTO(BaseModel):
    tipo: str = Field(..., pattern="^(BCS|BFA)$")
    valor_disponivel: Decimal = Field(..., ge=0)
    observacao: Optional[str] = None
    origem: Optional[str] = Field(None, max_length=80)


# MOVIMENTO DTOs
class MovimentoBaseDTO(BaseModel):
    data: datetime
    fornecedor_id: Optional[UUID] = None  # obrigatório se tipo=saida
    cliente_id: Optional[UUID] = None     # obrigatório se tipo=entrada
    conceito_id: UUID
    valor: Decimal = Field(..., gt=0)
    tipo_movimento: str = Field(..., pattern="^(entrada|saida)$")
    fundo_tipo: str = Field(default="BCS", pattern="^(BCS|BFA)$")
    estado_pagamento: str = Field(default="pendente")
    fatura_proforma: Optional[str] = Field(None, max_length=50)
    fatura_recibo: Optional[str] = Field(None, max_length=50)
    observacoes: Optional[str] = Field(None, max_length=500)


class MovimentoCreateDTO(MovimentoBaseDTO):
    pass


class MovimentoUpdateDTO(BaseModel):
    data: Optional[datetime] = None
    fornecedor_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None
    conceito_id: Optional[UUID] = None
    valor: Optional[Decimal] = Field(None, gt=0)
    tipo_movimento: Optional[str] = Field(None, pattern="^(entrada|saida)$")
    estado_pagamento: Optional[str] = None
    fundo_tipo: Optional[str] = Field(None, pattern="^(BCS|BFA)$")
    fatura_proforma: Optional[str] = Field(None, max_length=50)
    fatura_recibo: Optional[str] = Field(None, max_length=50)
    observacoes: Optional[str] = Field(None, max_length=500)


class MovimentoResponseDTO(MovimentoBaseDTO):
    valor: Decimal
    id: UUID
    company_id: UUID
    codigo: Optional[str] = None
    estado_movimento: str = "criado"
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    comprovativo_pagamento: Optional[str] = None

    class Config:
        from_attributes = True


class MovimentoHistoricoDTO(BaseModel):
    id: UUID
    movimento_id: UUID
    campo: str
    valor_anterior: Optional[str] = None
    valor_novo: Optional[str] = None
    user_name: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdateDTO(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class ResetPasswordDTO(BaseModel):
    new_password: str = Field(..., min_length=8)


class ChangePasswordDTO(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


# COMPANY SETTINGS DTOs
class CompanySettingsResponseDTO(BaseModel):
    company_id: UUID
    nome: str = ""
    nif: Optional[str] = None
    morada: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[EmailStr] = None
    iban_bcs: Optional[str] = None
    iban_bfa: Optional[str] = None
    logo_path: Optional[str] = None
    logo_url: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CompanySettingsUpdateDTO(BaseModel):
    nome: Optional[str] = Field(None, max_length=255)
    nif: Optional[str] = Field(None, max_length=20)
    morada: Optional[str] = Field(None, max_length=500)
    telefone: Optional[str] = Field(None, max_length=30)
    email: Optional[EmailStr] = None
    iban_bcs: Optional[str] = Field(None, max_length=50)
    iban_bfa: Optional[str] = Field(None, max_length=50)


# AUTH DTOs
class LoginRequestDTO(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponseDTO(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenDTO(BaseModel):
    refresh_token: str


# PAGINATION
class PaginationDTO(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)


class PaginatedResponseDTO(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int


__all__ = [
    "UserCreateDTO",
    "UserUpdateDTO",
    "ResetPasswordDTO",
    "ChangePasswordDTO",
    "UserResponseDTO",
    "FornecedorCreateDTO",
    "FornecedorUpdateDTO",
    "FornecedorResponseDTO",
    "ClienteCreateDTO",
    "ClienteUpdateDTO",
    "ClienteResponseDTO",
    "ConceptoCreateDTO",
    "ConceptoUpdateDTO",
    "ConceptoResponseDTO",
    "FundoResponseDTO",
    "FundoUpdateDTO",
    "MovimentoCreateDTO",
    "MovimentoUpdateDTO",
    "MovimentoResponseDTO",
    "MovimentoHistoricoDTO",
    "LoginRequestDTO",
    "TokenResponseDTO",
    "RefreshTokenDTO",
    "PaginationDTO",
    "PaginatedResponseDTO",
    "CompanySettingsResponseDTO",
    "CompanySettingsUpdateDTO",
]
