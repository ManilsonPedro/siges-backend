# Backend SIGES — notas para trabalho futuro

## Migrações de schema (sem Alembic)

Este projeto **não usa Alembic**. As tabelas são criadas por
`Base.metadata.create_all` (chamado uma vez, ver `app/infrastructure/database/__init__.py`),
que **cria tabelas em falta mas nunca altera tabelas já existentes** — não
adiciona colunas novas, não remove colunas obsoletas, não faz rename.

Isto já causou bugs reais em produção: colunas adicionadas a um modelo
SQLAlchemy (`app/infrastructure/database/models.py`) simplesmente não
apareciam na base de dados real, porque a tabela já existia de uma versão
anterior do modelo.

### Processo obrigatório para qualquer alteração de schema

Sempre que um sprint adicionar uma coluna, remover uma coluna, ou alterar
uma tabela **que já existe em produção** (não uma tabela nova):

1. Criar `backend/migrar_<algo>.py` — script idempotente com
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `DROP COLUMN IF EXISTS`,
   `DROP TABLE IF EXISTS`, etc. Seguir o padrão de
   `migrar_colunas_lavagem.py` (SQLAlchemy async, expõe `async def main()`,
   corre standalone com `DB_URL='...' python migrar_<algo>.py`).
2. Adicionar o nome do módulo à lista `MODULOS` em `backend/migrar.py` —
   este é o ponto de entrada único que corre todos os scripts em sequência.
3. `migrar.py` corre automaticamente no arranque da app (`app/main.py`,
   logo depois de `migrate.py` e antes dos scripts de seed) — não é
   necessário lembrar ninguém de correr scripts manuais em produção.
4. Antes de dar o sprint como concluído, validar contra uma cópia real da
   BD (branch de dev do Neon, não uma BD vazia local) que o schema fica
   idêntico ao esperado pelos modelos — um `CREATE TABLE` numa BD vazia
   esconde exactamente este tipo de bug.

### Scripts legados (não seguir este padrão para novo trabalho)

- `migrate.py` — script histórico com todas as migrações aditivas desde a
  origem do projeto (`MIGRATIONS` é uma lista append-only). Continua a
  correr no arranque; não reescrever entradas antigas, só adicionar.
- `migrate_drop_role.py` — script one-time com pré-condições especiais
  (anti-lockout de RBAC). Não corre automaticamente — só invocar
  manualmente quando as pré-condições estiverem confirmadas.

## Contexto de negócio

Ver `../PROMPT_SISTEMA_SIGES_SPRINTS.md` (raiz do repositório) para o mapa
de estado real do sistema e o plano de sprints em curso, e
`../SIGES_BI_JENNOS_Documento_Visao_Arquitetural.md` para a visão de alto
nível (Secção 2.4 documenta a remoção de Combustível/Primavera/Produção
Industrial/Logística decidida em 23/07/2026).
