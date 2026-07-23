"""
Ponto de entrada único para os scripts `migrar_*.py` (ALTER/DROP idempotentes
sobre tabelas que já existem em produção — o projeto não usa Alembic e
`Base.metadata.create_all` nunca altera colunas/tabelas já existentes).

Corre cada script em sequência, na ordem desta lista. Todo sprint que altere
o schema de uma tabela já existente (coluna nova, coluna removida, rename)
deve adicionar o seu `migrar_<nome>.py` aqui — ver PROMPT_SISTEMA_SIGES_SPRINTS.md,
Sprint 0.4.

Uso manual:
    DB_URL='...' python migrar.py

Chamado automaticamente no arranque da app (ver app/main.py), depois de
`migrate.py` (que cria as tabelas base) e antes dos scripts de seed.
"""
import asyncio
import importlib
import os

# Ordem de execução: cada módulo expõe `async def main()`.
MODULOS = [
    "migrar_colunas_lavagem",
    "migrar_remover_combustivel",
    "migrar_remover_primavera",
]


async def run_async() -> None:
    db_url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DB_URL não definida")

    for nome in MODULOS:
        print(f"\n=== {nome} ===")
        modulo = importlib.import_module(nome)
        try:
            await modulo.main()
        except Exception as e:
            # Idempotente por natureza (IF EXISTS/IF NOT EXISTS) — uma falha
            # aqui indica um problema real de schema, não repetição segura.
            # Regista e continua para não bloquear os scripts seguintes.
            print(f"  [ERRO] {nome}: {e}")


def run() -> None:
    """Wrapper síncrono — mesmo padrão de `migrate.run()` para uso em
    `asyncio.to_thread()` a partir do bootstrap síncrono do main.py."""
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
