"""
Migração manual de colunas — módulo Lavagem.

O projeto não usa Alembic (tabelas são criadas só via
`Base.metadata.create_all`, que nunca adiciona colunas novas a tabelas já
existentes). Este script aplica ALTER TABLE idempotentes para colunas que
foram adicionadas aos modelos SQLAlchemy depois da tabela já existir em
produção — descobertas ao testar o módulo de Lavagem ponta-a-ponta contra
uma cópia da BD de produção (branch Neon de dev).

Uso:
    DB_URL='...' python migrar_colunas_lavagem.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    # viaturas.categoria_veiculo_id — Sprint 1 (preço/água por categoria de veículo)
    "ALTER TABLE viaturas ADD COLUMN IF NOT EXISTS categoria_veiculo_id VARCHAR(36)",
    # viaturas.cliente_id deve ser nullable (D1: walk-in sem conta de cliente)
    "ALTER TABLE viaturas ALTER COLUMN cliente_id DROP NOT NULL",
    # ordens_lavagem.origem — Sprint 3 (walk-in vs. reserva vs. telefone)
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS origem VARCHAR(20) NOT NULL DEFAULT 'backoffice_walkin'",
    # ordens_lavagem.lembrete_enviado — Sprint 6 (lembrete 30min antes da reserva)
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS lembrete_enviado BOOLEAN NOT NULL DEFAULT false",
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
