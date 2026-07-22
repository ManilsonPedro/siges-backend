from abc import ABC, abstractmethod
from uuid import UUID
from typing import Optional, List, Any


class IRepository(ABC):
    """Interface base do repositório"""
    
    @abstractmethod
    async def get_by_id(self, id: UUID) -> Optional[Any]:
        pass
    
    @abstractmethod
    async def get_all(self, skip: int = 0, limit: int = 100) -> List[Any]:
        pass
    
    @abstractmethod
    async def create(self, entity: Any) -> Any:
        pass
    
    @abstractmethod
    async def update(self, id: UUID, entity: Any) -> Optional[Any]:
        pass
    
    @abstractmethod
    async def delete(self, id: UUID) -> bool:
        pass


class IUserRepository(IRepository):
    """Interface do repositório de utilizadores"""
    
    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[Any]:
        pass


class IFornecedorRepository(IRepository):
    """Interface do repositório de fornecedores"""
    
    @abstractmethod
    async def get_by_nif(self, nif: str) -> Optional[Any]:
        pass
    
    @abstractmethod
    async def get_by_company(self, company_id: UUID) -> List[Any]:
        pass


class IConceptoRepository(IRepository):
    """Interface do repositório de conceitos"""
    
    @abstractmethod
    async def get_by_company(self, company_id: UUID) -> List[Any]:
        pass


class IFundoRepository(IRepository):
    """Interface do repositório de fundos"""
    
    @abstractmethod
    async def get_by_company(self, company_id: UUID) -> Optional[Any]:
        pass


class IMovimentoRepository(IRepository):
    """Interface do repositório de movimentos"""
    
    @abstractmethod
    async def get_by_company(
        self, 
        company_id: UUID,
        skip: int = 0,
        limit: int = 100,
        filtros: Optional[dict] = None
    ) -> List[Any]:
        pass
    
    @abstractmethod
    async def get_by_fornecedor(self, fornecedor_id: UUID) -> List[Any]:
        pass
    
    @abstractmethod
    async def get_by_conceito(self, conceito_id: UUID) -> List[Any]:
        pass


class IAuditLogRepository(IRepository):
    """Interface do repositório de auditoria"""
    
    @abstractmethod
    async def get_by_company(self, company_id: UUID, skip: int = 0, limit: int = 100) -> List[Any]:
        pass
    
    @abstractmethod
    async def get_by_user(self, user_id: UUID, skip: int = 0, limit: int = 100) -> List[Any]:
        pass


__all__ = [
    "IRepository",
    "IUserRepository",
    "IFornecedorRepository",
    "IConceptoRepository",
    "IFundoRepository",
    "IMovimentoRepository",
    "IAuditLogRepository",
]
