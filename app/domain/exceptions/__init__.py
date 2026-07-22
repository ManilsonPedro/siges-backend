class DomainException(Exception):
    """Exceção base do domínio"""
    pass


class ValidationException(DomainException):
    """Exceção de validação"""
    pass


class InsufficientFundsException(DomainException):
    """Saldo insuficiente"""
    pass


class FornecedorNotFound(DomainException):
    """Fornecedor não encontrado"""
    pass


class ConceptoNotFound(DomainException):
    """Conceito não encontrado"""
    pass


class FundoNotFound(DomainException):
    """Fundo não encontrado"""
    pass


class MovimentoNotFound(DomainException):
    """Movimento não encontrado"""
    pass


class UserNotFound(DomainException):
    """Utilizador não encontrado"""
    pass


class InvalidCredentials(DomainException):
    """Credenciais inválidas"""
    pass


class DuplicateFornecedor(DomainException):
    """Fornecedor duplicado"""
    pass


class DuplicateUser(DomainException):
    """Utilizador duplicado"""
    pass


__all__ = [
    "DomainException",
    "ValidationException",
    "InsufficientFundsException",
    "FornecedorNotFound",
    "ConceptoNotFound",
    "FundoNotFound",
    "MovimentoNotFound",
    "UserNotFound",
    "InvalidCredentials",
    "DuplicateFornecedor",
    "DuplicateUser",
]
