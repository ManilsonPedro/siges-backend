# PROMPT — Gestão de Recursos Hídricos (Água): Sprints

> Copiar este documento inteiro (ou o sprint específico) como prompt para a sessão de IA que vai implementar o código.
> Complementa `PROMPT_SISTEMA_SIGES_SPRINTS.md` e `PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md`. Este documento detalha
> a expansão do módulo "Operações · Água" de simples controlo de nível de tanque para um módulo completo de
> Gestão de Recursos Hídricos: abastecimento, consumo, custos, fornecedores, documentos e auditoria.

---

## Estado de implementação: TODAS AS 11 FASES CONCLUÍDAS

Implementação completa em `siges-backend` e `siges-frontend`, `npx tsc --noEmit` e `python -m py_compile`
limpos. Resumo do que foi entregue por fase (detalhe de cada uma nas secções abaixo):

- **Fase 1** — `TanqueAguaModel.filial_id`/`.estado` + PATCH/DELETE.
- **Fase 2** — `FornecedorModel.tipo_pessoa`, reaproveitando o cadastro geral de Fornecedores.
- **Fase 3** — `AbastecimentoAguaModel` (numeração `ABA-<ano>-<seq>`, fornecedor com criação inline, filial,
  fluxo de estado registado→aprovado→documentado→pago→concluído).
- **Fase 4** — `AnexoModel` genérico com versionamento (`entity_type`/`entity_id`/`tipo_documento`/`versao`),
  router `/anexos/{entity_type}/{entity_id}` e componente `AnexosUploader` reutilizável. Não substitui
  `MovimentoAnexoModel` (regras de negócio próprias do fluxo financeiro) — coexistem por decisão explícita.
- **Fase 5** — Geração automática de Proforma/Fatura/Fatura-Recibo/Recibo/Ordem de Receção em PDF
  (`abastecimento_agua_pdf.py`), gravados automaticamente como `AnexoModel` v1+.
- **Fase 6** — `GET /operacoes/agua/abastecimentos` com filtros completos (período, tanque, fornecedor, filial,
  estado, valor min/max, quantidade min/max) + UI de filtros e totais agregados.
- **Fase 7** — `GET /operacoes/agua/consumo-por-dimensao?dimensao=box|colaborador|equipa`. Dimensão `turno` não
  implementada (ver nota na Fase 7 abaixo — cruzamento indirecto via `EscalaTurnoModel` não é confiável o
  suficiente para um KPI).
- **Fase 8** — `MovimentoTanqueAguaModel` tipado (entrada/saída/ajuste/transferência/perda/evaporação/vazamento);
  todo o histórico de abastecimento/consumo/ajuste manual passa a gerar aqui um registo permanente.
- **Fase 9** — `GET /operacoes/agua/alertas`: nível mínimo, capacidade máxima, consumo anormal (>2× média móvel
  30 dias), documentação pendente (>7 dias), custo acima da média (>1.2× média 90 dias). Âmbito específico de
  água, sem motor de alertas genérico (decisão confirmada).
- **Fase 10** — `bi_agua.py`: `GET /bi/agua/dashboard` (KPIs), `/evolucao-custos`, `/consumo-por-servico`,
  `/ranking-fornecedores`, `/ranking-filiais`. Secção "Gestão da Água" adicionada ao Dashboard Executivo.
- **Fase 11** — `GET /operacoes/agua/custos`: custo por abastecimento/fornecedor/filial/tanque + evolução
  mensal do preço médio por litro.

**Confirmado fora de escopo** (ver secção "Fora de escopo deste ciclo"): motor de alertas genérico,
lançamentos contabilísticos automáticos, `ContaPagarModel` automática, aprovação multi-etapa configurável,
estado de fornecedor bloqueado, deteção de fuga por sensor/IoT, dimensão "turno" no consumo por dimensão.

---

## Regras Fixas (idênticas aos documentos anteriores)

