"""
Migração manual de colunas — Gestão de Recursos Hídricos (Fases 1 e 2).

Fase 1: tanques_agua ganha filial_id (localização) e estado
(activo|manutencao|inactivo), complementando o soft-delete já existente.

Fase 2: fornecedores ganha tipo_pessoa (singular|empresa) — reutilização
do cadastro de fornecedores já existente para os fornecedores de água,
sem criar tabela paralela.

Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fases 1 e 2.

Uso:
    DB_URL='...' python migrar_gestao_agua_fase1_2.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    "ALTER TABLE tanques_agua ADD COLUMN IF NOT EXISTS filial_id VARCHAR(36)",
    "ALTER TABLE tanques_agua ADD COLUMN IF NOT EXISTS estado VARCHAR(20) NOT NULL DEFAULT 'activo'",
    "CREATE INDEX IF NOT EXISTS ix_tanques_agua_filial_id ON tanques_agua (filial_id)",
    "ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS tipo_pessoa VARCHAR(20)",
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
