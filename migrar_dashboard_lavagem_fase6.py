"""
Migração manual de colunas — Dashboard Operacional (Fase 6).

Adiciona a flag `no_show` a `ordens_lavagem`, distinguindo não-comparência
de cancelamento activo do cliente (ambos usam estado=cancelada).

Ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md, Fase 6.

Uso:
    DB_URL='...' python migrar_dashboard_lavagem_fase6.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS no_show BOOLEAN NOT NULL DEFAULT false",
]


async def main() -> None:
    db_url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DB_URL não definida")

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            await conn.execute(sqlalchemy.text(stmt))
            print("OK:", stmt)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
