# Próxima Fase: Leitura de Código via Repositório Git

## Resumo
Expandir o fluxo atual de `git-sync` para suportar ingestão de arquivos do repositório com foco em Q&A técnico e documentação. A v1 continuará reaproveitando o pipeline de `Source`, mas deixará de ser markdown-only: além de Markdown, também poderá ingerir arquivos `PUML` e `SVG` quando forem explicitamente incluídos ou descobertos a partir de `README`/arquivos índice, seguindo links internos do próprio repo. O suporte deve valer para os dois providers já existentes, `azure_devops` e `github`.

## Mudanças de Implementação
- Backend de sync Git:
  - Tornar o `git-sync` multimodal com `content_kind: "docs" | "code"`, default `"docs"` para compatibilidade.
  - Manter o modo atual por `paths` explícitos para docs.
  - Adicionar modo de descoberta para código com `roots`, `include_patterns`, `exclude_patterns` e `allowed_extensions`.
  - Adicionar modo opcional de descoberta guiada por documentação com `seed_paths`, permitindo usar `README.md`, `docs/index.md` e arquivos equivalentes como ponto de partida.
  - Na descoberta guiada, baixar os arquivos-semente, extrair links Markdown relativos para arquivos do mesmo repo, resolver caminhos e seguir recursivamente os links internos encontrados.
  - Permitir que a descoberta adicione automaticamente arquivos `.md`, `.puml` e `.svg` quando forem referenciados pelos Markdown percorridos.
  - Seguir recursivamente apenas arquivos Markdown; `PUML` e `SVG` entram como arquivos-folha, sem expandir novos links.
  - Permitir seguir também links encontrados em arquivos descobertos, com proteção contra ciclos e duplicação.
  - Para descoberta recursiva, usar APIs de listagem do provider, não endpoints RAW.
  - Continuar usando RAW/API de conteúdo apenas na etapa de fetch do arquivo final.
  - Manter um `Source` por arquivo do repo.
- Modelo e persistência:
  - Estender `GitSync` para guardar `content_kind`, `roots`, `include_patterns`, `exclude_patterns`, `allowed_extensions`, `seed_paths`, `max_discovery_depth` e `max_discovery_files`.
  - Preservar `paths` para o fluxo legado de docs.
  - No `Source`, sempre preencher `asset.url`, `asset.file_path` e `title`.
  - Estender embeddings de source para guardar `file_path`, `language`, `start_line`, `end_line` e `chunk_kind`.
  - Não introduzir AST, grafo de símbolos ou navegação semântica completa nesta fase.
- Chunking e processamento:
  - Introduzir detecção explícita de `CODE`, separada de `PLAIN`.
  - Adicionar detecção de linguagem por extensão.
  - Usar chunking por linguagem quando houver suporte do splitter; fallback para o splitter recursivo atual.
  - Calcular e persistir faixa de linhas por chunk.
  - Tratar `PUML` como texto simples, preservando o conteúdo fonte.
  - Tratar `SVG` como texto quando for SVG textual válido, preservando o XML bruto como conteúdo fonte.
  - Allowlist padrão da v1: `.md`, `.puml`, `.svg`, `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.java`, `.go`, `.rs`, `.sql`, `.json`, `.yml`, `.yaml`.
  - Na descoberta via `README`/índice, seguir apenas links internos relativos que resolvam para arquivos elegíveis dentro do mesmo repo/branch.
  - Ignorar links externos, anchors, assets binários e caminhos fora da allowlist.
- API e frontend:
  - Estender `GitSyncCreateRequest` e `GitSyncUpdateRequest` com `content_kind`, `roots`, `include_patterns`, `exclude_patterns`, `allowed_extensions`, `seed_paths`, `max_discovery_depth` e `max_discovery_files`.
  - `content_kind="docs"` continua aceitando `paths`.
  - `content_kind="code"` usa descoberta por `roots`; `paths` deixa de ser obrigatório nesse modo.
  - `seed_paths` pode ser usado tanto em `docs` quanto em `code` para expandir automaticamente os arquivos a partir de `README`/índices.
  - No front, manter o mesmo wizard Git e adicionar uma escolha entre `Docs` e `Code`.
  - Para `Code`, o formulário deve pedir provider, repo, branch, pasta(s) raiz, padrões include/exclude, arquivos-semente opcionais e credencial quando exigida.
  - O submit continua criando um `git-sync` e executando `run` automaticamente.

## APIs e Interfaces Públicas
- `GitSyncCreateRequest` / `GitSyncUpdateRequest`: novos campos `content_kind`, `roots`, `include_patterns`, `exclude_patterns`, `allowed_extensions`, `seed_paths`, `max_discovery_depth`, `max_discovery_files`.
- `GitSyncResponse`: refletir esses campos novos.
- `GitSyncFileStateResponse`: incluir opcionalmente `language`.
- Busca/resultados: quando um resultado vier de chunk de código, expor `file_path`, `language` e `start_line/end_line` se disponíveis.
- Compatibilidade: syncs existentes de markdown continuam funcionando sem migração manual de payload no cliente atual.

## Testes
- Backend:
  - criar sync `code` com descoberta recursiva por pasta
  - filtrar corretamente por `include_patterns`, `exclude_patterns` e allowlist
  - expandir arquivos a partir de `README.md`/índices usando `seed_paths`
  - seguir links internos recursivamente até o limite configurado
  - evitar ciclos e deduplicar arquivos descobertos
  - descobrir e ingerir `.puml` e `.svg` quando referenciados pelos Markdown
  - ignorar links externos, anchors e arquivos fora da allowlist
  - manter sync legado `docs` por `paths` explícitos sem regressão
  - criar `Source` com `asset.url` e `asset.file_path` corretos
  - detectar linguagem por extensão e aplicar chunking de código
  - preservar conteúdo textual de `.puml` e `.svg`
  - persistir `start_line/end_line` e `language` nos embeddings
  - reprocessar apenas arquivos alterados por hash
  - tratar `401/403/404` sem corromper estado anterior
  - validar ambos providers: `github` e `azure_devops`
- Frontend:
  - wizard Git alterna entre `Docs` e `Code`
  - modo `Code` exige `roots` e não exige `paths`
  - filtros include/exclude são enviados corretamente
  - `seed_paths` e limites de descoberta são enviados corretamente
  - criação e execução do sync continuam funcionando para GitHub e Azure DevOps
- Regressão:
  - build do frontend
  - testes existentes de `git-sync`
  - testes de chunking atualizados para `CODE`

## Assumptions e Defaults
- Objetivo da v1: Q&A sobre código, não análise estrutural profunda.
- Seleção de arquivos na v1: descoberta por pasta com `include/exclude`.
- Descoberta por documentação na v1: opcional via `seed_paths`, seguindo links internos do mesmo repo.
- Inteligência da v1: chunking por arquivo/linguagem + metadados de linha; sem AST e sem extração de símbolos.
- Providers suportados: `github` e `azure_devops`, reaproveitando a autenticação já implementada.
- Modelo de ingestão: um `Source` por arquivo.
- `PUML` e `SVG` entram quando forem explicitamente incluídos ou referenciados pelos arquivos Markdown descobertos.
- `PUML` e `SVG` não expandem novos arquivos nesta v1; apenas são ingeridos.
- Extensões padrão suportadas: `.md`, `.puml`, `.svg`, `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.java`, `.go`, `.rs`, `.sql`, `.json`, `.yml`, `.yaml`.
- Defaults de descoberta guiada: `max_discovery_depth=2` e `max_discovery_files=200`.
