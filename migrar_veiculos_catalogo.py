"""
Migração manual — Catálogo de Veículo (Marca, Modelo, Cor).

Cria as tabelas de referência para os dropdowns de Viatura (portal e
backoffice). Não popula dados — ver seed_veiculos_catalogo.py para um
seed opcional e manual, chamado por company_id (não integrado ao
arranque automático da app, já que catálogo de marcas/cores é decisão
do backoffice de cada empresa, não um valor universal).

Uso:
    DB_URL='...' python migrar_veiculos_catalogo.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS marcas_veiculo (
        id VARCHAR(36) PRIMARY KEY,
        company_id VARCHAR(36) NOT NULL,
        nome VARCHAR(60) NOT NULL,
        activo BOOLEAN NOT NULL DEFAULT true,
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_marcas_veiculo_company_id ON marcas_veiculo (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_marcas_veiculo_activo ON marcas_veiculo (activo)",
    "CREATE INDEX IF NOT EXISTS ix_marcas_veiculo_deleted_at ON marcas_veiculo (deleted_at)",
    """
    CREATE TABLE IF NOT EXISTS modelos_veiculo (
        id VARCHAR(36) PRIMARY KEY,
        company_id VARCHAR(36) NOT NULL,
        marca_id VARCHAR(36) NOT NULL,
        nome VARCHAR(60) NOT NULL,
        activo BOOLEAN NOT NULL DEFAULT true,
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_modelos_veiculo_company_id ON modelos_veiculo (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_modelos_veiculo_marca_id ON modelos_veiculo (marca_id)",
    "CREATE INDEX IF NOT EXISTS ix_modelos_veiculo_activo ON modelos_veiculo (activo)",
    "CREATE INDEX IF NOT EXISTS ix_modelos_veiculo_deleted_at ON modelos_veiculo (deleted_at)",
    """
    CREATE TABLE IF NOT EXISTS cores_veiculo (
        id VARCHAR(36) PRIMARY KEY,
        company_id VARCHAR(36) NOT NULL,
        nome VARCHAR(30) NOT NULL,
        hex VARCHAR(7),
        activo BOOLEAN NOT NULL DEFAULT true,
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_cores_veiculo_company_id ON cores_veiculo (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_cores_veiculo_activo ON cores_veiculo (activo)",
    "CREATE INDEX IF NOT EXISTS ix_cores_veiculo_deleted_at ON cores_veiculo (deleted_at)",
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
