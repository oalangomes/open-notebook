# Open Notebook: funcionalidades, transformacoes e formas de uso

Este documento resume, em portugues, as principais funcionalidades do Open Notebook com foco no uso pratico de chat, busca vetorial, transformacoes e organizacao do conhecimento.

## Visao geral

O Open Notebook e uma plataforma para organizar fontes de pesquisa, conversar com IA usando esse material como contexto, executar buscas textuais e semanticas, gerar insights a partir de transformacoes e consolidar tudo em notas reutilizaveis.

Na pratica, o fluxo principal e:

1. Adicionar fontes ao notebook.
2. Processar o conteudo e, quando necessario, gerar embeddings.
3. Explorar o material via busca, Ask, chat ou chat por fonte.
4. Criar insights e notas para consolidar o conhecimento.

## Estrutura funcional do sistema

### 1. Notebooks

Os notebooks sao o contenedor principal de trabalho. Eles agrupam:

- fontes
- notas
- sessoes de chat
- contexto selecionado para conversas

Cada notebook pode ter varias sessoes de chat, o que permite separar linhas de raciocinio por tema, tarefa ou experimento.

### 2. Fontes

As fontes sao a materia-prima do sistema. Hoje, o fluxo suporta principalmente:

- upload de arquivo
- URL/link
- texto colado manualmente

Depois de processada, a fonte passa a ter:

- `full_text` para leitura e uso em chat
- insights associados
- embeddings, quando gerados
- associacao com um ou mais notebooks

Na interface de detalhe da fonte tambem e possivel:

- visualizar o conteudo extraido
- baixar o arquivo original, quando existir
- gerar embeddings manualmente
- aplicar transformacoes para criar insights
- conversar diretamente com a fonte

### 3. Notes e Insights

O sistema distingue dois artefatos importantes:

- `insight`: saida gerada a partir de uma transformacao aplicada a uma fonte
- `note`: anotacao consolidada, editavel e reutilizavel no notebook

Fluxo recomendado:

1. aplicar transformacoes em uma fonte
2. revisar o insight gerado
3. salvar o insight como nota quando fizer sentido

As notas entram no contexto do chat de notebook e tambem podem participar da busca.

## Chat: formas de uso

O Open Notebook possui duas experiencias diferentes de conversa com IA.

### 1. Chat do notebook

Esse e o modo de conversa mais flexivel para trabalhar com varias fontes e notas ao mesmo tempo.

#### Como funciona

Antes de enviar a mensagem, o sistema monta um contexto a partir do notebook usando a selecao feita pelo usuario.

Para cada fonte, o contexto pode ficar em um destes modos:

- `insights`: envia apenas os insights da fonte
- `full`: envia o conteudo completo da fonte
- `off`: exclui a fonte do contexto

Para cada nota, o contexto pode ficar em:

- `full`: inclui a nota
- `off`: exclui a nota

O sistema calcula e exibe contagem estimada de caracteres e tokens antes do envio. Isso ajuda a controlar custo e tamanho de contexto.

#### Quando usar

Use o chat do notebook quando voce quiser:

- comparar varias fontes
- misturar fontes e notas
- iterar com perguntas de acompanhamento
- controlar manualmente o que a IA pode ver

#### Caracteristicas

- suporta multiplas sessoes por notebook
- permite trocar o modelo por sessao
- preserva historico da conversa
- nao depende de busca vetorial para responder
- funciona com contexto montado manualmente

Em outras palavras: o chat do notebook e o modo ideal para exploracao guiada pelo usuario.

### 2. Chat por fonte

Esse modo e voltado para uma unica fonte.

#### Como funciona

Ao conversar com uma fonte especifica, o sistema monta automaticamente um contexto com:

- a propria fonte
- os insights ja gerados para ela

Esse contexto e montado por um `ContextBuilder`, com limite de tokens, priorizacao e remocao de duplicidades. A resposta tambem pode trazer indicadores de contexto usados na ultima interacao.

#### Quando usar

Use o chat por fonte quando voce quiser:

- analisar um documento especifico
- revisar um video, artigo ou PDF isoladamente
- aproveitar os insights ja gerados daquela fonte
- manter uma conversa mais focada e menos dispersa

#### Diferenca pratica para o chat do notebook

- chat do notebook: contexto manual e multiplo
- chat por fonte: contexto automatico e focado em uma fonte

## Busca: textual, vetorial e Ask

O sistema expoe tres formas complementares de encontrar informacao.

### 1. Busca textual

E a busca baseada em termos exatos.

#### Quando usar

Use busca textual quando voce:

- sabe a palavra ou frase que procura
- quer localizar um termo tecnico especifico
- precisa encontrar um trecho literal

#### Comportamento

- mais direta
- mais previsivel para palavras exatas
- pode pesquisar em fontes e notas

### 2. Busca vetorial

E a busca semantica do sistema.

#### Como funciona

O texto da consulta e convertido em embedding e comparado com embeddings previamente gerados para o conteudo armazenado. Isso permite recuperar trechos semanticamente parecidos, mesmo quando as palavras nao sao identicas.

#### Quando usar

Use busca vetorial quando voce:

- quer encontrar conteudo por conceito
- nao sabe exatamente quais termos foram usados
- quer descobrir materiais relacionados semanticamente

#### Requisitos importantes

Para a busca vetorial funcionar, a instancia precisa ter:

- um modelo de embedding configurado
- embeddings gerados para as fontes e/ou notas desejadas

Sem isso, a busca vetorial e o modo Ask nao funcionam corretamente.

#### Exemplo de uso

Em vez de buscar por uma frase exata como:

`mecanismo de interpretabilidade`

