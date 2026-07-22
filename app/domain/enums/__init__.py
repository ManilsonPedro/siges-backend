from enum import Enum


class UserRoleEnum(str, Enum):
    """Roles de utilizador"""
    ADMIN = "admin"
    FINANCEIRO = "financeiro"
    AUDITOR = "auditor"


class EstadoFornecedorEnum(str, Enum):
    """Estados do fornecedor"""
    ATIVO = "ativo"
    INATIVO = "inativo"
    SUSPENSO = "suspenso"


class EstadoConceptoEnum(str, Enum):
    """Estados do conceito"""
    ATIVO = "ativo"
    INATIVO = "inativo"


class TipoMovimentoEnum(str, Enum):
    """Tipo de movimento financeiro"""
    ENTRADA = "entrada"
    SAIDA = "saida"


class EstadoPagamentoEnum(str, Enum):
    """Estados de pagamento"""
    PENDENTE = "pendente"
    PAGO = "pago"
    CANCELADO = "cancelado"


class AcaoAuditoriaEnum(str, Enum):
    """Ações auditadas"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    EXPORT = "export"
    UPLOAD = "upload"


__all__ = [
    "UserRoleEnum",
    "EstadoFornecedorEnum",
    "EstadoConceptoEnum",
    "TipoMovimentoEnum",
    "EstadoPagamentoEnum",
    "AcaoAuditoriaEnum",
]
