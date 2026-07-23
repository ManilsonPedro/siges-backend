# PROMPT — Dashboard Executivo: Centro de Inteligência Operacional (Lavagem)

> Copiar este documento inteiro (ou o sprint específico) como prompt para a sessão de IA que vai implementar o código.
> Complementa `PROMPT_SISTEMA_SIGES_SPRINTS.md` (Sprint 8, BI & Fecho). Este documento detalha especificamente a
> especificação de "Centro de Comando Operacional" para o módulo de Lavagem — o core business do SIGES.

---

## Regras Fixas (idênticas a `PROMPT_SISTEMA_SIGES_SPRINTS.md`)

- Stack: Python 3.11 + FastAPI + SQLAlchemy 2 Async + PostgreSQL, sem Alembic (`migrar.py` + scripts idempotentes).
- Reutilizar RBAC (`dashboard.ver`), Auditoria, Soft-delete.
- **Nenhum KPI pode ser inventado.** Se o dado não existir na BD, o indicador fica de fora até o schema suportar — nunca um valor fixo/mock (o próprio `bi.py` já declara este princípio no cabeçalho).

---

## Contexto

O pedido original ("Dashboard Executivo SIGES — Operações") propõe ~40 indicadores para o módulo de Lavagem: KPIs, produtividade por hora/dia/semana/mês/box/equipa/funcionário/turno, rankings de serviços e clientes, receita por múltiplas dimensões, tempo de atendimento, consumo, alertas operacionais, e sugestões avançadas (heatmap, retrabalho, no-show, cross-selling, LTV, comparativo entre filiais, previsão por IA).

Uma auditoria ao schema actual (`app/infrastructure/database/models.py`) confirmou que **parte destes indicadores já é calculável hoje** e parte **exige campos/tabelas novas** que não existem. Este documento separa isso em fases.

## Fase 1 — Já implementada (`GET /bi/dashboards/operacional`)

Estes indicadores já estão no backend e ligados ao Dashboard Executivo:

- Lavagens hoje / agendadas hoje / concluídas hoje
- Lavagens em curso (checkin/em_curso/controlo_qualidade)
- Walk-ins hoje vs. reservas hoje
- Taxa de ocupação de boxes (tempo real)
- Água consumida por categoria de veículo
- Top 5 clientes por nº de lavagens concluídas (histórico completo)
- Avaliação média de qualidade (1-5, todas as ordens)
- Cancelamentos hoje
- Taxa de retrabalho (% de ordens concluídas com `re_lavagem_de_id` preenchido)
- Top 5 extras mais vendidos (por contagem)

**Critério de aceitação:** já cumprido — ver `bi.py::dashboard_operacional` e `dashboard/relatorios/executivo/page.tsx`.

---

## Fase 2 — Concluída: timestamps por transição de estado

**Desbloqueou:** Tempo Médio de Atendimento (check-in → conclusão), Tempo Médio de Espera na Fila.
**Ainda por fazer dentro desta fase:** Eficiência Operacional (lavagens/hora), Produtividade por Turno, Heatmap — ver nota abaixo.

### O que foi implementado

- `OrdemLavagemModel` ganhou `checkin_em`, `iniciado_em`, `controlo_qualidade_em`, `concluido_em` (todos `DateTime`, nullable) — `updated_at` continua a ser sobrescrito a cada transição (comportamento antigo preservado), mas agora cada transição também grava o seu próprio timestamp dedicado, que nunca é apagado por uma transição posterior.
- Migração idempotente em `migrar_dashboard_lavagem.py` (`ADD COLUMN IF NOT EXISTS`), registada em `migrar.py`.
- `operacoes_lavagem.py`: `/checkin`, `/iniciar`, `/controlo-qualidade`, `/concluir` preenchem o timestamp correspondente.
- `GET /bi/dashboards/operacional` → `lavagem_tempo_medio_atendimento_minutos` (média de `concluido_em - checkin_em` sobre ordens com ambos preenchidos) e `lavagem_tempo_medio_espera_minutos` (média de `agora - created_at` sobre ordens ainda em `agendada`/`confirmada`/`checkin`).
- Ligado ao Dashboard Executivo (`dashboard/relatorios/executivo/page.tsx`).

### Ainda por fazer (não incluído nesta implementação)

