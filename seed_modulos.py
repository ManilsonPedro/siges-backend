"""Seed dos Módulos e Páginas (catálogo do sistema).

Cada Módulo/Página criado aqui é `is_system=true` — pode ser renomeado mas não eliminado.
Idempotente.
"""
import os
import sys
import psycopg
from uuid import uuid4

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

url = _resolve_url()

# Módulos
MODULOS = [
    # nome, descricao, icone, ordem
    ("Operacional", "Movimentos financeiros e operações do dia-a-dia", "ArrowLeftRight", 10),
    ("Cadastros", "Fornecedores, Clientes, Conceitos", "Users", 20),
    ("Financeiro", "Fundos, Orçamentos, Períodos", "Wallet", 30),
    ("Relatórios", "Relatórios e Auditoria", "BarChart3", 40),
    ("Administração", "Utilizadores, Grupos, Empresa, Lixeira", "Shield", 50),
]

# Páginas (modulo_nome, nome_pagina, descricao, href, icone, ordem)
PAGINAS = [
    ("Operacional", "dashboard",   "Painel principal",         "/dashboard",                 "LayoutDashboard", 10),
    ("Operacional", "movimentos",  "Movimentos financeiros",   "/dashboard/movimentos",      "ArrowLeftRight",  20),
    ("Cadastros",   "fornecedores","Fornecedores",             "/dashboard/fornecedores",    "Users",           10),
    ("Cadastros",   "clientes",    "Clientes",                 "/dashboard/clientes",        "Users",           20),
    ("Cadastros",   "conceitos",   "Conceitos financeiros",    "/dashboard/conceitos",       "Tag",             30),
    ("Financeiro",  "fundos",      "Fundos BCS / BFA",         "/dashboard/fundos",          "Wallet",          10),
    ("Financeiro",  "orcamentos",  "Orçamentos",               "/dashboard/orcamentos",      "Target",          20),
    ("Financeiro",  "periodos",    "Períodos contabilísticos", "/dashboard/periodos",        "Lock",            30),
    ("Relatórios",  "relatorios",  "Relatórios e extratos",    "/dashboard/relatorios",      "BarChart3",       10),
    ("Relatórios",  "auditoria",   "Histórico de auditoria",   "/dashboard/auditoria",       "ShieldCheck",     20),
    ("Administração","users",       "Utilizadores",             "/dashboard/utilizadores",    "UserCog",         10),
    ("Administração","grupos",      "Grupos de utilizadores",   "/dashboard/utilizadores",    "Shield",          20),
    ("Administração","empresa",     "Configurações da empresa", "/dashboard/configuracoes",   "Building2",       30),
    ("Administração","lixeira",     "Lixeira (soft-delete)",    "/dashboard/lixeira",         "Trash2",          40),
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
            # Módulos
            mod_map = {}
            for nome, desc, icone, ordem in MODULOS:
                cur.execute("SELECT id FROM modulos WHERE nome = %s", (nome,))
                row = cur.fetchone()
                if row:
                    mod_map[nome] = str(row[0])
                    cur.execute(
                        "UPDATE modulos SET descricao=%s, icone=%s, ordem=%s, is_system=TRUE WHERE id=%s",
                        (desc, icone, ordem, row[0]),
                    )
                    print(f"  [upd] modulo {nome}")
                else:
                    mid = str(uuid4())
                    cur.execute(
                        "INSERT INTO modulos (id, nome, descricao, icone, ordem, is_system) "
                        "VALUES (%s, %s, %s, %s, %s, TRUE)",
                        (mid, nome, desc, icone, ordem),
                    )
                    mod_map[nome] = mid
                    print(f"  [new] modulo {nome}")

            # Páginas
            pag_map = {}
            for mod_nome, nome_pag, desc, href, icone, ordem in PAGINAS:
                modulo_id = mod_map.get(mod_nome)
                cur.execute("SELECT id FROM paginas WHERE nome = %s AND modulo_id = %s", (nome_pag, modulo_id))
                row = cur.fetchone()
                if row:
                    pag_map[nome_pag] = str(row[0])
                    cur.execute(
                        "UPDATE paginas SET descricao=%s, href=%s, icone=%s, ordem=%s, is_system=TRUE WHERE id=%s",
                        (desc, href, icone, ordem, row[0]),
                    )
                    print(f"  [upd] página {mod_nome}/{nome_pag}")
                else:
                    pid = str(uuid4())
                    cur.execute(
                        "INSERT INTO paginas (id, modulo_id, nome, descricao, href, icone, ordem, is_system) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)",
                        (pid, modulo_id, nome_pag, desc, href, icone, ordem),
                    )
                    pag_map[nome_pag] = pid
                    print(f"  [new] página {mod_nome}/{nome_pag}")

            # Backfill permissoes.pagina_id baseado em permissoes.menu == paginas.nome
            for pag_nome, pid in pag_map.items():
                cur.execute(
                    "UPDATE permissoes SET pagina_id = %s WHERE menu = %s AND (pagina_id IS NULL OR pagina_id = '')",
                    (pid, pag_nome),
                )

        conn.commit()
        print("\nSeed concluído.")
    except Exception as e:
        conn.rollback()
        print(f"ERRO: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
