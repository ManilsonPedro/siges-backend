# Migração do Bucket B2 — `financ-bi-jennos-aquasan` → `siges-storage`

O código já foi actualizado (`app/config.py` e `.env.production.example`) para usar
`siges-storage` como nome por omissão. Esta mudança **não quebra nada por si só** —
o `public_url()`/`presigned_url()` em `app/infrastructure/storage/__init__.py`
constrói a URL dinamicamente a partir de `settings.b2_bucket`, sem nenhum caminho
hardcoded.

O risco real é operacional, fora do código: se já existem ficheiros guardados no
bucket antigo em produção (logos de empresa, fotos de lavagem, comprovativos),
mudar só o nome do bucket sem mover o conteúdo faz esses ficheiros deixarem de
ser encontrados.

## Passos manuais (fazer no painel da Backblaze, não neste repositório)

1. **Confirmar se há ficheiros no bucket antigo.** Entrar em
   [backblaze.com](https://www.backblaze.com) → B2 Cloud Storage → Buckets →
   `financ-bi-jennos-aquasan` → Browse Files. Se estiver vazio, ir directo ao
   passo 4.

2. **Criar o bucket novo** `siges-storage` (mesma região `us-east-005`, mesmas
   definições de acesso — privado, já que o acesso é sempre via presigned URL).

3. **Copiar os ficheiros existentes** do bucket antigo para o novo. Opções:
   - Backblaze B2 CLI: `b2 sync b2://financ-bi-jennos-aquasan b2://siges-storage`
   - Ou rclone (`rclone copy b2remote:financ-bi-jennos-aquasan b2remote:siges-storage`)

4. **Actualizar a variável de ambiente em produção** (Render): `B2_BUCKET=siges-storage`.
   Antes deste passo, o backend em produção continua a apontar para o bucket
   antigo — nada muda até esta variável ser actualizada.

5. **Confirmar** que uploads/downloads novos funcionam (ex.: carregar um logo em
   Configurações > Empresa) e que anexos antigos (se existirem) ainda abrem.

6. **Só depois de confirmado**, apagar o bucket antigo `financ-bi-jennos-aquasan`
   (ou mantê-lo por mais uns dias como rede de segurança antes de apagar).

## Nada a fazer no ambiente de desenvolvimento local

Em dev, `STORAGE_TYPE` normalmente não é `b2` (usa `LocalStorageProvider`, disco
local `./uploads`), pelo que esta migração só é relevante para o ambiente de
produção no Render.
