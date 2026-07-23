"""
Migração manual — Gestão de Recursos Hídricos (Fases 3 e 8).

Fase 3: abastecimentos_agua — entrada de fornecedor num tanque, com
numeração sequencial (ABA-<ano>-<seq>), fornecedor, filial, equipamento
e responsáveis.

Fase 8: movimentos_tanque_agua — livro de movimentos tipados (entrada,
saída, ajuste, transferência, perda, evaporação, vazamento). Cada
alteração ao nível do tanque (abastecimento, consumo, ajuste manual)
passa a gerar aqui um registo permanente.

Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fases 3 e 8.

Uso:
    DB_URL='...' python migrar_gestao_agua_fase3_8.py
"""
import asyncio
import os

import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS abastecimentos_agua (
        id VARCHAR(36) PRIMARY KEY,
        company_id VARCHAR(36) NOT NULL,
        numero VARCHAR(30),
        tanque_agua_id VARCHAR(36) NOT NULL,
        fornecedor_id VARCHAR(36) NOT NULL,
        filial_id VARCHAR(36),
        equipamento_id VARCHAR(36),
        quantidade_litros NUMERIC(12,2) NOT NULL,
        valor_por_litro NUMERIC(10,4) NOT NULL,
        custo_total NUMERIC(12,2) NOT NULL,
        metodo_pagamento VARCHAR(30),
        observacoes TEXT,
        registado_por_id VARCHAR(36) NOT NULL,
        recebido_por_id VARCHAR(36),
        estado VARCHAR(20) NOT NULL DEFAULT 'registado',
        data TIMESTAMP,
        created_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_abastecimentos_agua_company_id ON abastecimentos_agua (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_abastecimentos_agua_numero ON abastecimentos_agua (numero)",
    "CREATE INDEX IF NOT EXISTS ix_abastecimentos_agua_tanque_agua_id ON abastecimentos_agua (tanque_agua_id)",
    "CREATE INDEX IF NOT EXISTS ix_abastecimentos_agua_fornecedor_id ON abastecimentos_agua (fornecedor_id)",
    "CREATE INDEX IF NOT EXISTS ix_abastecimentos_agua_filial_id ON abastecimentos_agua (filial_id)",
    "CREATE INDEX IF NOT EXISTS ix_abastecimentos_agua_estado ON abastecimentos_agua (estado)",
    "CREATE INDEX IF NOT EXISTS ix_abastecimentos_agua_data ON abastecimentos_agua (data)",
    """
    CREATE TABLE IF NOT EXISTS movimentos_tanque_agua (
        id VARCHAR(36) PRIMARY KEY,
        company_id VARCHAR(36) NOT NULL,
        tanque_agua_id VARCHAR(36) NOT NULL,
        tipo VARCHAR(20) NOT NULL,
        quantidade_litros NUMERIC(12,2) NOT NULL,
        nivel_antes NUMERIC(12,2) NOT NULL,
        nivel_depois NUMERIC(12,2) NOT NULL,
        referencia_tipo VARCHAR(30),
        referencia_id VARCHAR(36),
        observacoes TEXT,
        registado_por_id VARCHAR(36) NOT NULL,
        created_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_movimentos_tanque_agua_company_id ON movimentos_tanque_agua (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_movimentos_tanque_agua_tanque_agua_id ON movimentos_tanque_agua (tanque_agua_id)",
    "CREATE INDEX IF NOT EXISTS ix_movimentos_tanque_agua_tipo ON movimentos_tanque_agua (tipo)",
    "CREATE INDEX IF NOT EXISTS ix_movimentos_tanque_agua_created_at ON movimentos_tanque_agua (created_at)",
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
