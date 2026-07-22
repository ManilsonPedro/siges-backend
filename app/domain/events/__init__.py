from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class DomainEvent:
    """Evento base do domínio"""
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    aggregate_id: UUID = field(default_factory=uuid4)


@dataclass
class MovementCreatedEvent(DomainEvent):
    """Evento: Movimento criado"""
    company_id: UUID = field(default_factory=uuid4)
    movimento_id: UUID = field(default_factory=uuid4)
    fornecedor_id: UUID = field(default_factory=uuid4)
    conceito_id: UUID = field(default_factory=uuid4)
    valor: str = ""
    tipo_movimento: str = ""


@dataclass
class MovementUpdatedEvent(DomainEvent):
    """Evento: Movimento atualizado"""
    company_id: UUID = field(default_factory=uuid4)
    movimento_id: UUID = field(default_factory=uuid4)
    changes: dict = field(default_factory=dict)


@dataclass
class MovementDeletedEvent(DomainEvent):
    """Evento: Movimento eliminado"""
    company_id: UUID = field(default_factory=uuid4)
    movimento_id: UUID = field(default_factory=uuid4)


@dataclass
class FundsUpdatedEvent(DomainEvent):
    """Evento: Fundos atualizados"""
    company_id: UUID = field(default_factory=uuid4)
    fundo_id: UUID = field(default_factory=uuid4)
    saldo_atual: str = ""
    acumulado: str = ""


__all__ = [
    "DomainEvent",
    "MovementCreatedEvent",
    "MovementUpdatedEvent",
    "MovementDeletedEvent",
    "FundsUpdatedEvent",
]
