"""
Seed opcional do catálogo de Veículo (Marca, Modelo, Cor) e de Tipos de
Lavagem — popula um conjunto considerável de valores de referência
comuns no mercado angolano, para os dropdowns do portal/backoffice
ficarem úteis desde o primeiro dia, sem obrigar o backoffice a
digitar tudo manualmente.

Idempotente — corre por empresa, só insere o que ainda não existe
(por nome). NÃO é chamado automaticamente no arranque da app (ao
contrário de seed_permissoes.py) — catálogo de marcas/tipos de lavagem
é decisão de negócio de cada empresa, corre-se manualmente quando faz
sentido.

Uso:
    DB_URL='...' python seed_veiculos_catalogo.py
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


url = _resolve_url()

# ─── Marcas + modelos comuns (mercado angolano: forte presença de
# japonesas/coreanas usadas e europeias) ─────────────────────────────
MARCAS_MODELOS = {
    "Toyota": ["Corolla", "Hilux", "Land Cruiser", "RAV4", "Yaris", "Avensis", "Hiace"],
    "Hyundai": ["Tucson", "Elantra", "i10", "i20", "Accent", "Santa Fe"],
    "Kia": ["Sportage", "Picanto", "Rio", "Sorento", "Cerato"],
    "Nissan": ["Qashqai", "Navara", "X-Trail", "Sentra", "Patrol"],
    "Mercedes-Benz": ["Classe C", "Classe E", "GLE", "Sprinter", "Vito"],
    "BMW": ["Série 3", "Série 5", "X3", "X5"],
    "Volkswagen": ["Golf", "Polo", "Passat", "Amarok", "Tiguan"],
    "Mitsubishi": ["Pajero", "L200", "ASX", "Outlander"],
    "Ford": ["Ranger", "Focus", "EcoSport", "Everest"],
    "Honda": ["Civic", "CR-V", "Accord", "Fit"],
    "Chevrolet": ["Spark", "Captiva", "S10"],
    "Renault": ["Duster", "Sandero", "Logan", "Kangoo"],
    "Peugeot": ["208", "308", "3008", "Partner"],
    "Land Rover": ["Discovery", "Range Rover", "Defender"],
    "Suzuki": ["Vitara", "Jimny", "Swift"],
    "Mazda": ["CX-5", "Mazda 3", "BT-50"],
    "Isuzu": ["D-Max", "MU-X"],
    "Audi": ["A4", "A6", "Q5", "Q7"],
    "Volvo": ["XC60", "XC90", "S60"],
    "Fiat": ["Palio", "Doblo", "Strada"],
    "Jeep": ["Wrangler", "Grand Cherokee", "Compass"],
    "Subaru": ["Forester", "Outback"],
    "Mota": ["Bajaj Boxer", "Honda CG", "Yamaha Crypton"],
}

# ─── Cores comuns ─────────────────────────────────────────────────────
CORES = [
    ("Branco", "#FFFFFF"), ("Preto", "#000000"), ("Prata", "#C0C0C0"),
    ("Cinza", "#808080"), ("Vermelho", "#C0392B"), ("Azul", "#2980B9"),
    ("Azul Escuro", "#1B2A4A"), ("Verde", "#27AE60"), ("Verde Escuro", "#1E5631"),
    ("Amarelo", "#F1C40F"), ("Laranja", "#E67E22"), ("Castanho", "#6E4A2E"),
    ("Bege", "#D2B48C"), ("Dourado", "#C9A227"), ("Bordô", "#6D1B2A"),
    ("Roxo", "#6C3483"), ("Rosa", "#E699C4"), ("Grafite", "#3B3B3B"),
    ("Prata Fosco", "#9E9E9E"), ("Champagne", "#E8D9B5"),
]

# ─── Tipos de lavagem (catálogo base, preço em Kz — ajustável no
# backoffice depois) ──────────────────────────────────────────────────
TIPOS_LAVAGEM = [
    ("LAV-SIMPLES", "Lavagem Simples", "Exterior + jantes, sem interior.", 1500, 20, 40),
    ("LAV-COMPLETA", "Lavagem Completa", "Exterior + interior + aspiração.", 2500, 35, 70),
    ("LAV-PREMIUM", "Lavagem Premium", "Completa + cera + pretinho de pneus.", 4000, 50, 90),
    ("LAV-MOTOR", "Lavagem do Motor", "Limpeza e desengorduramento do compartimento do motor.", 2000, 25, 30),
    ("LAV-ESTOFOS", "Lavagem de Estofos/Tapetes", "Lavagem a fundo de bancos e tapetes.", 3500, 60, 15),
    ("LAV-POLIMENTO", "Polimento", "Polimento da carroçaria (remoção de riscos ligeiros).", 8000, 90, 5),
    ("LAV-HIGIENIZACAO", "Higienização A/C", "Desinfecção do sistema de ar condicionado.", 3000, 30, 5),
    ("LAV-MOTOS", "Lavagem de Motociclos", "Lavagem completa para motas/scooters.", 800, 15, 20),
]


def run():
    if not url:
        print("[erro] DB_URL/DATABASE_URL não definida")
        sys.exit(1)

    with psycopg.connect(url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT company_id FROM users WHERE company_id IS NOT NULL")
            companies = [row[0] for row in cur.fetchall()]
            print(f"Empresas encontradas: {len(companies)}")

            for cid in companies:
                print(f"\n--- company_id={cid} ---")

                # Marcas + Modelos
                n_marcas = n_modelos = 0
                for marca_nome, modelos in MARCAS_MODELOS.items():
                    cur.execute(
                        "SELECT id FROM marcas_veiculo WHERE company_id = %s AND nome = %s",
                        (cid, marca_nome),
                    )
                    row = cur.fetchone()
                    if row:
                        marca_id = row[0]
                    else:
                        marca_id = str(uuid4())
                        cur.execute(
                            "INSERT INTO marcas_veiculo (id, company_id, nome, activo) VALUES (%s, %s, %s, true)",
                            (marca_id, cid, marca_nome),
                        )
                        n_marcas += 1

                    for modelo_nome in modelos:
                        cur.execute(
                            "SELECT 1 FROM modelos_veiculo WHERE company_id = %s AND marca_id = %s AND nome = %s",
                            (cid, marca_id, modelo_nome),
                        )
                        if not cur.fetchone():
                            cur.execute(
                                "INSERT INTO modelos_veiculo (id, company_id, marca_id, nome, activo) "
                                "VALUES (%s, %s, %s, %s, true)",
                                (str(uuid4()), cid, marca_id, modelo_nome),
                            )
                            n_modelos += 1
                print(f"  Marcas novas: {n_marcas} · Modelos novos: {n_modelos}")

                # Cores
                n_cores = 0
                for nome, hexcode in CORES:
                    cur.execute(
                        "SELECT 1 FROM cores_veiculo WHERE company_id = %s AND nome = %s", (cid, nome),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO cores_veiculo (id, company_id, nome, hex, activo) VALUES (%s, %s, %s, %s, true)",
                            (str(uuid4()), cid, nome, hexcode),
                        )
                        n_cores += 1
                print(f"  Cores novas: {n_cores}")

                # Tipos de lavagem
                n_tipos = 0
                for codigo, nome, descricao, preco_base, duracao, agua in TIPOS_LAVAGEM:
                    cur.execute(
                        "SELECT 1 FROM tipos_lavagem WHERE company_id = %s AND codigo = %s", (cid, codigo),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO tipos_lavagem "
                            "(id, company_id, codigo, nome, descricao, preco_base, duracao_estimada_minutos, "
                            "agua_estimada_litros, activo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)",
                            (str(uuid4()), cid, codigo, nome, descricao, preco_base, duracao, agua),
                        )
                        n_tipos += 1
                print(f"  Tipos de lavagem novos: {n_tipos}")

            conn.commit()
    print("\nSeed de catálogo de veículo/tipos de lavagem concluído.")


if __name__ == "__main__":
    run()
