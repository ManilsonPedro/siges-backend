-- ─────────────────────────────────────────────────────────────────────────
-- Migração ADITIVA: novas permissões de Produtos / Estoque / Caixa.
--
-- 100% segura e idempotente: usa INSERT ... ON CONFLICT DO NOTHING, por isso
-- NÃO apaga nem reescreve nenhuma permissão existente. Pode correr-se várias
-- vezes e em qualquer ambiente (dev/prod).
--
-- Como aplicar em PRODUÇÃO: cola este ficheiro no SQL Editor da Neon Console
-- (do branch de produção) e executa.
-- ─────────────────────────────────────────────────────────────────────────

-- 1) Inserir os códigos novos no catálogo de permissões
INSERT INTO permissoes (id, codigo, modulo, menu, acao, descricao) VALUES
  (gen_random_uuid(), 'produtos.listar',   'Cadastros', 'produtos', 'listar',     'Listar produtos'),
  (gen_random_uuid(), 'produtos.criar',    'Cadastros', 'produtos', 'criar',      'Criar produtos'),
  (gen_random_uuid(), 'produtos.editar',   'Cadastros', 'produtos', 'editar',     'Editar produtos'),
  (gen_random_uuid(), 'produtos.eliminar', 'Cadastros', 'produtos', 'eliminar',   'Eliminar produtos'),
  (gen_random_uuid(), 'estoque.ver',        'Estoque',  'estoque',  'ver',         'Ver estoque/armazéns'),
  (gen_random_uuid(), 'estoque.movimentar', 'Estoque',  'estoque',  'movimentar',  'Movimentar estoque (entradas/saídas)'),
  (gen_random_uuid(), 'caixa.ver',          'Caixa',    'caixa',    'ver',         'Ver caixa/vendas'),
  (gen_random_uuid(), 'caixa.vender',       'Caixa',    'caixa',    'vender',      'Registar vendas no caixa')
ON CONFLICT (codigo) DO NOTHING;

-- 2) Grupo Admin → conceder TODAS as permissões (aditivo; Admin deve ter tudo)
INSERT INTO grupo_permissoes (grupo_id, permissao_id)
SELECT g.id, p.id
FROM grupos g CROSS JOIN permissoes p
WHERE g.nome = 'Admin'
ON CONFLICT DO NOTHING;

-- 3) Grupo Gestor → conceder os códigos novos (aditivo)
INSERT INTO grupo_permissoes (grupo_id, permissao_id)
SELECT g.id, p.id
FROM grupos g
JOIN permissoes p ON p.codigo IN (
  'produtos.listar','produtos.criar','produtos.editar','produtos.eliminar',
  'estoque.ver','estoque.movimentar','caixa.ver','caixa.vender'
)
WHERE g.nome = 'Gestor'
ON CONFLICT DO NOTHING;

-- 4) Grupo Assistente → subconjunto (aditivo)
INSERT INTO grupo_permissoes (grupo_id, permissao_id)
SELECT g.id, p.id
FROM grupos g
JOIN permissoes p ON p.codigo IN (
  'produtos.listar','estoque.ver','caixa.ver','caixa.vender'
)
WHERE g.nome = 'Assistente'
ON CONFLICT DO NOTHING;
