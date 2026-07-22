from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4
from typing import Optional
from decimal import Decimal


@dataclass
class User:
    """Entidade: Utilizador"""
    id: UUID = field(default_factory=uuid4)
    company_id: UUID = field(default_factory=uuid4)
    email: str = ""
    hashed_password: str = ""
    full_name: str = ""
    is_active: bool = True
    is_superadmin: bool = False
    must_change_password: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None


@dataclass
class Fornecedor:
    """Entidade: Fornecedor"""
    id: UUID = field(default_factory=uuid4)
    company_id: UUID = field(default_factory=uuid4)
    nome: str = ""
    nif: str = ""
    telefone: str = ""
    email: str = ""
    endereco: str = ""
    estado: str = "ativo"  # ativo, inativo, suspenso
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None
    cliente_id: Optional[UUID] = None


@dataclass
class Cliente:
    """Entidade: Cliente (comprador, associado a Entradas)."""
    id: UUID = field(default_factory=uuid4)
    company_id: UUID = field(default_factory=uuid4)
    nome: str = ""
    nif: str = ""
    telefone: str = ""
    email: str = ""
    endereco: str = ""
    estado: str = "ativo"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None
    fornecedor_id: Optional[UUID] = None


@dataclass
class Conceito:
    """Entidade: Conceito Financeiro"""
    id: UUID = field(default_factory=uuid4)
    company_id: UUID = field(default_factory=uuid4)
    nome: str = ""
    descricao: str = ""
    estado: str = "ativo"  # ativo, inativo
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None


@dataclass
class Fundo:
    """Entidade: Fundo Financeiro"""
    id: UUID = field(default_factory=uuid4)
    company_id: UUID = field(default_factory=uuid4)
    tipo: str = "BCS"
    data: datetime = field(default_factory=datetime.utcnow)
    descricao: str = ""
    valor_disponivel: Decimal = field(default_factory=lambda: Decimal("0.00"))
    acumulado: Decimal = field(default_factory=lambda: Decimal("0.00"))
    saldo_atual: Decimal = field(default_factory=lambda: Decimal("0.00"))
    observacao: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MovimentoFinanceiro:
    """Entidade: Movimento Financeiro"""
    id: UUID = field(default_factory=uuid4)
    company_id: UUID = field(default_factory=uuid4)
    data: datetime = field(default_factory=datetime.utcnow)
    fornecedor_id: Optional[UUID] = None
    cliente_id: Optional[UUID] = None
    conceito_id: UUID = field(default_factory=uuid4)
    fatura_proforma: str = ""
    valor: str = "0.00"
    fatura_recibo: str = ""
    comprovativo_pagamento: Optional[str] = None
    observacoes: str = ""
    tipo_movimento: str = "entrada"
    estado_pagamento: str = "pendente"
    estado_movimento: str = "criado"
    fundo_tipo: str = "BCS"
    codigo: Optional[str] = None
    created_by: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None


@dataclass
class AuditLog:
    """Entidade: Log de Auditoria"""
    id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    company_id: UUID = field(default_factory=uuid4)
    acao: str = ""  # create, update, delete, login, export, upload
    entidade: str = ""  # Nome da entidade
    entidade_id: UUID = field(default_factory=uuid4)
    dados_anteriores: dict = field(default_factory=dict)  # JSONB
    dados_novos: dict = field(default_factory=dict)  # JSONB
    ip_address: str = ""
    user_agent: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


__all__ = [
    "User",
    "Fornecedor",
    "Conceito",
    "Fundo",
    "MovimentoFinanceiro",
    "AuditLog",
]
