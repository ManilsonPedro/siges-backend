"""
Migração manual de colunas/tabela — Dashboard Operacional (Fases 4 e 5).

Fase 4: atribuição individual opcional (colaborador_responsavel_id) sem
reestruturar o conceito de equipa colectiva já existente.

Fase 5: entidade Filial + filial_id denormalizado em boxes_lavagem, para
permitir comparativo entre unidades físicas sem exigir join através de
areas_servico em toda agregação de BI.

Ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md, Fases 4 e 5.

Uso:
    DB_URL='...' python migrar_dashboard_lavagem_fase4_5.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    "ALTER TABLE ordens_lavagem ADD COLUMN IF NOT EXISTS colaborador_responsavel_id VARCHAR(36)",
    """
    CREATE TABLE IF NOT EXISTS filiais (
        id VARCHAR(36) PRIMARY KEY,
        company_id VARCHAR(36) NOT NULL,
        nome VARCHAR(120) NOT NULL,
        morada TEXT,
        activo BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_filiais_company_id ON filiais (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_filiais_activo ON filiais (activo)",
    "CREATE INDEX IF NOT EXISTS ix_filiais_deleted_at ON filiais (deleted_at)",
    "ALTER TABLE boxes_lavagem ADD COLUMN IF NOT EXISTS filial_id VARCHAR(36)",
    "CREATE INDEX IF NOT EXISTS ix_boxes_lavagem_filial_id ON boxes_lavagem (filial_id)",
]


async def main() -> None:
    db_url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DB_URL não definida")

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            await conn.execute(sqlalchemy.text(stmt))
            print("OK:", stmt.strip().split("\n")[0])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
