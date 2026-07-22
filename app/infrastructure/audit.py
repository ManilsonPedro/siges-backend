from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.database.models import AuditLogModel
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional


async def write_audit(
    db: AsyncSession,
    user_id: UUID,
    company_id: UUID,
    acao: str,
    entidade: str,
    entidade_id: UUID,
    dados_anteriores: Optional[dict] = None,
    dados_novos: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    log = AuditLogModel(
        id=uuid4(),
        user_id=user_id,
        company_id=company_id,
        acao=acao,
        entidade=entidade,
        entidade_id=entidade_id,
        dados_anteriores=dados_anteriores,
        dados_novos=dados_novos,
        ip_address=ip_address,
        created_at=datetime.utcnow(),
    )
    db.add(log)
