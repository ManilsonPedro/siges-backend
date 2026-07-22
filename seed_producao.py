"""Seed mínimo de produção: 1 empresa + 1 utilizador superadmin real.

Idempotente — pode ser corrido várias vezes sem duplicar dados.
Diferente de seed.py (dados fictícios de demonstração, não usar em produção).

Uso:
    DB_URL='postgresql://...' python seed_producao.py
    (variáveis opcionais: ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NOME, EMPRESA_NOME)
"""
import asyncio
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select

from app.infrastructure.database import AsyncSessionLocal, init_db
from app.infrastructure.database.models import CompanySettingsModel, UserModel
from app.infrastructure.auth import hash_password


ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@siges.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "MudarNoPrimeiroLogin@1234")
ADMIN_NOME = os.environ.get("ADMIN_NOME", "Administrador")
EMPRESA_NOME = os.environ.get("EMPRESA_NOME", "Minha Empresa")


async def run():
    await init_db()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(UserModel).where(UserModel.email == ADMIN_EMAIL))
        existente = r.scalar_one_or_none()
        if existente:
            print(f"Utilizador '{ADMIN_EMAIL}' já existe — nada a fazer.")
            return

        company_id = uuid4()
        admin = UserModel(
            id=uuid4(),
            company_id=company_id,
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            full_name=ADMIN_NOME,
            is_active=True,
            is_superadmin=True,
            must_change_password=True,
        )
        db.add(admin)

        settings = CompanySettingsModel(company_id=company_id, nome=EMPRESA_NOME)
        db.add(settings)

        await db.commit()
        print("Seed de produção concluído.")
        print(f"  Empresa: {EMPRESA_NOME} ({company_id})")
        print(f"  Login:   {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print("  (será exigida troca de senha no primeiro login)")


if __name__ == "__main__":
    asyncio.run(run())
