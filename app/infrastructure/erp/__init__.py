"""Factory do `ErpGateway` activo segundo a configuração."""
from __future__ import annotations

from app.config import settings
from app.domain.services.erp_gateway import ErpGateway


def get_erp_gateway() -> ErpGateway:
    """Devolve a implementação do ErpGateway conforme ``settings.erp_provider``.

    Trocar a env var ``ERP_PROVIDER`` arranca o backend sem erros — o stub
    do Primavera só levanta ``NotImplementedError`` quando é *chamado*.
    """
    provider = (settings.erp_provider or "local").lower()
    if provider == "primavera":
        from app.infrastructure.erp.primavera_gateway import PrimaveraErpGateway
        return PrimaveraErpGateway()
    # default
    from app.infrastructure.erp.local_gateway import LocalErpGateway
    return LocalErpGateway()


__all__ = ["get_erp_gateway"]
