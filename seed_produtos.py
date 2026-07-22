"""Seed dos produtos KITOKA da Aquasan Angola.

Cria, para **todas as empresas existentes**, a categoria "KITOKA" e os 4
produtos próprios (hipoclorito de sódio a granel e lixívia). Idempotente:
re-execuções não duplicam.

Preços iniciais são *placeholders* — devem ser revistos com a área
comercial antes de uso real.
"""
import os
import sys
from uuid import uuid4

import psycopg


def _resolve_url() -> str:
    raw = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL") or ""
    if not raw:
        return ""
    u = raw
    for prefix in ["postgresql+psycopg://", "postgres+psycopg://"]:
        if u.startswith(prefix):
            u = "postgresql://" + u[len(prefix):]
            break
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://"):]
    return u


CATEGORIA_NOME = "KITOKA"

# (sku, nome, unidade, preço_base_AOA, iva_pct, descricao)
PRODUTOS = [
    (
        "KTK-HIPO-12-L",
        "Hipoclorito de Sódio 12% — granel",
        "L", "850.00", "14.00",
        "Hipoclorito de sódio concentração 12%, fornecido a granel. Marca KITOKA — Aquasan Angola.",
    ),
    (
        "KTK-HIPO-05-L",
        "Hipoclorito de Sódio 5% — granel",
        "L", "450.00", "14.00",
        "Hipoclorito de sódio concentração 5%, fornecido a granel. Marca KITOKA — Aquasan Angola.",
    ),
    (
        "KTK-LIX-1L",
        "Lixívia KITOKA 1 L",
        "un", "350.00", "14.00",
        "Lixívia KITOKA embalada em frasco de 1 litro.",
    ),
    (
        "KTK-LIX-5L",
        "Lixívia KITOKA 5 L",
        "un", "1500.00", "14.00",
        "Lixívia KITOKA embalada em bidão de 5 litros.",
    ),
]


def run():
    db_url = _resolve_url()
    if not db_url:
        print("ERRO: Defina DB_URL ou DATABASE_URL")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # Empresas existentes (usamos a tabela de utilizadores como fonte —
            # garante que só seedámos empresas com pelo menos um user).
            cur.execute("SELECT DISTINCT company_id FROM users")
            companies = [r[0] for r in cur.fetchall()]
            if not companies:
                print("Nenhuma empresa encontrada — nada a fazer.")
                return

            for company_id in companies:
                # Categoria KITOKA
                cur.execute(
                    "SELECT id FROM produto_categorias "
                    "WHERE company_id = %s AND nome = %s AND deleted_at IS NULL",
                    (company_id, CATEGORIA_NOME),
                )
                row = cur.fetchone()
                if row:
                    categoria_id = str(row[0])
                    print(f"  [skip] categoria KITOKA ({company_id}) já existe")
                else:
                    categoria_id = str(uuid4())
                    cur.execute(
                        "INSERT INTO produto_categorias "
                        "(id, company_id, nome, ordem, estado) "
                        "VALUES (%s, %s, %s, 10, 'ativo')",
                        (categoria_id, company_id, CATEGORIA_NOME),
                    )
                    print(f"  [new] categoria KITOKA ({company_id})")

                # Produtos
                for sku, nome, unidade, preco, iva, descricao in PRODUTOS:
                    cur.execute(
                        "SELECT id FROM produtos "
                        "WHERE company_id = %s AND sku = %s AND deleted_at IS NULL",
                        (company_id, sku),
                    )
                    if cur.fetchone():
                        print(f"  [skip] produto {sku} ({company_id})")
                        continue
                    cur.execute(
                        "INSERT INTO produtos "
                        "(id, company_id, sku, nome, marca, categoria_id, "
                        " unidade_medida, preco_base, iva_pct, descricao, activo) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)",
                        (
                            str(uuid4()), company_id, sku, nome, "KITOKA",
                            categoria_id, unidade, preco, iva, descricao,
                        ),
                    )
                    print(f"  [new] produto {sku} ({company_id})")

        conn.commit()
        print("\nSeed KITOKA concluído.")
    except Exception as e:
        conn.rollback()
        print(f"ERRO: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