voce pode buscar algo como:

`como o modelo explica suas decisoes`

e recuperar resultados conceitualmente proximos.

### 3. Ask

O modo `Ask` nao e apenas uma busca. Ele e um fluxo de busca e sintese.

#### Como funciona

O pipeline atual faz o seguinte:

1. recebe uma pergunta ampla
2. usa um modelo para montar uma estrategia com ate cinco buscas
3. executa buscas vetoriais para cada subconsulta
4. usa um segundo modelo para responder cada parte
5. usa um terceiro modelo para consolidar a resposta final

Na interface, a resposta pode ser acompanhada em streaming, mostrando:

- estrategia
- respostas intermediarias
- resposta final

#### Quando usar

Use Ask quando voce quiser:

- responder uma pergunta ampla
- sintetizar varias evidencias
- comparar abordagens
- obter uma resposta mais estruturada do que uma simples lista de resultados

#### Diferenca para busca comum

- busca textual/vetorial: retorna resultados
- Ask: busca, interpreta e sintetiza

## Transformacoes

Transformacoes sao templates reutilizaveis de prompt.

Cada transformacao possui:

- `name`
- `title`
- `description`
- `prompt`
- opcao `apply_default`

### O que elas fazem

Elas permitem padronizar extracoes e analises, por exemplo:

- resumo executivo
- pontos principais
- metodologia
- perguntas abertas
- takeaways

### Formas atuais de uso

Hoje, na implementacao atual, as transformacoes aparecem em dois fluxos principais.

#### 1. Playground de transformacoes

Na pagina de transformacoes existe um playground onde o usuario:

1. escolhe a transformacao
2. escolhe o modelo
3. cola um texto manualmente
4. executa o prompt
5. visualiza a saida em Markdown

Esse fluxo e ideal para:

- testar prompts
- ajustar formato de saida
- validar instrucoes antes de usar em fontes reais

#### 2. Geracao de insight em uma fonte

Na tela de detalhe da fonte, o usuario pode:

1. selecionar uma transformacao
2. solicitar a execucao
3. disparar um job assincrono
4. receber um novo insight associado a fonte

Esse insight pode depois ser salvo como nota.

### Como entender o papel das transformacoes

Transformacao nao e conversa.
Transformacao nao e busca.
Transformacao e processamento padronizado.

Use transformacoes quando voce quiser responder sempre ao mesmo tipo de pergunta sobre diferentes fontes.

### Prompt padrao global

O sistema tambem possui um prompt padrao global para transformacoes. Ele pode servir como uma camada adicional de instrucao aplicada ao comportamento geral desse tipo de execucao.

## Embeddings: o que sao e por que importam

Embeddings sao representacoes numericas do conteudo usadas para busca semantica.

No Open Notebook, eles aparecem em tres frentes:

- embeddings de fontes
- embeddings de notas
- embeddings de insights

### O que dependem deles

- busca vetorial
- Ask
- parte da recuperacao semantica do conhecimento

### Observacao importante

Nem todo fluxo depende de embedding.

Por exemplo:

- chat do notebook pode funcionar apenas com contexto montado manualmente
- chat por fonte pode usar a fonte e os insights diretamente

Ou seja, embedding e essencial para busca semantica, mas nao para todo uso de IA dentro da plataforma.

## Quando usar cada recurso

| Objetivo | Melhor recurso |
|---|---|
| Conversar sobre varias fontes e notas com controle manual de contexto | Chat do notebook |
| Analisar profundamente uma unica fonte | Chat por fonte |
| Encontrar termo exato ou frase literal | Busca textual |
| Encontrar conteudo por similaridade de significado | Busca vetorial |
| Fazer uma pergunta ampla e receber sintese automatica | Ask |
| Aplicar a mesma extracao/estrutura de resposta repetidamente | Transformacoes |
| Consolidar conhecimento editavel e reaproveitavel | Notes |

## Exemplos de fluxos praticos

### Fluxo 1: estudo de uma fonte

1. adicionar a fonte
2. processar e gerar embedding se necessario
3. abrir chat por fonte
4. aplicar uma transformacao para gerar insight
5. salvar o insight como nota

### Fluxo 2: comparacao entre materiais

1. adicionar varias fontes ao notebook
2. selecionar no chat quais entram como `full` e quais entram como `insights`
3. conversar no chat do notebook
4. usar Ask para uma sintese mais ampla
5. salvar o resultado em notas

### Fluxo 3: descoberta semantica

1. garantir modelo de embedding configurado
2. gerar embeddings das fontes
3. usar busca vetorial com perguntas conceituais
4. abrir os resultados mais relevantes
5. aprofundar com chat

## Diferenca resumida entre chat, busca vetorial e transformacoes

### Chat

- exploratorio
- iterativo
- conversacional
- orientado a contexto selecionado

### Busca vetorial

- orientada a recuperacao semantica
- ideal para descoberta
- depende de embeddings

### Transformacoes

- orientadas a padronizacao
- ideais para extracao estruturada
- produzem insights reutilizaveis

## Observacoes finais

- O modo `Ask` usa busca vetorial no pipeline atual.
- O chat do notebook trabalha com contexto montado explicitamente, nao com busca automatica.
- O chat por fonte aproveita a propria fonte e seus insights para manter foco.
- Transformacoes, no estado atual, sao mais bem entendidas como templates reutilizaveis para teste em playground e para geracao de insights por fonte.

## Resumo executivo

Se precisar resumir o funcionamento do sistema em uma frase:

> O Open Notebook organiza fontes, permite conversar com elas, buscar por significado, sintetizar respostas amplas e transformar conteudo em conhecimento estruturado por meio de insights e notas.