- [ ] Produtividade por hora/turno: agrupar `checkin_em`/`concluido_em` por hora do dia — especificar endpoint `GET /bi/dashboards/operacional/produtividade-horaria?data=` quando este sprint avançar. Não implementado porque exige decidir a granularidade de agrupamento (por hora civil? por turno operacional?) antes de codificar.

**Critério de aceitação:** cumprido para tempo médio de atendimento/espera — testar criando uma ordem, fazendo check-in, iniciar e concluir com um intervalo real (ex.: 40 min) e confirmando que `lavagem_tempo_medio_atendimento_minutos` reflecte esse valor.

---

## Fase 3 — Concluída: preço persistido na ordem

**Desbloqueou:** Ticket Médio da Lavagem, Receita da Lavagem (hoje/total).
**Ainda por fazer dentro desta fase:** Receita por Box/Equipa/Funcionário/Produto, Ranking de Serviços por rentabilidade — ver nota abaixo.

### O que foi implementado

- `OrdemLavagemModel.preco_total_snapshot` (Numeric(10,2), nullable) — preenchido em `POST /ordens/{id}/concluir` com o valor calculado por `_calcular_preco_ordem` **nesse instante** (tipo + categoria do veículo + extras vigentes), antes de a ordem passar a `concluida`. Não muda retroactivamente se o catálogo de preços for alterado depois.
- `_to_response` em `operacoes_lavagem.py` usa `preco_total_snapshot` quando já preenchido (ordem concluída/paga) em vez de recalcular pelo catálogo actual — histórico fica estável.
- `GET /bi/dashboards/operacional` → `lavagem_receita_total`, `lavagem_receita_hoje`, `lavagem_ticket_medio` (todos sobre `preco_total_snapshot`, só ordens já concluídas).
- Ligado ao Dashboard Executivo.

### Ainda por fazer (não incluído nesta implementação)

- [ ] Receita por Box: agrupar `preco_total_snapshot` por `box_id`.
- [ ] Receita por Equipa: agrupar por `equipa` (CSV de user_id) — exige parsear o CSV ou aguardar decisão da Fase 4 sobre atribuição individual.
- [ ] Receita por Tipo de Serviço: agrupar por `tipo_lavagem_id`.
- [ ] Ranking de Serviços por rentabilidade: depende de custo por serviço, que não existe no schema (só `preco_base`, sem custo associado) — precisa de decisão de negócio sobre como modelar custo antes de avançar.

Não implementados nesta passagem por serem "mais uma dimensão de agrupamento" sobre a mesma coluna, não um bloqueio de schema — podem ser adicionados a pedido, individualmente, sem necessidade de mais migrações.

**Critério de aceitação:** cumprido para ticket médio/receita — concluir uma lavagem grava o preço nesse momento; mudar o `preco_base` do `TipoLavagem` depois não altera o valor já gravado nas ordens antigas.

---

## Fase 4 — Concluída: atribuição individual (colaborador_responsavel_id)

**Desbloqueou:** Produtividade por Colaborador (ranking individual: nº lavagens, receita, tempo médio).

### Decisão de negócio tomada

Adicionar campo opcional `OrdemLavagemModel.colaborador_responsavel_id`, preenchido manualmente pelo operador — sem reestruturar o conceito de equipa colectiva (`OrdemLavagemModel.equipa` continua a existir e a ser preenchido automaticamente via `EscalaTurno`, como já era). Produtividade fica disponível **tanto colectiva (por equipa/box) quanto individual** (por colaborador, quando indicado).

### O que foi implementado

- `OrdemLavagemModel.colaborador_responsavel_id` (nullable) — não obrigatório, para não impor trabalho extra ao operador quando não for necessário o detalhe individual.
- `POST /ordens/{id}/iniciar` aceita `colaborador_responsavel_id` opcional, validando que pertence à equipa escalada para aquele box/turno.
- `PATCH /ordens/{id}/colaborador-responsavel` — permite corrigir/atribuir depois do início, mesmo já concluída.
- `GET /bi/dashboards/operacional` → `lavagem_produtividade_colaboradores`: nº de lavagens, receita (via `preco_total_snapshot`) e tempo médio por colaborador, só sobre ordens concluídas com o campo preenchido.
- Ligado ao Dashboard Executivo.

**Critério de aceitação:** iniciar uma lavagem indicando o colaborador responsável e concluí-la faz esse colaborador aparecer em `lavagem_produtividade_colaboradores` com os valores correctos.

