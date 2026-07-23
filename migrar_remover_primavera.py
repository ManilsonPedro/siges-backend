"""
Migração manual — remoção do mecanismo Primavera (Sprint 0.2).

"Primavera ERP" nunca teve integração real: era um stub (`NotImplementedError`),
campos de referência manual, e em vários casos apenas um banner de UI sobre
dados inventados no frontend. Removido por completo — todo dado passa a ser
gerido e persistido pela própria aplicação (ver PROMPT_SISTEMA_SIGES_SPRINTS.md,
Sprint 0.2).

O projeto não usa Alembic — este script aplica os DROP COLUMN idempotentes
correspondentes à remoção dos campos dos modelos SQLAlchemy, e RENAME das
colunas de VendaModel que foram substituídas pelo equivalente interno
(faturação própria, sem depender de ERP externo).

Uso:
    DB_URL='...' python migrar_remover_primavera.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    "ALTER TABLE produtos DROP COLUMN IF EXISTS ref_primavera",
    "ALTER TABLE armazens DROP COLUMN IF EXISTS ref_primavera",
    # vendas: ref_primavera/primavera_marcada_em/primavera_marcada_por
    # substituídos por numero_fatura_interna/faturada_em/faturada_por.
    # Migra o valor existente antes de remover a coluna antiga, para não
    # perder o histórico de vendas já marcadas.
    "ALTER TABLE vendas ADD COLUMN IF NOT EXISTS numero_fatura_interna VARCHAR(50)",
    "ALTER TABLE vendas ADD COLUMN IF NOT EXISTS faturada_em TIMESTAMP",
    "ALTER TABLE vendas ADD COLUMN IF NOT EXISTS faturada_por VARCHAR(36)",
    """
    UPDATE vendas SET
        numero_fatura_interna = ref_primavera,
        faturada_em = primavera_marcada_em,
        faturada_por = primavera_marcada_por
    WHERE ref_primavera IS NOT NULL AND numero_fatura_interna IS NULL
    """,
    "DROP INDEX IF EXISTS ix_vendas_pendente_primavera",
    "ALTER TABLE vendas DROP COLUMN IF EXISTS ref_primavera",
    "ALTER TABLE vendas DROP COLUMN IF EXISTS primavera_marcada_em",
    "ALTER TABLE vendas DROP COLUMN IF EXISTS primavera_marcada_por",
    "CREATE INDEX IF NOT EXISTS ix_vendas_numero_fatura_interna ON vendas (numero_fatura_interna)",
]


async def main() -> None:
    db_url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DB_URL não definida")

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            await conn.execute(sqlalchemy.text(stmt))
            print("OK:", stmt.strip().splitlines()[0])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
