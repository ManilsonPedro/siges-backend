"""
Migração manual de colunas — Dashboard Operacional (Fases 2 e 3).

Adiciona a `ordens_lavagem` os timestamps por transição de estado
(necessários para tempo médio de atendimento/espera — `updated_at`
sobrescreve-se a cada transição, não serve) e o preço snapshot gravado
na conclusão (necessário para receita/ticket médio não mudarem
retroactivamente se o catálogo de preços for alterado depois).

Ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md, Fases 2 e 3.

Uso:
    DB_URL='...' python migrar_dashboard_lavagem.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS checkin_em TIMESTAMP",
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS iniciado_em TIMESTAMP",
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS controlo_qualidade_em TIMESTAMP",
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS concluido_em TIMESTAMP",
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS preco_total_snapshot NUMERIC(10, 2)",
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