- Stack: Python 3.11 + FastAPI + SQLAlchemy 2 Async + PostgreSQL, sem Alembic (`migrar.py` + scripts idempotentes
  `migrar_<nome>.py` registados em `MODULOS`).
- Reutilizar RBAC (`require_permission`), Auditoria (`write_audit`), Soft-delete (`deleted_at`).
- **Nenhum KPI pode ser inventado.** Se o dado não existir na BD, o indicador fica de fora até o schema suportar.
- Toda mudança de backend tem o espelho correspondente no frontend (`shared/types`, `shared/services`, páginas),
  com `npx tsc --noEmit` e `python -m py_compile` limpos antes de commit.

---

## Auditoria ao que já existe (não reinventar)

Antes de desenhar as sprints, foi feito um levantamento ao schema e código actuais. Conclusão: **o módulo de Água
já existe hoje, embora limitado a nível/qualidade de tanque e consumo simples**, e boa parte da infraestrutura
transversal pedida (fornecedores, auditoria, storage, aprovações, compras) **já existe e deve ser reutilizada**,
não recriada.

### Já existe e deve ser reutilizado directamente

| Necessidade do pedido | Já existe como |
|---|---|
| Fornecedor (pessoa/empresa, NIF, contacto) | `FornecedorModel` (`models.py`) — falta só coluna `tipo_pessoa` |
| Filiais | `FilialModel` (`models.py`) — id, company_id, nome, morada, activo |
| Auditoria (quem criou/alterou, IP, user agent) | `AuditLogModel` + `write_audit()` (`app/infrastructure/audit.py`) — já usado em `operacoes_agua.py` |
| Storage de ficheiros (upload, PDF/JPG/PNG/DOCX/XLSX) | `LocalStorageProvider`/`B2StorageProvider` (`app/infrastructure/storage/`) |
| Aprovação em várias etapas | `AprovacaoFinanceiraModel` (estados pendente/aprovado/rejeitado) |
| Compras / requisições / receção de mercadoria | `RequisicaoModel`, `PedidoCompraModel`, `RecepcaoModel` (módulo Compras completo) |
| Contas a pagar / movimentos financeiros | `ContaPagarModel`, `MovimentoFinanceiroModel` |
| Equipamento/área de serviço por filial | `EquipamentoModel`, `AreaServicoModel` (ambos com `filial_id`) |
| Consumo de água já ligado à Lavagem | `TipoLavagemModel.agua_estimada_litros`, `CategoriaVeiculoModel.fator_agua`, `OrdemLavagemModel.agua_consumida_litros`, cálculo em `operacoes_lavagem.py::_calcular_agua_estimada` |
| Referência de desenho para movimentos tipados | `StockMovimentoModel` (entrada/saída/ajuste com tipo + referência) |

### Já existe mas precisa de expansão

- `TanqueAguaModel` (tabela `tanques_agua`): `codigo`, `nome`, `tipo`, `capacidade_litros`, `nivel_atual_litros`,
  `nivel_minimo_litros`, `ph`, `turbidez`, `condutividade`, `tem_sensor`, `sensor_id`, `deleted_at`.
  **Falta**: `filial_id`, `estado` (activo/manutenção/inactivo — hoje só há soft-delete), endpoints de
  edição/desactivação (só há list+create em `operacoes_agua.py`).
- `ConsumoAguaModel` (tabela `consumos_agua`): `tanque_agua_id`, `litros_consumidos`, `tipo`, `referencia_id`,
  `referencia_tipo`, `custo_por_litro`, `custo_total`, `data`. Endpoints `GET/POST /operacoes/agua/consumos` e
  `GET /operacoes/agua/indicadores`. **Falta**: agregação por box/funcionário/equipa/turno (hoje só existe
  por categoria de veículo, usado em `bi.py::lavagem_agua_por_categoria_litros`).
- Alertas de água: já existem limites hardcoded (`PARAMETROS_LIMITE` em `operacoes_agua.py`, ph 6.5–8.5,
  turbidez ≤5) que gravam `write_audit` acção `alerta_tanque_agua`, mas não há tabela/consulta de alertas nem
  notificação — é o mesmo padrão simples usado em `estoque.py::alertas-stock-minimo`.
