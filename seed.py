"""Seed data para desenvolvimento"""
import asyncio
from uuid import uuid4
from decimal import Decimal
from datetime import datetime, timedelta
import random

from app.infrastructure.database import AsyncSessionLocal, init_db
from app.infrastructure.database.models import (
    UserModel, FornecedorModel, ConceptoModel, FundoModel, MovimentoFinanceiroModel
)
from app.infrastructure.auth import hash_password


COMPANY_ID = uuid4()


async def seed():
    await init_db()
    async with AsyncSessionLocal() as db:
        admin = UserModel(
            id=uuid4(),
            company_id=COMPANY_ID,
            email="admin@financeiro.ao",
            hashed_password=hash_password("Admin@1234"),
            full_name="Administrador",
            is_active=True,
        )
        financeiro = UserModel(
            id=uuid4(),
            company_id=COMPANY_ID,
            email="financeiro@financeiro.ao",
            hashed_password=hash_password("Finance@1234"),
            full_name="Gestor Financeiro",
            is_active=True,
        )
        db.add_all([admin, financeiro])
        await db.flush()

        fornecedores_data = [
            ("Distribuidora Central Lda", "5417235LA031", "+244 923 456 789", "geral@distcentral.ao", "Rua da Indústria, 45, Luanda"),
            ("TechSupply Angola", "5423100LA041", "+244 912 345 678", "tech@techsupply.ao", "Av. 4 de Fevereiro, 12"),
            ("Construções Modernas", "5431200LA051", "+244 934 567 890", "admin@construcoes.ao", "Bairro Miramar, Luanda"),
            ("Serviços Gerais Lda", "5441100LA061", "+244 945 678 901", "info@servicos.ao", "Rua Comandante Valódia"),
            ("Materiais e Equipamentos", "5451200LA071", "+244 956 789 012", "mat@equip.ao", "Zona Industrial Viana"),
        ]
        fornecedores = []
        for nome, nif, tel, email, end in fornecedores_data:
            f = FornecedorModel(
                id=uuid4(),
                company_id=COMPANY_ID,
                nome=nome,
                nif=nif,
                telefone=tel,
                email=email,
                endereco=end,
                estado="ativo",
            )
            db.add(f)
            fornecedores.append(f)
        await db.flush()

        conceitos_data = [
            ("Combustível", "Despesas com combustível e lubrificantes"),
            ("Manutenção", "Serviços de manutenção e reparação"),
            ("Material de Escritório", "Compra de materiais e consumíveis"),
            ("Consultoria", "Serviços de consultoria especializada"),
            ("Fornecimento de Água", "Serviços de abastecimento de água"),
            ("Equipamentos", "Aquisição de equipamentos"),
            ("Serviços de Limpeza", "Contrato de limpeza e higienização"),
        ]
        conceitos = []
        for nome, desc in conceitos_data:
            c = ConceptoModel(
                id=uuid4(),
                company_id=COMPANY_ID,
                nome=nome,
                descricao=desc,
                estado="ativo",
            )
            db.add(c)
            conceitos.append(c)
        await db.flush()

        fundo = FundoModel(
            id=uuid4(),
            company_id=COMPANY_ID,
            data=datetime.utcnow(),
            descricao="Fundo operacional 2024",
            valor_disponivel=Decimal("5000000.00"),
            acumulado=Decimal("0.00"),
            saldo_atual=Decimal("5000000.00"),
            observacao="Fundo inicial constituído para operações do exercício",
        )
        db.add(fundo)
        await db.flush()

        estados = ["pendente", "pago", "cancelado"]
        tipos = ["saida", "entrada"]
        acumulado = Decimal("0.00")

        for i in range(30):
            tipo = random.choice(tipos)
            estado = random.choice(estados)
            valor = Decimal(str(round(random.uniform(5000, 200000), 2)))
            if tipo == "saida" and estado == "pago":
                acumulado += valor

            m = MovimentoFinanceiroModel(
                id=uuid4(),
                company_id=COMPANY_ID,
                data=datetime.utcnow() - timedelta(days=random.randint(0, 90)),
                fornecedor_id=random.choice(fornecedores).id,
                conceito_id=random.choice(conceitos).id,
                fatura_proforma=f"FP-{2024}-{i+1:04d}",
                valor=valor,
                fatura_recibo=f"FR-{2024}-{i+1:04d}" if estado == "pago" else None,
                observacoes=f"Movimento de {tipo} - referência {i+1}",
                tipo_movimento=tipo,
                estado_pagamento=estado,
                created_by=admin.id,
            )
            db.add(m)

        saldo_final = Decimal("5000000.00") - acumulado
        fundo.acumulado = acumulado
        fundo.saldo_atual = saldo_final

        await db.commit()
        print("Seed concluído com sucesso!")
        print(f"Company ID: {COMPANY_ID}")
        print("Utilizadores criados:")
        print(f"  admin@financeiro.ao / Admin@1234")
        print(f"  financeiro@financeiro.ao / Finance@1234")


if __name__ == "__main__":
    asyncio.run(seed())
