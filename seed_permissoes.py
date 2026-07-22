"""
Seed do catálogo de permissões e grupos default por empresa.
Idempotente — pode ser corrido várias vezes.

Uso:
    DB_URL='...' python seed_permissoes.py
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

# Catálogo de permissões: (codigo, modulo, menu(página), acao, descricao)
PERMISSOES = [
    # ─── Operacional ───
    ("dashboard.ver", "Operacional", "dashboard", "ver", "Ver Dashboard"),
    ("movimentos.listar", "Operacional", "movimentos", "listar", "Listar movimentos"),
    ("movimentos.criar", "Operacional", "movimentos", "criar", "Criar movimentos"),
    ("movimentos.editar", "Operacional", "movimentos", "editar", "Editar movimentos"),
    ("movimentos.cancelar", "Operacional", "movimentos", "cancelar", "Cancelar movimentos"),
    ("movimentos.fechar", "Operacional", "movimentos", "fechar", "Fechar/mudar estado"),
    ("movimentos.ver_detalhes", "Operacional", "movimentos", "ver_detalhes", "Ver detalhes completos"),
    ("movimentos.anexar", "Operacional", "movimentos", "anexar", "Carregar anexos"),
    ("movimentos.exportar", "Operacional", "movimentos", "exportar", "Exportar Excel/PDF"),
    # ─── Cadastros ───
    ("fornecedores.listar", "Cadastros", "fornecedores", "listar", "Listar fornecedores"),
    ("fornecedores.criar", "Cadastros", "fornecedores", "criar", "Criar fornecedores"),
    ("fornecedores.editar", "Cadastros", "fornecedores", "editar", "Editar fornecedores"),
    ("fornecedores.eliminar", "Cadastros", "fornecedores", "eliminar", "Eliminar fornecedores"),
    ("fornecedores.gerir_contratos", "Cadastros", "fornecedores", "gerir_contratos", "Gerir contratos de fornecedores"),
    ("fornecedores.avaliar", "Cadastros", "fornecedores", "avaliar", "Avaliar fornecedores"),
    ("clientes.listar", "Cadastros", "clientes", "listar", "Listar clientes"),
    ("clientes.criar", "Cadastros", "clientes", "criar", "Criar clientes"),
    ("clientes.editar", "Cadastros", "clientes", "editar", "Editar clientes"),
    ("clientes.eliminar", "Cadastros", "clientes", "eliminar", "Eliminar clientes"),
    ("conceitos.listar", "Cadastros", "conceitos", "listar", "Listar conceitos"),
    ("conceitos.criar", "Cadastros", "conceitos", "criar", "Criar conceitos"),
    ("conceitos.editar", "Cadastros", "conceitos", "editar", "Editar conceitos"),
    ("conceitos.eliminar", "Cadastros", "conceitos", "eliminar", "Eliminar conceitos"),
    ("produtos.listar", "Cadastros", "produtos", "listar", "Listar produtos"),
    ("produtos.criar", "Cadastros", "produtos", "criar", "Criar produtos"),
    ("produtos.editar", "Cadastros", "produtos", "editar", "Editar produtos"),
    ("produtos.eliminar", "Cadastros", "produtos", "eliminar", "Eliminar produtos"),
    # ─── Estoque & Caixa ───
    ("estoque.ver", "Estoque", "estoque", "ver", "Ver estoque/armazéns"),
    ("estoque.movimentar", "Estoque", "estoque", "movimentar", "Movimentar estoque (entradas/saídas)"),
    ("estoque.gerir_localizacoes", "Estoque", "estoque", "gerir_localizacoes", "Gerir localizações físicas nos armazéns"),
    ("estoque.realizar_inventario", "Estoque", "estoque", "realizar_inventario", "Realizar contagens físicas de inventário"),
    ("caixa.ver", "Caixa", "caixa", "ver", "Ver caixa/vendas"),
    ("caixa.vender", "Caixa", "caixa", "vender", "Registar vendas no caixa"),
    ("caixa.processar_devolucao", "Caixa", "caixa", "processar_devolucao", "Processar devoluções de vendas"),
    # ─── Loja (Comércio) ───
    ("loja.view", "Comércio", "loja", "view", "Ver promoções da loja"),
    ("loja.gerir_promocoes", "Comércio", "loja", "gerir_promocoes", "Criar/editar promoções da loja"),
    # ─── E-Commerce (Comércio) ───
    ("ecommerce.view", "Comércio", "ecommerce", "view", "Ver pedidos/config do e-commerce"),
    ("ecommerce.gerir_config", "Comércio", "ecommerce", "gerir_config", "Configurar a loja online"),
    ("ecommerce.gerir_cupoes", "Comércio", "ecommerce", "gerir_cupoes", "Gerir cupões de desconto"),
    ("ecommerce.processar_pedidos", "Comércio", "ecommerce", "processar_pedidos", "Processar pedidos online (estado, entrega)"),
    # ─── Operações — Gestão da Estação ───
    ("operacoes.estacao.view", "Operações", "operacoes_estacao", "view", "Ver áreas de serviço/equipamentos/turnos"),
    ("operacoes.estacao.gerir_equipamentos", "Operações", "operacoes_estacao", "gerir_equipamentos", "Gerir áreas de serviço e equipamentos"),
    ("operacoes.estacao.gerir_turnos", "Operações", "operacoes_estacao", "gerir_turnos", "Gerir turnos operacionais"),
    # ─── Operações — Combustível ───
    ("operacoes.combustivel.view", "Operações", "operacoes_combustivel", "view", "Ver tanques/bombas/abastecimentos"),
    ("operacoes.combustivel.registar_leitura", "Operações", "operacoes_combustivel", "registar_leitura", "Registar leitura de tanque de combustível"),
    ("operacoes.combustivel.gerir_bombas", "Operações", "operacoes_combustivel", "gerir_bombas", "Gerir tanques/bombas/bicos"),
    ("operacoes.combustivel.ver_alertas_perda", "Operações", "operacoes_combustivel", "ver_alertas_perda", "Ver alertas de perda de combustível"),
    # ─── Operações — Lavagem Automóvel ───
    ("operacoes.lavagem.view", "Operações", "operacoes_lavagem", "view", "Ver tipos/boxes/ordens de lavagem"),
    ("operacoes.lavagem.gerir_tipos", "Operações", "operacoes_lavagem", "gerir_tipos", "Gerir tipos de lavagem e boxes"),
    ("operacoes.lavagem.agendar", "Operações", "operacoes_lavagem", "agendar", "Agendar slots e criar ordens de lavagem"),
    ("operacoes.lavagem.operar", "Operações", "operacoes_lavagem", "operar", "Operar ordens de lavagem (checkin/iniciar/concluir)"),
    ("operacoes.lavagem.avaliar_qualidade", "Operações", "operacoes_lavagem", "avaliar_qualidade", "Avaliar qualidade de lavagens"),
    # ─── Operações — Gestão da Água ───
    ("operacoes.agua.view", "Operações", "operacoes_agua", "view", "Ver tanques de água/indicadores"),
    ("operacoes.agua.registar_leitura", "Operações", "operacoes_agua", "registar_leitura", "Registar leitura/consumo de água"),
    # ─── Restauração ───
    ("restauracao.view", "Restauração", "restauracao", "view", "Ver mesas/comandas/itens de menu"),
    ("restauracao.gerir_menu", "Restauração", "restauracao", "gerir_menu", "Gerir mesas e itens de menu"),
    ("restauracao.operar_comanda", "Restauração", "restauracao", "operar_comanda", "Operar comandas (criar/adicionar/fechar)"),
    ("restauracao.gerir_happy_hour", "Restauração", "restauracao", "gerir_happy_hour", "Gerir Happy Hour do Bar"),
    ("restauracao.gerir_reservas", "Restauração", "restauracao", "gerir_reservas", "Gerir reservas do Restaurante"),
    ("restauracao.fechar_conta", "Restauração", "restauracao", "fechar_conta", "Fechar conta consolidada de mesa"),
    ("restauracao.gerir_combos", "Restauração", "restauracao", "gerir_combos", "Gerir combos da Churrasqueira"),
    ("restauracao.operar_producao", "Restauração", "restauracao", "operar_producao", "Operar fila de produção (KDS)"),
    # ─── CRM ───
    ("crm.view", "Gestão Comercial", "crm", "view", "Ver leads/oportunidades/pipeline"),
    ("crm.create", "Gestão Comercial", "crm", "create", "Criar leads/oportunidades/viaturas/visitas/tarefas"),
    ("crm.edit", "Gestão Comercial", "crm", "edit", "Editar leads/oportunidades/viaturas/visitas/tarefas"),
    ("crm.delete", "Gestão Comercial", "crm", "delete", "Eliminar registos de CRM"),
    ("crm.gerir_pipeline", "Gestão Comercial", "crm", "gerir_pipeline", "Gerir etapas do pipeline e mover oportunidades"),
    ("crm.gerir_fidelizacao", "Gestão Comercial", "crm", "gerir_fidelizacao", "Gerir programas de fidelização"),
    # ─── Marketing ───
    ("marketing.view", "Gestão Comercial", "marketing", "view", "Ver segmentos/campanhas"),
    ("marketing.gerir_segmentos", "Gestão Comercial", "marketing", "gerir_segmentos", "Gerir segmentos de clientes"),
    ("marketing.gerir_campanhas", "Gestão Comercial", "marketing", "gerir_campanhas", "Criar/editar campanhas"),
    ("marketing.enviar_campanhas", "Gestão Comercial", "marketing", "enviar_campanhas", "Enviar campanhas"),
    # ─── Atendimento ───
    ("atendimento.view", "Gestão Comercial", "atendimento", "view", "Ver reclamações/tickets/sugestões"),
    ("atendimento.gerir_reclamacoes", "Gestão Comercial", "atendimento", "gerir_reclamacoes", "Gerir reclamações e sugestões"),
    ("atendimento.gerir_tickets", "Gestão Comercial", "atendimento", "gerir_tickets", "Gerir tickets de suporte"),
    # ─── Financeiro — Tesouraria e Gestão ───
    ("financeiro.tesouraria.view", "Financeiro", "financeiro_tesouraria", "view", "Ver fluxo de caixa/transferências"),
    ("financeiro.tesouraria.gerir_transferencias", "Financeiro", "financeiro_tesouraria", "gerir_transferencias", "Registar transferências entre fundos"),
    ("financeiro.ver", "Financeiro", "financeiro_gestao", "ver", "Ver aprovações financeiras"),
    ("financeiro.aprovar", "Financeiro", "financeiro_gestao", "aprovar", "Aprovar/rejeitar movimentos financeiros"),
    ("financeiro.gerir_centros_custo", "Financeiro", "financeiro_gestao", "gerir_centros_custo", "Gerir centros de custo"),
    ("financeiro.contas_receber.view", "Financeiro", "contas_receber", "view", "Ver contas a receber"),
    ("financeiro.contas_receber.gerir", "Financeiro", "contas_receber", "gerir", "Criar contas a receber"),
    ("financeiro.contas_receber.registar_recebimento", "Financeiro", "contas_receber", "registar_recebimento", "Registar recebimentos"),
    ("financeiro.contas_pagar.view", "Financeiro", "contas_pagar", "view", "Ver contas a pagar"),
    ("financeiro.contas_pagar.gerir", "Financeiro", "contas_pagar", "gerir", "Criar contas a pagar"),
    ("financeiro.contas_pagar.registar_pagamento", "Financeiro", "contas_pagar", "registar_pagamento", "Registar pagamentos"),
    # ─── Contabilidade ───
    ("contabilidade.ver", "Contabilidade", "contabilidade", "ver", "Ver balancetes/razão/diário (leitura, fonte interna)"),
    ("contabilidade.gerir_plano_contas", "Contabilidade", "contabilidade", "gerir_plano_contas", "Gerir plano de contas"),
    # ─── Fiscalidade ───
    ("fiscalidade.view", "Fiscalidade", "fiscalidade", "view", "Ver taxas/obrigações/IVA"),
    ("fiscalidade.gerir_taxas", "Fiscalidade", "fiscalidade", "gerir_taxas", "Gerir taxas de imposto"),
    ("fiscalidade.gerir_obrigacoes", "Fiscalidade", "fiscalidade", "gerir_obrigacoes", "Gerir obrigações fiscais"),
    # ─── Recursos Humanos ───
    ("rh.view", "Capital Humano", "rh", "view", "Ver colaboradores/departamentos/organograma"),
    ("rh.gerir_colaboradores", "Capital Humano", "rh", "gerir_colaboradores", "Gerir colaboradores"),
    ("rh.gerir_departamentos", "Capital Humano", "rh", "gerir_departamentos", "Gerir departamentos"),
    ("rh.gerir_contratos", "Capital Humano", "rh", "gerir_contratos", "Gerir contratos de colaboradores"),
    ("rh.registar_ponto", "Capital Humano", "rh", "registar_ponto", "Registar ponto (entrada/saída)"),
    ("rh.aprovar_ferias", "Capital Humano", "rh", "aprovar_ferias", "Aprovar/rejeitar pedidos de férias"),
    ("rh.aprovar_horas_extra", "Capital Humano", "rh", "aprovar_horas_extra", "Aprovar horas extra"),
    ("rh.avaliar", "Capital Humano", "rh", "avaliar", "Criar avaliações de desempenho"),
    ("rh.gerir_objetivos", "Capital Humano", "rh", "gerir_objetivos", "Gerir objetivos e competências"),
    ("rh.gerir_formacoes", "Capital Humano", "rh", "gerir_formacoes", "Gerir formações de colaboradores"),
    ("rh.payroll.view", "Capital Humano", "rh_payroll", "view", "Ver folhas de pagamento/recibos"),
    ("rh.payroll.gerir_subsidios", "Capital Humano", "rh_payroll", "gerir_subsidios", "Gerir subsídios de colaboradores"),
    ("rh.payroll.gerir_descontos", "Capital Humano", "rh_payroll", "gerir_descontos", "Gerir descontos de colaboradores"),
    ("rh.payroll.processar_folha", "Capital Humano", "rh_payroll", "processar_folha", "Processar folha de pagamento"),
    # ─── Compras (Supply Chain) ───
    ("compras.ver", "Compras", "compras", "ver", "Ver requisições/pedidos/receções"),
    ("compras.criar_requisicao", "Compras", "compras", "criar_requisicao", "Criar/submeter requisições de compra"),
    ("compras.aprovar", "Compras", "compras", "aprovar", "Aprovar/rejeitar requisições de compra"),
    ("compras.gerir_pedidos", "Compras", "compras", "gerir_pedidos", "Converter requisições em pedidos e confirmar pedidos"),
    ("compras.receber", "Compras", "compras", "receber", "Registar e confirmar receções de mercadoria"),
    # ─── Financeiro ───
    ("fundos.ver", "Financeiro", "fundos", "ver", "Ver fundos"),
    ("fundos.carregar", "Financeiro", "fundos", "carregar", "Carregar valor disponibilizado"),
    ("orcamentos.ver", "Financeiro", "orcamentos", "ver", "Ver orçamentos"),
    ("orcamentos.gerir", "Financeiro", "orcamentos", "gerir", "Criar/editar orçamentos"),
    ("periodos.ver", "Financeiro", "periodos", "ver", "Ver períodos"),
    ("periodos.fechar", "Financeiro", "periodos", "fechar", "Fechar/reabrir períodos"),
    # ─── Relatórios ───
    ("relatorios.ver", "Relatórios", "relatorios", "ver", "Ver relatórios"),
    ("relatorios.exportar", "Relatórios", "relatorios", "exportar", "Exportar relatórios"),
    ("auditoria.ver", "Relatórios", "auditoria", "ver", "Ver auditoria"),
    # ─── Administração ───
    ("users.listar", "Administração", "users", "listar", "Listar utilizadores"),
    ("users.gerir", "Administração", "users", "gerir", "Criar/editar utilizadores"),
    ("grupos.gerir", "Administração", "grupos", "gerir", "Gerir grupos e permissões"),
    ("empresa.gerir", "Administração", "empresa", "gerir", "Configurações da empresa"),
    ("lixeira.ver", "Administração", "lixeira", "ver", "Ver e restaurar lixeira"),
]

# Grupos default por empresa (codigo, descricao, lista de codigos de permissoes ou "*")
GRUPOS_DEFAULT = [
    ("Admin", "Acesso total ao sistema", "*"),
    ("Gestor", "Gestor financeiro — tudo excepto admin/grupos", [
        "dashboard.ver",
        "movimentos.listar", "movimentos.criar", "movimentos.editar", "movimentos.cancelar",
        "movimentos.fechar", "movimentos.ver_detalhes", "movimentos.anexar", "movimentos.exportar",
        "fornecedores.listar", "fornecedores.criar", "fornecedores.editar", "fornecedores.eliminar",
        "fornecedores.gerir_contratos", "fornecedores.avaliar",
        "clientes.listar", "clientes.criar", "clientes.editar", "clientes.eliminar",
        "conceitos.listar", "conceitos.criar", "conceitos.editar", "conceitos.eliminar",
        "produtos.listar", "produtos.criar", "produtos.editar", "produtos.eliminar",
        "estoque.ver", "estoque.movimentar", "estoque.gerir_localizacoes", "estoque.realizar_inventario",
        "caixa.ver", "caixa.vender", "caixa.processar_devolucao",
        "loja.view", "loja.gerir_promocoes",
        "ecommerce.view", "ecommerce.gerir_config", "ecommerce.gerir_cupoes", "ecommerce.processar_pedidos",
        "operacoes.estacao.view", "operacoes.estacao.gerir_equipamentos", "operacoes.estacao.gerir_turnos",
        "operacoes.combustivel.view", "operacoes.combustivel.registar_leitura", "operacoes.combustivel.gerir_bombas", "operacoes.combustivel.ver_alertas_perda",
        "operacoes.lavagem.view", "operacoes.lavagem.gerir_tipos", "operacoes.lavagem.agendar", "operacoes.lavagem.operar", "operacoes.lavagem.avaliar_qualidade",
        "operacoes.agua.view", "operacoes.agua.registar_leitura",
        "restauracao.view", "restauracao.gerir_menu", "restauracao.operar_comanda", "restauracao.gerir_happy_hour",
        "restauracao.gerir_reservas", "restauracao.fechar_conta", "restauracao.gerir_combos", "restauracao.operar_producao",
        "crm.view", "crm.create", "crm.edit", "crm.delete", "crm.gerir_pipeline", "crm.gerir_fidelizacao",
        "marketing.view", "marketing.gerir_segmentos", "marketing.gerir_campanhas", "marketing.enviar_campanhas",
        "atendimento.view", "atendimento.gerir_reclamacoes", "atendimento.gerir_tickets",
        "financeiro.tesouraria.view", "financeiro.tesouraria.gerir_transferencias",
        "financeiro.gerir_centros_custo",
        "financeiro.contas_receber.view", "financeiro.contas_receber.gerir", "financeiro.contas_receber.registar_recebimento",
        "financeiro.contas_pagar.view", "financeiro.contas_pagar.gerir", "financeiro.contas_pagar.registar_pagamento",
        "contabilidade.ver", "contabilidade.gerir_plano_contas",
        "fiscalidade.view", "fiscalidade.gerir_taxas", "fiscalidade.gerir_obrigacoes",
        "rh.view", "rh.gerir_colaboradores", "rh.gerir_departamentos", "rh.gerir_contratos",
        "rh.registar_ponto", "rh.aprovar_ferias", "rh.aprovar_horas_extra", "rh.avaliar",
        "rh.gerir_objetivos", "rh.gerir_formacoes",
        "rh.payroll.view", "rh.payroll.gerir_subsidios", "rh.payroll.gerir_descontos", "rh.payroll.processar_folha",
        "compras.ver", "compras.criar_requisicao", "compras.aprovar", "compras.gerir_pedidos", "compras.receber",
        "fundos.ver", "fundos.carregar",
        "orcamentos.ver", "orcamentos.gerir",
        "periodos.ver",
        "relatorios.ver", "relatorios.exportar",
        "auditoria.ver",
    ]),
    ("Assistente", "Assistente — criar movimentos e ver", [
        "dashboard.ver",
        "movimentos.listar", "movimentos.criar", "movimentos.ver_detalhes", "movimentos.anexar",
        "fornecedores.listar", "fornecedores.criar",
        "clientes.listar", "clientes.criar",
        "conceitos.listar", "conceitos.criar",
        "produtos.listar",
        "estoque.ver",
        "caixa.ver", "caixa.vender",
        "fundos.ver",
        "relatorios.ver",
    ]),
    ("Auditoria", "Apenas leitura + auditoria", [
        "dashboard.ver",
        "movimentos.listar", "movimentos.ver_detalhes",
        "fornecedores.listar", "clientes.listar", "conceitos.listar",
        "fundos.ver", "orcamentos.ver", "periodos.ver",
        "relatorios.ver", "relatorios.exportar",
        "auditoria.ver",
    ]),
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
            # Catálogo
            for codigo, modulo, menu, acao, desc in PERMISSOES:
                cur.execute(
                    "INSERT INTO permissoes (id, codigo, modulo, menu, acao, descricao) "
                    "VALUES (gen_random_uuid(), %s, %s, %s, %s, %s) "
                    "ON CONFLICT (codigo) DO UPDATE SET modulo = EXCLUDED.modulo, menu = EXCLUDED.menu, acao = EXCLUDED.acao, descricao = EXCLUDED.descricao",
                    (codigo, modulo, menu, acao, desc),
                )

            # Para cada empresa existente, criar grupos default se faltarem
            cur.execute("SELECT DISTINCT company_id FROM users WHERE company_id IS NOT NULL")
            companies = [row[0] for row in cur.fetchall()]
            print(f"Empresas encontradas: {len(companies)}")

            cur.execute("SELECT id, codigo FROM permissoes")
            perm_map = {codigo: str(pid) for pid, codigo in cur.fetchall()}
            all_perm_ids = list(perm_map.values())

            for cid in companies:
                for nome, desc, perms in GRUPOS_DEFAULT:
                    # Existe?
                    cur.execute("SELECT id FROM grupos WHERE company_id = %s AND nome = %s", (cid, nome))
                    row = cur.fetchone()
                    if row:
                        gid = str(row[0])
                        print(f"  [skip] {cid} :: {nome} já existe")
                    else:
                        gid = str(uuid4())
                        cur.execute(
                            "INSERT INTO grupos (id, company_id, nome, descricao, is_system) "
                            "VALUES (%s, %s, %s, %s, TRUE)",
                            (gid, cid, nome, desc),
                        )
                        print(f"  [new]  {cid} :: {nome}")

                    # Atribuir permissões
                    target_ids = all_perm_ids if perms == "*" else [perm_map[c] for c in perms if c in perm_map]
                    # Limpar e reescrever (idempotente)
                    cur.execute("DELETE FROM grupo_permissoes WHERE grupo_id = %s", (gid,))
                    for pid in target_ids:
                        cur.execute(
                            "INSERT INTO grupo_permissoes (grupo_id, permissao_id) VALUES (%s, %s)",
                            (gid, pid),
                        )

                # Atribuir grupo_id aos utilizadores baseando no role legado.
                # Só corre enquanto a coluna `role` existir (pré-migração drop-role);
                # depois de a coluna ser removida torna-se um no-op idempotente.
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'users' AND column_name = 'role'"
                )
                if cur.fetchone():
                    role_to_grupo = {"admin": "Admin", "financeiro": "Gestor", "assistente": "Assistente", "auditor": "Auditoria"}
                    for role, gnome in role_to_grupo.items():
                        cur.execute("SELECT id FROM grupos WHERE company_id = %s AND nome = %s", (cid, gnome))
                        g = cur.fetchone()
                        if g:
                            cur.execute(
                                "UPDATE users SET grupo_id = %s WHERE company_id = %s AND role = %s AND grupo_id IS NULL",
                                (str(g[0]), cid, role),
                            )

                # Rede de segurança anti-lockout: garantir que existe sempre ≥1
                # utilizador no grupo Admin. Se nenhum utilizador ativo da empresa
                # estiver no grupo Admin, atribui-o ao mais antigo. Cobre instalações
                # de raiz (sem role) e evita ficar sem ninguém capaz de gerir grupos.
                cur.execute("SELECT id FROM grupos WHERE company_id = %s AND nome = 'Admin'", (cid,))
                admin_g = cur.fetchone()
                if admin_g:
                    admin_gid = str(admin_g[0])
                    cur.execute(
                        "SELECT 1 FROM users WHERE company_id = %s AND grupo_id::text = %s "
                        "AND is_active = TRUE AND deleted_at IS NULL LIMIT 1",
                        (cid, admin_gid),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "UPDATE users SET grupo_id = %s WHERE id = ("
                            "  SELECT id FROM users WHERE company_id = %s AND is_active = TRUE "
                            "  AND deleted_at IS NULL ORDER BY created_at ASC LIMIT 1)",
                            (admin_gid, cid),
                        )
                        print(f"  [admin] {cid} :: atribuído grupo Admin ao utilizador mais antigo (anti-lockout)")

        conn.commit()
        print("\nSeed concluído com sucesso.")
    except Exception as e:
        conn.rollback()
        print(f"ERRO: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