- Anexos: `MovimentoAnexoModel` existe mas está acoplado a `movimentos_financeiros` (FK `movimento_id`) e não
  tem versionamento — só soft-delete.

### Genuinamente novo

- `AbastecimentoAguaModel` + numeração automática + histórico com filtros (Áreas 2 e 4 do pedido).
- `MovimentoTanqueAguaModel` tipado — entrada/saída/ajuste/transferência/perda/evaporação/vazamento (Área 6).
- Anexos genéricos com versionamento (`entity_type`/`entity_id`/`versao`), substituindo o acoplamento actual
  a `movimentos_financeiros` (Área 3/11).
- Documentos de abastecimento (proforma/fatura/fatura-recibo/recibo/ordem de receção) (Área 3).
- Dashboards/rankings dedicados de água (Área 8).

### Decisões de âmbito confirmadas para este ciclo

1. **Anexos genéricos**: generalizar agora — criar modelo de anexos reutilizável (`entity_type`/`entity_id` +
   versão), usado por Água e disponível para futuros módulos; migrar o uso actual de `MovimentoAnexoModel`
   para o novo modelo.
2. **Alertas**: âmbito específico de Água nesta fase — implementar as regras pedidas directamente no módulo
   de água (como já acontece com Stock), sem construir um motor de regras genérico agora. Isso fica documentado
   como possível trabalho futuro transversal, não implementado neste ciclo.
3. **Integração financeira**: âmbito de registo simples de custo — o abastecimento regista fornecedor, custo
   e documentos; a criação automática de `ContaPagarModel` e lançamentos contabilísticos fica para uma sprint
   futura (o próprio fluxo de Compras/Receção ainda não gera Conta a Pagar automaticamente hoje, portanto não
   faz sentido implementar isso primeiro para Água).

---

## Fase 1 — Tanques: completar CRUD e localização

- `TanqueAguaModel`: adicionar `filial_id` (nullable, FK `filiais.id`) e `estado` (enum: `activo`, `manutencao`,
  `inactivo`; default `activo`).
- Novos endpoints: `PATCH /operacoes/agua/tanques/{id}` (editar dados, incluindo estado) e
  `DELETE /operacoes/agua/tanques/{id}` (soft-delete).
- Frontend: `app/dashboard/operacoes/agua/page.tsx` — formulário de edição e selector de filial/estado.

**Critério de aceitação:** criar um tanque, associá-lo a uma filial, alterar o seu estado para "manutenção" e
confirmar que deixa de aparecer como disponível para novos abastecimentos/consumos.

---

## Fase 2 — Fornecedores de Água (reutilização + pequeno acréscimo)

- `FornecedorModel`: adicionar coluna `tipo_pessoa` (enum: `singular`, `empresa`; nullable para não quebrar
  fornecedores existentes).
- Reutilizar endpoints/páginas de Fornecedores já existentes (`fornecedor.py`, `app/dashboard/fornecedores/`);
  não criar um cadastro de fornecedores paralelo para água.
- No fluxo de registo de abastecimento (Fase 3), permitir cadastrar um novo fornecedor inline caso não exista
  (reaproveitando o endpoint `POST /fornecedores` já existente).

**Critério de aceitação:** um fornecedor de água cadastrado com `tipo_pessoa=empresa` aparece normalmente na
listagem geral de Fornecedores, sem duplicação de tabela.

---

## Fase 3 — Abastecimento de Tanques (novo)

- Novo modelo `AbastecimentoAguaModel`: `numero` (gerado automaticamente, padrão igual a `PedidoCompraModel.numero`),
  `tanque_agua_id`, `fornecedor_id`, `quantidade_litros`, `valor_por_litro`, `custo_total`, `metodo_pagamento`,
  `observacoes`, `filial_id`, `equipamento_id` (nullable), `registado_por_id`, `recebido_por_id` (funcionário
  responsável pela receção), `estado` (enum: `registado`, `aprovado`, `documentado`, `pago`, `concluido`),
  `created_at`.
