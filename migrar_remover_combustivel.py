"""
Migração manual — remoção do domínio Combustível (Sprint 0.1).

Combustível estava implementado por completo (5 tabelas, CRUD real) mas
não faz parte da visão actual do negócio: o SIGES foca-se em estação de
serviço centrada em Lavagem Automóvel, não em bombas de combustível
(ver PROMPT_SISTEMA_SIGES_SPRINTS.md, Sprint 0.1).

O projeto não usa Alembic — este script aplica os DROP TABLE idempotentes
correspondentes à remoção dos modelos SQLAlchemy.

Uso:
    DB_URL='...' python migrar_remover_combustivel.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    "DROP TABLE IF EXISTS abastecimentos",
    "DROP TABLE IF EXISTS leituras_tanque",
    "DROP TABLE IF EXISTS bicos",
    "DROP TABLE IF EXISTS bombas",
    "DROP TABLE IF EXISTS tanques_combustivel",
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