---

## Fase 5 — Concluída: entidade `Filial` e comparativo entre unidades

**Desbloqueou:** Comparativo entre Filiais (nº lavagens, receita).

### Decisão de negócio tomada

A empresa tem várias unidades físicas — Fase 5 implementada.

### O que foi implementado

- `FilialModel` (id, company_id, nome, morada, activo) — CRUD completo em `operacoes_estacao.py` (`/operacoes/estacao/filiais`), reutilizando a permissão `operacoes.estacao.gerir_equipamentos`.
- `BoxLavagemModel.filial_id` (denormalizado, nullable) — evita join através de `areas_servico` em toda agregação de BI; associável ao criar/editar um box.
- `GET /bi/dashboards/operacional` → `lavagem_comparativo_filiais`: nº de lavagens e receita por filial, só para filiais cadastradas (sem inventar "filial padrão" quando não há nenhuma).
- Frontend: `dashboard/configuracoes/filiais` deixou de ser mockup (era dados fixos) e passa a ser CRUD real; formulário de criação de Box em `dashboard/operacoes/lavagem` ganhou selector de filial (só aparece se houver filiais cadastradas).
- Ligado ao Dashboard Executivo.

**Critério de aceitação:** criar 2 filiais, associar boxes diferentes a cada uma, concluir lavagens em boxes de ambas, e confirmar que `lavagem_comparativo_filiais` reflecte os números certos por filial.

---

## Fase 6 — No-Show, Heatmap, LTV, Cross-selling (Concluída)

**Decisão de negócio confirmada:** No-Show modelado como flag booleana `no_show` sobre o estado `cancelada` existente (não um estado novo), distinguindo não-comparência de cancelamento activo do cliente.

### O que foi implementado

- `OrdemLavagemModel.no_show` (Boolean, default False) — `POST /operacoes/lavagem/ordens/{id}/no-show` (`marcar_no_show`): permitido apenas em `agendada`/`confirmada`, liberta o slot e marca `estado=cancelada, no_show=True`.
- `GET /bi/dashboards/operacional` → `lavagem_no_show_hoje`: contagem de não comparências do dia.
- `bi_lavagem_avancado.py` (novo router, prefixo `/api/v1/bi`):
  - `GET /lavagem/heatmap-movimento?dias=30` — agregação de check-ins por (dia da semana, hora).
  - `GET /lavagem/valor-por-cliente` — lifetime value por cliente sobre `preco_total_snapshot`.
  - `GET /lavagem/cross-selling` — % de clientes de lavagem que também compraram em loja/restaurante/bar no mesmo dia.
- Frontend: `bi-lavagem-avancado.service.ts` (novo) consome os 3 endpoints; `dashboard/operacoes/lavagem/fila` ganhou botão "Não compareceu" (oculto para walk-ins); `dashboard/relatorios/executivo` ganhou secção "Analytics Avançado · Lavagem" com heatmap visual (grid dia×hora), top clientes por LTV, e indicadores de cross-selling; card "Não Comparências Hoje" adicionado à secção de Operações.
- **Previsão de Procura (IA)**: mantida fora de escopo — exige decisão de negócio sobre modelo/serviço a usar; não implementar sem pedido explícito.

**Critério de aceitação:** marcar uma reserva como no-show e confirmar que `lavagem_no_show_hoje` incrementa e o slot é libertado; confirmar que o heatmap reflecte os horários reais de check-in; confirmar que o LTV por cliente soma `preco_total_snapshot` das lavagens concluídas; confirmar que a taxa de cross-selling só considera clientes com lavagem E compra no mesmo dia.

---

## Ordem de execução recomendada

```
Fase 1 (concluída, incluindo cancelamentos/retrabalho/extras)
   ↓
Fase 2 (concluída: tempo médio de atendimento/espera — produtividade por turno ainda por especificar)
   ↓
Fase 3 (concluída: ticket médio/receita — receita por box/equipa/serviço ainda por adicionar)
   ↓
Fase 4 (concluída: produtividade individual via colaborador_responsavel_id, opcional)
Fase 5 (concluída: entidade Filial + comparativo entre unidades)
   ↓
Fase 6 (concluída: no-show, heatmap, LTV, cross-sell)
IA de previsão                     — fora de escopo até decisão de negócio explícita
```

Cada fase é autossuficiente para ser copiada como prompt isolado.