- Endpoint `POST /operacoes/agua/abastecimentos` — ao confirmar, incrementa `TanqueAguaModel.nivel_atual_litros`
  e cria automaticamente um `MovimentoTanqueAguaModel` do tipo `entrada` (Fase 5) referenciando o abastecimento.
- `write_audit` em cada mudança de estado (quem registou, quem aprovou).
- Frontend: nova página `app/dashboard/operacoes/agua/abastecimentos/page.tsx` com formulário completo
  (tanque, fornecedor com opção "novo fornecedor", quantidade, preço, pagamento, responsável de receção).

**Critério de aceitação:** registar um abastecimento de 5000L a um tanque com 2000L actuais e confirmar que o
nível passa a 7000L, que existe um `MovimentoTanqueAguaModel` tipo `entrada` de 5000L referenciando o
abastecimento, e que o `write_audit` regista o utilizador e a filial.

---

## Fase 4 — Anexos genéricos com versionamento (novo, substitui acoplamento actual)

- Novo modelo `AnexoModel` (tabela `anexos`): `entity_type` (ex. `abastecimento_agua`, `movimento_financeiro`),
  `entity_id`, `tipo_documento` (ex. `proforma`, `fatura`, `fatura_recibo`, `guia_transporte`,
  `comprovativo_pagamento`, `comprovativo_bancario`, `fotografia`, `outro`), `versao` (int, incremental por
  `entity_type`+`entity_id`+`tipo_documento`), `file_path`, `file_name`, `mime_type`, `size_bytes`,
  `uploaded_by`, `uploaded_at`, soft-delete (`deleted_at`, `deleted_by`, `delete_reason`).
- Migrar `MovimentoAnexoModel` para usar este modelo (endpoints existentes em `movimento_detail.py` passam a
  gravar `entity_type="movimento_financeiro"`); manter compatibilidade de leitura para anexos já gravados no
  modelo antigo (script de migração de dados, não apenas de schema).
- Novos endpoints genéricos: `POST /anexos/{entity_type}/{entity_id}`, `GET /anexos/{entity_type}/{entity_id}`,
  `DELETE /anexos/{id}`. Formatos aceites: PDF, JPG, PNG, DOCX, XLSX (validar `mime_type`/extensão).
- Frontend: componente genérico `shared/ui/anexos-uploader.tsx` reutilizável por Água e Financeiro.

**Critério de aceitação:** anexar duas versões de "Proforma" ao mesmo abastecimento e confirmar que ambas ficam
visíveis com histórico de versão, utilizador e data; confirmar que os anexos antigos de movimentos financeiros
continuam acessíveis após a migração.

---

## Fase 5 — Documentos de Abastecimento (proforma/fatura/fatura-recibo/recibo/ordem de receção)

- Reaproveitar o gerador de PDF existente (`app/infrastructure/export/proforma_pdf.py`, `pdf.py`) generalizando-o
  para aceitar `AbastecimentoAguaModel` como origem, além de `VendaModel`.
- Endpoint `POST /operacoes/agua/abastecimentos/{id}/documentos/{tipo}` gera o PDF (proforma, fatura,
  fatura-recibo, recibo, ordem de receção) e grava-o automaticamente como `AnexoModel` (Fase 4) versão 1.
- Fluxo de estado do abastecimento (Fase 3) avança para `documentado` quando a fatura/fatura-recibo tiver sido
  gerada.

**Critério de aceitação:** gerar a Proforma de um abastecimento e confirmar que aparece automaticamente na lista
de anexos como versão 1, sem upload manual.

---

## Fase 6 — Histórico de Abastecimentos (novo, depende da Fase 3)

- Endpoint `GET /operacoes/agua/abastecimentos` com filtros: `data_inicio`/`data_fim`, `tanque_agua_id`,
  `fornecedor_id`, `filial_id`, `estado`, `valor_min`/`valor_max`, `quantidade_min`/`quantidade_max`.
