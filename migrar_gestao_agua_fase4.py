"""
Migração manual — Gestão de Recursos Hídricos (Fase 4).

Anexos genéricos com versionamento (entity_type/entity_id/tipo_documento/
versao), reutilizável por Água e por futuros módulos. Não substitui
`movimento_anexos` (fluxo financeiro com regras próprias) — coexistem.

Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fase 4.

Uso:
    DB_URL='...' python migrar_gestao_agua_fase4.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS anexos (
        id VARCHAR(36) PRIMARY KEY,
        company_id VARCHAR(36) NOT NULL,
        entity_type VARCHAR(50) NOT NULL,
        entity_id VARCHAR(36) NOT NULL,
        tipo_documento VARCHAR(30) NOT NULL,
        versao INTEGER NOT NULL DEFAULT 1,
        file_path VARCHAR(500) NOT NULL,
        file_name VARCHAR(255) NOT NULL,
        mime_type VARCHAR(100),
        size_bytes INTEGER,
        uploaded_by VARCHAR(36) NOT NULL,
        uploaded_at TIMESTAMP,
        deleted_at TIMESTAMP,
        deleted_by VARCHAR(36),
        delete_reason VARCHAR(500)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_anexos_company_id ON anexos (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_anexos_entity_type ON anexos (entity_type)",
    "CREATE INDEX IF NOT EXISTS ix_anexos_entity_id ON anexos (entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_anexos_uploaded_at ON anexos (uploaded_at)",
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
