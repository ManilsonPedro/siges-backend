"""
Migração one-time: elimina a coluna `users.role`.

A autorização passou a ser 100% baseada em Grupos. Este script:
  1. Verifica que a coluna `role` ainda existe (senão, no-op idempotente).
  2. Garante pré-condições anti-lockout:
       - nenhum utilizador ativo com grupo_id NULL;
       - pelo menos um utilizador ativo com a permissão `grupos.gerir` (admin).
  3. Executa `ALTER TABLE users DROP COLUMN role`.

⚠️ Correr SÓ depois de `seed_permissoes.py` (que cria os grupos e atribui
   grupo_id a partir do role legado). Se as pré-condições falharem, o script
   aborta SEM alterar nada.

Uso:
    DB_URL='postgresql://...' python migrate_drop_role.py
"""
import os
import sys
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


def run():
    db_url = _resolve_url()
    if not db_url:
        print("ERRO: Defina DB_URL ou DATABASE_URL")
        sys.exit(1)

    conn = psycopg.connect(db_url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # 1) A coluna ainda existe?
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = 'role'"
            )
            if not cur.fetchone():
                print("[ok] Coluna 'role' já não existe — nada a fazer.")
                conn.rollback()
                return

            # 2a) Utilizadores ativos sem grupo
            cur.execute(
                "SELECT email FROM users WHERE deleted_at IS NULL "
                "AND is_active = TRUE AND grupo_id IS NULL"
            )
            sem_grupo = [row[0] for row in cur.fetchall()]
            if sem_grupo:
                print("ABORTADO: utilizadores ativos sem grupo_id (corra seed_permissoes.py primeiro):")
                for e in sem_grupo:
                    print(f"  - {e}")
                conn.rollback()
                sys.exit(2)

            # 2b) Existe pelo menos um admin (grupos.gerir via grupo)?
            cur.execute(
                "SELECT COUNT(*) FROM users u "
                "JOIN grupo_permissoes gp ON gp.grupo_id::text = u.grupo_id::text "
                "JOIN permissoes p ON p.id = gp.permissao_id "
                "WHERE p.codigo = 'grupos.gerir' AND u.is_active = TRUE AND u.deleted_at IS NULL"
            )
            n_admin = cur.fetchone()[0]
            if not n_admin:
                print("ABORTADO: nenhum utilizador ativo com permissão 'grupos.gerir'. "
                      "Atribua o grupo Admin a alguém antes de eliminar a coluna role.")
                conn.rollback()
                sys.exit(3)

            # 3) Drop
            cur.execute("ALTER TABLE users DROP COLUMN role")
            print(f"[ok] Coluna 'role' eliminada. Admins ativos: {n_admin}.")

        conn.commit()
        print("Migração concluída com sucesso.")
    except Exception as e:
        conn.rollback()
        print(f"ERRO: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
