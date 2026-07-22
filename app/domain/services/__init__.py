from abc import ABC, abstractmethod
from uuid import UUID
from typing import Optional
from app.domain.value_objects import Money


class IFundoService(ABC):
    """Interface do serviço de fundos"""
    
    @abstractmethod
    async def recalcular_saldo(self, company_id: UUID) -> None:
        """Recalcula o saldo e acumulado"""
        pass
    
    @abstractmethod
    async def validar_saldo_suficiente(
        self, 
        company_id: UUID, 
        valor: Money
    ) -> bool:
        """Valida se há saldo suficiente"""
        pass


class IMovimentoService(ABC):
    """Interface do serviço de movimentos"""
    
    @abstractmethod
    async def validar_movimento(
        self,
        company_id: UUID,
        fornecedor_id: UUID,
        conceito_id: UUID,
        valor: Money
    ) -> bool:
        """Valida os dados do movimento"""
        pass


class IAuditoriaService(ABC):
    """Interface do serviço de auditoria"""
    
    @abstractmethod
    async def registrar_acao(
        self,
        user_id: UUID,
        company_id: UUID,
        acao: str,
        entidade: str,
        entidade_id: UUID,
        dados_anteriores: Optional[dict] = None,
        dados_novos: Optional[dict] = None,
        ip_address: str = "",
        user_agent: str = ""
    ) -> None:
        """Registra uma ação de auditoria"""
        pass


__all__ = [
    "IFundoService",
    "IMovimentoService",
    "IAuditoriaService",
]
