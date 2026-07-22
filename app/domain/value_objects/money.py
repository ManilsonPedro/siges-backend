from decimal import Decimal
from typing import Any


class Money:
    """Value Object para operações financeiras seguras"""
    
    def __init__(self, amount: Decimal | float | int | str, currency: str = "EUR"):
        self.amount = Decimal(str(amount))
        self.currency = currency
        self._validate()
    
    def _validate(self) -> None:
        """Valida o montante"""
        if not isinstance(self.amount, Decimal):
            raise ValueError("Amount must be a Decimal")
        if self.amount < 0:
            raise ValueError("Amount cannot be negative")
        if self.currency not in ["EUR", "USD", "GBP", "BRL"]:
            raise ValueError(f"Unsupported currency: {self.currency}")
    
    def add(self, other: "Money") -> "Money":
        """Soma dois montantes"""
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(self.amount + other.amount, self.currency)
    
    def subtract(self, other: "Money") -> "Money":
        """Subtrai dois montantes"""
        if self.currency != other.currency:
            raise ValueError("Cannot subtract different currencies")
        result = self.amount - other.amount
        if result < 0:
            raise ValueError("Result cannot be negative")
        return Money(result, self.currency)
    
    def multiply(self, factor: Decimal | float | int) -> "Money":
        """Multiplica o montante"""
        factor_decimal = Decimal(str(factor))
        return Money(self.amount * factor_decimal, self.currency)
    
    def format(self) -> str:
        """Formata o montante com símbolo de moeda"""
        currency_symbols = {
            "EUR": "€",
            "USD": "$",
            "GBP": "£",
            "BRL": "R$"
        }
        symbol = currency_symbols.get(self.currency, self.currency)
        return f"{symbol} {self.amount:,.2f}"
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount == other.amount and self.currency == other.currency
    
    def __lt__(self, other: "Money") -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare different currencies")
        return self.amount < other.amount
    
    def __le__(self, other: "Money") -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare different currencies")
        return self.amount <= other.amount
    
    def __gt__(self, other: "Money") -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare different currencies")
        return self.amount > other.amount
    
    def __ge__(self, other: "Money") -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare different currencies")
        return self.amount >= other.amount
    
    def __repr__(self) -> str:
        return f"Money({self.amount}, {self.currency})"