- Frontend: `app/dashboard/operacoes/agua/abastecimentos/page.tsx` ganha tabela com estes filtros e coluna de
  estado documental (nº de anexos por tipo).

**Critério de aceitação:** filtrar abastecimentos de um fornecedor específico num período e confirmar que os
totais (quantidade, custo) batem com a soma manual dos registos filtrados.

---

## Fase 7 — Consumo de Água por dimensão operacional (expande o que já existe)

- Novos agregados em `GET /operacoes/agua/indicadores` (ou endpoint dedicado
  `GET /operacoes/agua/consumo-por-dimensao?dimensao=box|colaborador|equipa|turno|dia|semana|mes`):
  cruzar `ConsumoAguaModel` (via `referencia_tipo="ordem_lavagem"`) com `OrdemLavagemModel.box_id`,
  `.colaborador_responsavel_id`, `.equipa`, `.turno_id` (turno operacional já existente).
- Frontend: secção "Consumo por Box/Equipa/Turno" na página de água, reaproveitando o padrão de tabela usado em
  "Produtividade por Colaborador" do Dashboard Operacional.

**Critério de aceitação:** concluir lavagens em boxes diferentes com tanques diferentes e confirmar que o
consumo agregado por box reflecte litros correctos por cada um.

---

## Fase 8 — Movimentações do Tanque (novo)

- Novo modelo `MovimentoTanqueAguaModel` (tabela `movimentos_tanque_agua`), desenhado como `StockMovimentoModel`:
  `tanque_agua_id`, `tipo` (enum: `entrada`, `saida`, `ajuste`, `transferencia`, `perda`, `evaporacao`,
  `vazamento`), `quantidade_litros`, `nivel_antes`, `nivel_depois`, `referencia_tipo` (ex. `abastecimento`,
  `consumo`, `ajuste_manual`), `referencia_id`, `observacoes`, `registado_por_id`, `created_at`.
- Toda alteração ao `nivel_atual_litros` (abastecimento, consumo, leitura manual) passa a gerar um registo aqui,
  em vez de apenas sobrescrever o campo — mantendo o comportamento actual do nível como resultado, não como
  única fonte de verdade.
- Endpoint `POST /operacoes/agua/tanques/{id}/movimentos` para ajustes manuais (perda, evaporação, vazamento,
  transferência entre tanques).
- Frontend: aba "Movimentos" na página do tanque, com histórico permanente.

**Critério de aceitação:** registar uma perda de 50L por evaporação num tanque e confirmar que o nível desce
50L, que fica um registo permanente do tipo `evaporacao`, e que o histórico de movimentos do tanque lista tanto
este ajuste como as entradas/consumos anteriores.

---

## Fase 9 — Alertas de Água (âmbito específico, sem motor genérico)

- Expandir `operacoes_agua.py` para emitir os seguintes alertas (mesma abordagem simples usada hoje para
  ph/turbidez e para stock mínimo), consultáveis via `GET /operacoes/agua/alertas`:
  - Tanque abaixo do nível mínimo (`nivel_atual_litros < nivel_minimo_litros`).
  - Capacidade máxima atingida.
  - Consumo anormal (desvio do consumo diário face à média móvel dos últimos 30 dias, ex. > 2x).
  - Abastecimento pendente de documentação (estado ≠ `documentado`/`concluido` há mais de N dias).
  - Abastecimento acima do custo médio por litro (últimos 90 dias).
- Frontend: cartão de alertas na página de água, seguindo o padrão visual de `dashboard/estoque/alertas`.
- Documentar explicitamente como trabalho futuro (não implementar agora): motor de alertas genérico
  reutilizável por todos os módulos, e alertas que dependem de conceitos ainda não implementados nesta fase
  (fornecedor bloqueado — não existe estado de bloqueio de fornecedor hoje; fuga de água detectada por sensor
  — depende de hardware/IoT fora de escopo).

**Critério de aceitação:** baixar o nível de um tanque abaixo do mínimo e confirmar que o alerta aparece na
lista; gerar um abastecimento sem documentos há mais de N dias e confirmar que aparece o alerta de documentação
pendente.

---

## Fase 10 — Dashboards de Água

- Novo endpoint `GET /bi/dashboards/agua` com KPIs: água disponível (soma de todos os tanques activos), água
  consumida hoje/mês, custo total, custo médio por litro, custo por lavagem, % de reutilização (litros de
  tanques tipo `reciclada`/`tratada` sobre o total consumido), nº de abastecimentos no período, valor gasto em
  abastecimentos.
- Gráficos: consumo por hora/dia/semana/mês/ano (reaproveitar padrão de séries temporais do BI existente),
  evolução mensal de custos, consumo por box, consumo por serviço (tipo de lavagem).
- Rankings: fornecedores (quantidade fornecida, faturação, preço médio, frequência), filiais (consumo,
  eficiência — reaproveitando `lavagem_comparativo_filiais` como referência de desenho), equipas (consumo por
  lavagem, produtividade hídrica).
- Frontend: nova página `app/dashboard/operacoes/agua/dashboard/page.tsx` ou secção dedicada dentro de
  `dashboard/relatorios/executivo`, a decidir consoante o volume de conteúdo (seguir o padrão já estabelecido
  de estender a página executiva com novas secções por domínio).

**Critério de aceitação:** os KPIs de água no dashboard batem com a soma manual dos registos de
`ConsumoAguaModel`/`AbastecimentoAguaModel`/`MovimentoTanqueAguaModel` no mesmo período.

---

## Fase 11 — Custos consolidados

- Endpoint `GET /operacoes/agua/custos` com relatórios: custo por abastecimento, por fornecedor, por filial,
  por tanque, por serviço (tipo de lavagem), por mês, e evolução do preço médio da água ao longo do tempo.
- Reaproveitar `CentroCustoModel` para permitir imputação opcional de custos de água a centros de custo
  existentes (sem obrigar a criar um centro de custo novo por tanque/filial).

**Critério de aceitação:** o relatório de custo por filial bate com a soma de `custo_total` dos abastecimentos
e consumos daquela filial no período seleccionado.

---

## Fora de escopo deste ciclo (documentado, não implementar sem pedido explícito)

- Motor de alertas genérico (regra + notificação) reutilizável por todos os módulos.
- Lançamentos contabilísticos automáticos a partir do abastecimento (depende de um desenho de integração
  Contabilidade↔Compras que ainda não existe para nenhum módulo, não só Água).
- Criação automática de `ContaPagarModel` a partir do abastecimento (mesma razão acima).
- Fluxo de aprovação multi-etapa configurável dinamicamente (reutilizar por agora `AprovacaoFinanceiraModel`
  tal como está, sem generalizar o motor de aprovação).
- Estado de "fornecedor bloqueado" (não existe hoje no `FornecedorModel`).
- Detecção de fuga por sensor/IoT em tempo real (depende de hardware fora de escopo).

---

## Ordem de execução recomendada

```
Fase 1 (Tanques: filial + estado)
Fase 2 (Fornecedores: tipo_pessoa — reutilização quase total)
   ↓
Fase 3 (Abastecimento — núcleo genuinamente novo do módulo)
   ↓
Fase 4 (Anexos genéricos — pré-requisito para Fase 5)
   ↓
Fase 5 (Documentos de abastecimento)
Fase 6 (Histórico de abastecimentos)
   ↓
Fase 7 (Consumo por dimensão operacional — expande o que já existe)
Fase 8 (Movimentações tipadas do tanque)
   ↓
Fase 9 (Alertas específicos de água)
   ↓
Fase 10 (Dashboards)
Fase 11 (Custos consolidados)
```

Cada fase é autossuficiente para ser copiada como prompt isolado, seguindo o mesmo padrão de
`PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md`.
