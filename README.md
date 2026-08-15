# Monitor de Preços

Monitora o preço de produtos em lojas de e-commerce brasileiras. Você cadastra o
produto com preço-alvo, tolerância e as URLs onde ele é vendido. Um coletor
agendado extrai o preço do bloco `application/ld+json` das páginas, grava a série
histórica e avisa no Telegram quando o preço entra na faixa aceitável.

Além do acompanhamento por URL, existe um **catálogo de descoberta**: o coletor
varre páginas de listagem das lojas verificadas (14 categorias hoje) e monta uma
vitrine para achar o que cadastrar — o preço-alvo é a única informação que a
vitrine não tem.

A interface é o app Vue em [frontend/](frontend/) (visual "Radar"), publicada em
https://report-price.web.app.

**Custo: R$ 0,00.** Nenhuma peça exige cartão de crédito.

Outros documentos: [frontend/README.md](frontend/README.md) (decisões do front),
[PROPOSTA.md](PROPOSTA.md) (briefing do produto para redesenho de layout).

---

## Estado atual

| Fase | Entrega | Situação |
|---|---|---|
| 0 | rules, índices, projeto Firebase | ✅ publicado e verificado no servidor |
| 1 | `coletor/parser.py` | ✅ tabela 7.5 + 4 fixtures reais |
| 2 | `coletor/repositorio.py` | ✅ 28 testes contra o emulador |
| 3 | `coletor/coleta.py` | ✅ 24 testes com `respx` |
| 4 | `coletor/alertas.py`, `notificador.py` | ✅ 31 testes, sem rede |
| 5 | `coletor/main.py`, workflow do Actions | ✅ em produção; 1 execução bem-sucedida registrada |
| 6 | front sem build (`publico/`) | ✅ substituído pelo Vue e removido |
| — | security rules | ✅ 24 testes contra o emulador (`tests/test_rules.py`) |
| — | raspagem de catálogo (`coletor/raspagem.py`) | ✅ 14 categorias (KaBuM via JSON-LD, Terabyte via seletores DOM); vitrine acumulativa |
| — | front Vue "Radar" (`frontend/`) | ✅ build ok; **pendente de verificação visual e deploy** |
| — | lista fechada + Amazon por DOM (`coletor/lojas.py`) | ✅ 38 testes contra capturas reais; **Amazon nunca rodou do runner** |
| — | captura por fora / n8n (`coletor/captura.py`, `n8n/`) | ✅ 25 testes + volta completa verificada; **nenhuma loja ligada nesse caminho ainda** |

```
262 passed, 87 skipped        # sem o emulador do Firestore
319 passed, 1 skipped         # com o emulador rodando
234 passed, 86 skipped        # num clone SEM as capturas de página (ver abaixo)
```

O ciclo foi validado ponta a ponta contra o emulador, usando uma URL real de
loja: fonte pendente → coleta HTTP → parser → buckets no Firestore → máquina de
estados → mensagem formatada. A janela de coleta bloqueia execução fora de hora e o
cooldown de 24h cala a renotificação, ambos verificados.

O portão da §13 (execução real via `workflow_dispatch`) já foi cruzado — a
tabela acima registra a execução em produção. O pendente de agora é outro:
verificar o front Vue no navegador e fazer o primeiro deploy dele (ver
[O que falta](#o-que-falta)).

---

## Arquitetura

```
┌─────────────────┐   Auth + leitura direta   ┌──────────────────┐
│  Front (Vue 3)  │◄─────────────────────────►│    Firestore     │
│ Firebase Hosting│      (security rules)     │     (Spark)      │
└─────────────────┘                           └────────▲─────────┘
                                                       │ Admin SDK
                                              ┌────────┴─────────┐
                                              │ GitHub Actions   │
                                              │ cron */15min     │
                                              │  → coleta (URLs) │
                                              │  → raspagem      │
                                              │    (catálogo)    │
                                              │  → Telegram      │
                                              └──────────────────┘
```

Não existe servidor de API. O front autentica no Firebase Auth e lê o Firestore
direto, contido pelas security rules. O coletor roda no GitHub Actions com o
Admin SDK, que ignora as rules.

O front é buildado (Vue + Vite) mas continua **estático**: o `predeploy` em
`firebase.json` gera `frontend/dist` e o Hosting serve arquivos, como sempre.

Dois processos no mesmo ciclo do Actions, com cadências próprias:

| Processo | Cadência | Propósito |
|---|---|---|
| **coleta** | 3 h | preço real, histórico e alerta das fontes que você segue |
| **raspagem** | 24 h | descobrir o que existe nas listagens e montar a vitrine |

A separação é factual, não organizacional: o preço da LISTAGEM é o de tabela
(medido de 10% a 31% acima do preço da página do produto), então ele alimenta só
a vitrine — nunca o histórico, nunca o alerta.

```
monitor-precos/
├── coletor/      coleta, raspagem, parser, alertas, notificador (Python)
│   ├── lojas.py    registro das lojas: domínio, estratégia, busca, cabeçalhos
│   ├── captura.py  HTML entregue por fora (n8n) — codec e validade
│   ├── capturar.py utilitário para subir uma captura à mão
│   └── templates/  capturas das páginas de produto — FORA DO GIT, ver .gitignore
├── n8n/          workflow de captura, pronto para importar
├── frontend/     app Vue "Radar" — o front publicado
├── tests/        pytest; fixtures congeladas de páginas reais
└── firestore.rules / firestore.indexes.json / firebase.json
```

### Por que cada peça é gratuita

| Peça | Limite gratuito | Uso previsto |
|---|---|---|
| Firestore leituras | 50.000/dia | ~100/dia |
| Firestore escritas | 20.000/dia | ~100/dia |
| Firestore armazenamento | 1 GB | ~1 MB/ano |
| Firebase Auth | ilimitado | 1 usuário |
| Firebase Hosting | 10 GB / 360 MB por dia | ~250 KB |
| GitHub Actions | ilimitado em repo **público** | ~1.100 min/mês |
| Telegram Bot API | sem limite prático | ~10 msgs/mês |

Cloud Functions está fora: no plano Spark a saída de rede só é permitida para
serviços Google, e a coleta é por definição saída para fora.

**O repositório precisa ser público.** Em repositório privado o limite é 2.000
min/mês e o cron de 15 em 15 minutos consome mais que isso.

---

## Lojas suportadas

**Lista fechada de quatro.** O cadastro não aceita mais loja de texto livre: a
opção "Outra loja" deixava o usuário gravar uma URL que o coletor não sabe ler, e
o desfecho era uma fonte que falhava cinco vezes e morria. Recusar na entrada é
mais honesto que aceitar e desistir depois.

A tabela vive em [coletor/lojas.py](coletor/lojas.py), espelhada em
[frontend/src/lojas.js](frontend/src/lojas.js). O front recusa antes de gravar; o
coletor recusa depois de buscar. As duas checagens existem porque as security
rules não sabem validar domínio.

| Loja | Estratégia | Ciclo real em 2026-08-12 |
|---|---|---|
| KaBuM | JSON-LD | ✅ R$ 4.999,99 |
| Terabyte Shop | JSON-LD | ✅ R$ 4.799,99 |
| Pichau | JSON-LD | ⚠️ aprovou a R$ 5.529,40 e deu `http_403` na coleta 60s depois |
| Amazon | **seletores de DOM** | ✅ R$ 5.830,53, origem `d` |

As quatro foram validadas e coletadas contra produção, do coletor de verdade —
não por `curl`. **A Amazon acertou um produto DIFERENTE da captura** (ASRock RX
9070, contra a ASUS RTX 5070 Ti do template), o que é a prova que interessa: os
seletores não estão viciados em uma página só.

### O número que o sistema persegue é o PREÇO À VISTA

Medido no mesmo produto (ASRock RX 9070 XT) nas quatro lojas:

| Loja | O que lemos | É o à vista? |
|---|---|---|
| KaBuM | 5.199,99 (JSON-LD) | ✅ a página diz "À vista no PIX com 15% de desconto" |
| Terabyte | 4.599,90 (JSON-LD) | ✅ "à vista com 15% de desconto no pix" |
| Pichau | ~~5.529,40~~ → **4.699,99** | ⚠️ precisou de ajuste, ver abaixo |
| Amazon | 5.830,53 (DOM) | ❌ há "5% off à vista no Pix", mas só como badge |

Duas de três já entregavam o preço com desconto no JSON-LD, então essa é a régua:
**é o que se paga de fato**.

**A Pichau é a exceção.** O `Offer.price` dela traz o `final_price` (parcelado) e
o à vista mora só no estado JSON embutido — não chega ao DOM renderizado, então
nenhum seletor de CSS o alcança. Daí `extrair_preco_do_estado` e
`PADRAO_AVISTA_PICHAU`, e a origem `e` no histórico.

A diferença não é cosmética. Com o gatilho deste repositório em **R$ 4.700,00**:
o à vista de R$ 4.699,99 **dispara alerta**; o parcelado de R$ 5.529,40 **não
dispara nunca**. Era um alerta sendo engolido em silêncio.

Por isso, se a chave `avista` sumir da página, a fonte **falha** com
`sem_preco_avista` em vez de cair para o preço do JSON-LD. Cair seria gravar um
número ~18% maior na série histórica, para sempre, sem ninguém notar.

**A Amazon fica ~5% acima da própria régua**, e isso é desvio conhecido e
limitado, não bug: a loja não publica o valor com desconto em lugar nenhum.
Consequência prática: numa disputa apertada, a Amazon parece até 5% mais cara do
que é.

### Três erros que NÃO condenam a fonte

`ERROS_DE_PARSE` é o conjunto que diz "a página é ilegível, insistir não muda
nada" — e quem cai nele é marcado inválido. Três casos ficam de fora de
propósito, porque em todos a URL está certa:

| Erro | O que é | Por que fica de fora |
|---|---|---|
| `http_403`, `timeout`, … | transporte | a loja bloqueou o IP; pode voltar |
| `pagina_de_bloqueio` | desafio anti-bot servido como página | a Amazon faz isso com **HTTP 200** e corpo grande; o Terabyte serve `Just a moment...` do Cloudflare |
| `sem_oferta_ativa` | produto existe, ninguém vendendo | é decisão do mercado, não defeito da URL |

A detecção de bloqueio roda em **todas** as estratégias, não só na de DOM — foi
um furo corrigido depois de notar que o Cloudflare do Terabyte chegaria como
`sem_jsonld`, que é erro de parse e condenaria a fonte em 5 ciclos.

O `sem_oferta_ativa` veio de um caso real: uma URL da Amazon respondeu 1,1 MB com
`#productTitle` presente, **zero bloco de preço** e o marcador
`#unqualifiedBuyBox`. Antes isso virava `sem_preco_no_dom` e a fonte era
condenada como se a URL estivesse errada.

As capturas ficam em `coletor/templates/`, e são fixture congelada pela mesma
regra de `tests/fixtures/`: teste vermelho ali é a notícia, não o problema.

### As capturas NÃO são versionadas

São 2,6 MB, e ficam fora do git por isso. **O custo é real:** num clone sem elas,
`tests/test_lojas.py` pula 9 testes e a suíte fica verde **sem ter verificado**
os seletores da Amazon nem o JSON-LD de Pichau e Terabyte. Uma loja pode mudar o
layout e nada avisa.

Quem for mexer em [coletor/lojas.py](coletor/lojas.py) precisa delas na máquina.
Para recriar, do navegador — não por `curl`, que a Pichau e o Terabyte recusam:

1. abra a página de produto da loja no navegador;
2. **Salvar como → Página da Web, somente HTML** (não "completa": imagens e CSS
   não interessam e multiplicam o tamanho);
3. salve como `coletor/templates/<loja>-produto-detalhes.html`, com `<loja>` em
   `amazon`, `pichau` ou `terabyte`.

Qualquer produto serve para Pichau e Terabyte — o teste confere o valor que
estiver no arquivo. Para a Amazon, os testes esperam os valores desta captura
(R$ 7.124,05 / R$ 8.299,00); trocando o produto, ajuste os números em
`tests/test_lojas.py` **depois** de confirmar que os seletores continuam certos.

### Por que a Amazon é diferente em duas coisas

**Não publica JSON-LD.** Zero blocos em 1,2 MB. Daí `extrair_preco_dom` e a
tabela `SELETORES_AMAZON`. O escopo `#corePrice_feature_div span.a-offscreen`
não é decoração: a página tem 22 `span.a-offscreen`, e o segundo é R$ 7.499,00 —
outro preço, de outro bloco. Sem o escopo, o coletor gravaria um número plausível
e errado, que é a pior espécie de bug porque não parece bug.

**Exige cabeçalhos de navegador.** Medido: com o User-Agent honesto ela responde
**HTTP 200 com 221 KB e nenhuma marcação de produto** — sem título, sem preço,
sem botão. Com UA de Chrome, 1,25 MB e tudo no lugar, idêntico à captura. Não
existe versão honesta da página para ler; a escolha real era buscar como
navegador ou não suportar a loja. Está registrado em `CABECALHOS_DE_NAVEGADOR`
como decisão, não descuido — é a única exceção ao User-Agent honesto do projeto.

Esse 200-sem-produto é o modo de falha perigoso, e por isso tem tratamento
próprio: `pagina_de_bloqueio` fica **fora** de `ERROS_DE_PARSE`. A página é
sintaticamente perfeita e não tem preço, então pareceria erro de parse — e o
parse condena a fonte depois de 5 ciclos. Classificada como transporte, a fonte
sobrevive até a loja voltar a responder.

### Lojas que NÃO funcionam

| Loja | Motivo (verificado) |
|---|---|
| Mercado Livre | shell de ~39 KB montado por JavaScript; e a API oficial retém `buy_box_winner` para apps sem permissão especial |
| Magazine Luiza / Magalu | HTTP 403 em **tudo**, inclusive na home, com qualquer User-Agent |
| Americanas | responde 200, mas monta tudo por JS: 0 preços no HTML |
| Submarino, Shoptime | mesma plataforma da Americanas |
| Carrefour | publica JSON-LD, mas **nunca foi confirmada a partir do datacenter**. Saiu da lista por isso, não por defeito |

### A Pichau é intermitente, e isso já apareceu

No mesmo ciclo, com 60 segundos de intervalo: a validação recebeu **200** e leu
R$ 5.529,40; a coleta seguinte recebeu **403**. Não é layout nem parser — é
anti-bot reagindo à segunda requisição.

O sistema tratou certo, e é para isso que a distinção existe: `http_403` é
**transporte**, então a fonte ficou `status=ok`, `falhas=1`, sem ser condenada.
Só cinco falhas seguidas a desligam. Se a Pichau seguir assim, ela vai oscilar
entre ler e falhar em vez de morrer — o que é o comportamento certo para uma
loja que às vezes responde.

> **Cuidado com medição por `curl`.** Sondando as mesmas URLs por `curl` momentos
> antes, Pichau e Terabyte devolveram 403 e o Terabyte veio com
> `Just a moment...` (Cloudflare). Pelo `httpx` do coletor, as duas responderam
> 200. Mesma máquina, mesmo User-Agent honesto. A diferença provável é impressão
> digital de TLS ou estado transitório do anti-bot — mas o que importa é a regra:
> **vale a medição do coletor de verdade, não a do `curl`.**
>
> E nada disso é veredito de produção. O coletor roda de IP de datacenter (Azure,
> via GitHub Actions), e loja com anti-bot trata datacenter e residencial de
> forma diferente. **Só a produção decide quais lojas funcionam.**

---

## HTML capturado por fora (n8n)

O coletor roda no GitHub Actions: **IP de datacenter e sem navegador**. Isso
derruba duas classes de loja — a que bloqueia datacenter (Pichau, Amazon com UA
honesto) e a que só monta a página com JavaScript (Mercado Livre, Shopee, ambas
medidas com **zero ocorrências de "R$"** no HTML entregue).

Um n8n com navegador, **rodando de rede residencial**, tem as duas coisas que
faltam. O caminho entre ele e o coletor é uma coleção do Firestore.

```
   n8n (navegador, IP residencial)          GitHub Actions (coletor)
   ────────────────────────────────         ────────────────────────
   busca a página                            lê paginas/{fonteId}
   gzip + base64            ──▶  Firestore  ──▶  descompacta
   grava paginas/{fonteId}      (caixa de        extrai com os MESMOS
                                 correio)         seletores de sempre
```

> **Isto só compensa se o n8n NÃO rodar em datacenter.** Em n8n Cloud você troca
> um IP da Azure por outro, e a Pichau continua recusando. O ganho é o IP
> residencial e o motor de render — não a ferramenta.

### O documento que o n8n precisa escrever

Coleção `paginas`, **id do documento = id da fonte** (veja com
`python -m coletor.capturar --listar`).

| Campo | Tipo | O quê |
|---|---|---|
| `url` | string | a URL buscada. Confere contra a fonte — se você editar a URL e o n8n ainda não tiver rebuscado, a captura antiga é recusada em vez de gravar o preço do produto errado |
| `html` | string | o HTML em **gzip + base64** |
| `codificacao` | string | `"gzip+base64"`, ou `"texto"` para HTML cru |
| `bytes` | number | tamanho do HTML original, para diagnóstico |
| `capturadoEm` | timestamp | **obrigatório** — sem ele a captura é tratada como vencida |

O id ser o da fonte significa que **cada captura sobrescreve a anterior**: são
~13 documentos para sempre, sem rotina de limpeza para falhar em silêncio.

Por que comprimido: documento do Firestore tem teto de **1 MiB** e a Amazon são
1,2 MB de HTML — não cabe cru. Medido nos cinco templates: Amazon 1.209 KB →
358 KB, Mercado Livre 977 → 365, Shopee 925 → 255, Pichau 402 → 83, Terabyte
298 → 53. Comprimido cabe tudo com folga.

`paginas` é coleção **raiz e sem regra** em `firestore.rules` — o catch-all nega
tudo, e é assim que tem de ficar. Só o Admin SDK lê e escreve.

### ⚠️ A armadilha nº 1: aspas escapadas

**Já aconteceu neste repositório**, em 2026-08-13, com uma captura do Terabyte.
O arquivo continha literalmente os caracteres `\"` e `\n` — 4.312 aspas, **todas
escapadas**. O HTML passou por `JSON.stringify` e foi salvo sem desescapar.

O sintoma engana: o arquivo abre, o tamanho parece certo, o conteúdo está todo
lá. Mas `type=\"application/ld+json\"` não é o mesmo atributo que
`type="application/ld+json"`, então **nada casa** e o parser reporta
`sem_jsonld` — apontando para a loja, não para o arquivo.

E **não dá para consertar depois**: o bloco `Product` tinha `\r\n` numa avaliação
de cliente, que virou `\\r\\n`; desfazer escape sobre escape é ambíguo. O
conserto é sempre a montante — no n8n, entregue o campo cru (`{{ $json.data }}`),
sem re-serializar.

O coletor detecta e recusa com `captura_escapada` em vez de fingir que a loja
mudou. Teste de 5 segundos no HTML salvo: **procure `\"`. Se achar, está
escapado.**

### O workflow pronto

[n8n/captura-de-paginas.json](n8n/captura-de-paginas.json) — importe no n8n
(Workflows → Import from File). Sete nós:

```
A cada 3 horas → Listar fontes ativas → Escolher o que capturar
                                                ↓
              Gravar em paginas/{id} ← Comprimir ← Buscar a página
                        └──────────── volta para a próxima fonte
```

`Listar fontes ativas` usa a **collection group query** do Firestore REST (as
fontes moram em `usuarios/{uid}/produtos/{id}/fontes`, então `allDescendants:
true`) com o mesmo filtro de `listar_fontes_ativas()`. Não há lista de URLs para
manter em lugar nenhum: o n8n descobre sozinho.

**Três coisas para configurar:**

| O quê | Onde |
|---|---|
| Credencial **Google Service Account API** | nos dois nós de HTTP que falam com o Firestore |
| `NODE_FUNCTION_ALLOW_BUILTIN=zlib` | variável de ambiente do n8n — sem ela o nó `Comprimir` falha com *Cannot find module 'zlib'* |
| `DOMINIOS_PARA_CAPTURAR` | dentro do nó `Escolher o que capturar`. **Começa vazia de propósito** |

#### A credencial: service account, NÃO OAuth2

No n8n existem duas credenciais de Firestore e elas levam a caminhos bem
diferentes. A de **OAuth2** (`Google Firebase Cloud Firestore OAuth2 API`) pede
Client ID e Client Secret, e exige montar tela de consentimento e client OAuth no
Google Cloud — trabalho à toa para máquina falando com máquina. **Não é essa.**

Use **`Google Service Account API`**:

1. Credentials → New → busque `Google Service Account API`
2. **Service Account Email** e **Private Key** (com as linhas
   `-----BEGIN/END PRIVATE KEY-----`), do JSON baixado do Google Cloud
3. Ligue **Set up for use in HTTP Request node**
4. Em **Scope(s)**: `https://www.googleapis.com/auth/datastore`

O passo 3 é o que costuma passar batido: sem ele a credencial não aparece para
escolher no nó de HTTP Request.

A conta de serviço deve ser **dedicada**, com o papel **Cloud Datastore User**
(`roles/datastore.user`) e nada mais. Dá para usar a do `FIREBASE_SA_BASE64`, mas
ela é a do Admin SDK — acesso total, incluindo apagar todo o histórico — para uma
tarefa que só precisa ler `fontes` e escrever `paginas`. Se a chave dedicada
vazar, você revoga só ela e o coletor continua de pé.

Essa última lista é a **única duplicação consciente** do desenho: ela precisa
bater com as lojas que têm `busca="capturada"` em `coletor/lojas.py`. Não há como
o n8n importar Python, e preferi um lugar só, comentado, a espalhar a decisão.

O que o workflow foi verificado fazendo, rodando o código dos nós em Node contra
as capturas reais:

| Template | Bruto | No documento |
|---|---|---|
| Amazon | 1.209 KB | 360 KB ✅ |
| Mercado Livre | 977 KB | 363 KB ✅ |
| Shopee | 925 KB | 254 KB ✅ |
| Pichau | 402 KB | 83 KB ✅ |
| Terabyte (a captura escapada) | — | ❌ recusada com a mensagem certa |

E a volta completa: saída do nó `Comprimir` → `captura.ler()` → `extrair_da_loja`
devolveu **R$ 4.699,99, origem `e`** para a Pichau — o mesmo valor do caminho
direto.

> **Por que HTTP Request e não navegador:** as quatro lojas do registro não
> precisam de JavaScript, precisam de um IP que não seja datacenter. Mercado
> Livre e Shopee precisariam de um nó de navegador (Puppeteer), mas nenhuma das
> duas está no registro — e não estão porque não dá para lê-las de jeito nenhum
> sem render.

Quatro testes amarram o JSON ao Python (`tests/test_captura.py`): os campos que o
nó escreve, o `responseFormat: text`, a cadência ser menor que a validade, e a
credencial ser a de service account e não a de OAuth2. Se
alguém renomear um campo de um lado, o teste quebra em vez de virar
`sem_captura` num n8n que está rodando perfeitamente.

#### O n8n avisa o Actions quando termina

Sem aviso, a captura fica esperando: o n8n grava em `paginas/` e o coletor só lê
no próximo ciclo, **até 30 minutos depois**. O nó final do workflow fecha essa
distância disparando a coleta na hora.

O nó **`Avisar o GitHub Actions`** faz `POST` em
`/repos/{owner}/{repo}/actions/workflows/coletor.yml/dispatches` com corpo
`{"ref":"main"}`. Sucesso é **204 sem corpo**.

Três decisões que valem entender:

- **Pende da saída `done` do loop, e tem `executeOnce`.** São duas coisas
  diferentes, e a segunda custou caro para aprender. A saída `done` garante que
  o nó é *alcançado* uma vez, depois da última fonte — a saída por item
  dispararia a coleta antes de as páginas existirem. Mas um nó de HTTP Request
  no n8n roda **uma vez por item de entrada**, e a `done` emite todos os itens
  acumulados do laço: um por fonte. Sem `executeOnce`, uma captura gerou **8
  disparos** (runs #113–#120 em 2026-08-15). O `concurrency: coletor` cancelou 6
  em 1–3s e dois rodaram — contenção, não conserto.
- **O corpo não manda `inputs`.** O input `forcar` é do tipo `boolean`, e mandar
  `"true"` (string) pela API do GitHub esbarra na validação de tipo. Omitir faz
  valer o `default: true` do workflow — que é exatamente o que se quer. Um teste
  amarra as duas pontas: se alguém trocar o default, ele quebra em vez de a
  coleta passar a esperar a janela em silêncio.
- **O token não entra no JSON.** O repositório é público. O PAT mora numa
  credencial **Header Auth** do n8n (`Name: Authorization`,
  `Value: Bearer <PAT>`), e um teste varre o JSON exportado atrás de `ghp_`,
  `github_pat_` e chaves privadas.

O PAT precisa ser **fine-grained**, restrito a este repositório, com a permissão
**Actions: Read and write**. Só isso. `404` na chamada quase sempre é permissão
faltando no token, não caminho errado — a API do GitHub esconde 403 como 404
quando o token não enxerga o recurso.

> **Cadência:** o gatilho do n8n é de 3 em 3 horas. Se você aumentar a frequência
> da captura, lembre que cada execução passa a disparar um ciclo de coleta —
> forçado, então **fora** da janela de 30 min, sem deslocar o agendamento
> automático (ver *Coletar os produtos agora*).

### Ligar uma loja no caminho capturado

Em [coletor/lojas.py](coletor/lojas.py), mude `busca` da loja para `"capturada"`.
O padrão é `"direta"` e **assim deve continuar para KaBuM e Terabyte**: elas
funcionam por HTTP simples há semanas: fazê-las depender de um n8n que pode estar
fora do ar seria trocar o que está de pé pelo que talvez funcione.

Para provar o caminho inteiro antes de montar o n8n, dá para subir uma captura
salva do navegador:

```bash
set -a; source .env; set +a
python -m coletor.capturar --listar
python -m coletor.capturar --fonte <fonteId> --arquivo pagina.html
```

### Cinco erros que não condenam a fonte

Uma captura ausente ou velha é falha do **mensageiro**, não da URL. Todos ficam
fora de `ERROS_DE_PARSE` — se entrassem, um n8n fora do ar por meio dia marcaria
todas as fontes como inválidas, e o usuário leria "URL não legível" para URLs
perfeitas.

| Erro | Quando |
|---|---|
| `sem_captura` | o n8n ainda não escreveu nada para esta fonte |
| `captura_vencida` | mais velha que `HORAS_DE_VALIDADE` (6 h), ou sem `capturadoEm` |
| `captura_de_outra_url` | a URL da fonte mudou e a captura é da antiga |
| `captura_ilegivel` | não é gzip+base64 válido |
| `captura_escapada` | ver a armadilha acima |

A validade é o que impede o pior modo de falha: **sem ela, o n8n parar
significaria o coletor reler a mesma página para sempre e gravar o mesmo preço
como se fosse leitura nova** — série histórica inventada, sem erro em log nenhum.

---

## Modelo de dados

Dinheiro é **sempre inteiro de centavos**, e todo campo monetário termina em
`Centavos`. R$ 1.299,90 → `129990`. A única divisão por 100 do projeto está em
`formatarBRL`, no front, e existe só para exibir.

```
usuarios/{uid}/produtos/{produtoId}
    nome, precoAlvoCentavos, toleranciaPct, precoGatilhoCentavos,
    estado ("ACIMA" | "EM_ALERTA"), ultimoAlertaEm,
    ultimoPrecoAlertadoCentavos, ativo, criadoEm
  └── fontes/{fonteId}
        loja, url, status ("pendente"|"ok"|"invalida"), motivoInvalida,
        falhasSeguidas, comErro, ultimoPrecoCentavos, ultimaColetaEm
  └── historico/{fonteId}_{AAAA-MM}     1 doc por fonte por MÊS
        leituras: [ {t, p, d, s, o, e?}, … ]
  └── diario/{fonteId}_{AAAA}           1 doc por fonte por ANO
        dias: { "d20260810": {min, max, soma, n, fech} }

sistema/controle                        GLOBAL (coleção raiz)
    ultimaColetaEm
sistema/controle_raspagem
    ultimaRaspagemEm

paginas/{fonteId}                       caixa de correio do n8n (raiz)
    url, html (gzip+base64), codificacao, bytes, capturadoEm

catalogo/{loja}                         GLOBAL — escrito só pelo coletor,
  └── indice/{categoria}                lido por qualquer usuário autenticado
        quantidade, atualizadoEm,
        itens: { sku: {n, u, p, t, d, img, vt} }   ← a categoria INTEIRA em 1 doc
  └── itens/{sku}                       documento por item (detalhe)
```

O índice do catálogo segue a mesma jogada do bucketing: **uma leitura serve a
categoria inteira**. `p` é o preço de vitrine (tabela), `t` o "de" riscado
quando a loja publica os dois, `vt` quando o item foi visto pela última vez. A
vitrine é **acumulativa**: a renderização das listagens é instável (a mesma
categoria já devolveu 47 itens numa requisição e 25 na seguinte), então um item
só sai depois de sumir por 7 dias seguidos — o sinal de que foi descontinuado.

> **Atenção aos dois campos homônimos.** `sistema/controle.ultimaColetaEm` é o
> **portão**: decide se o ciclo coleta. `fontes/{id}.ultimaColetaEm` é apenas
> informativo — é escrito a cada coleta e nunca lido para decidir nada.
> Intervalo atual: **3 horas** (`INTERVALO_COLETA_HORAS`).

Bucketing existe porque um documento por leitura faria o gráfico de 1 ano custar
365 leituras cobradas por abertura. Com buckets: 1 documento para `1d`, 1–2 para
`1s`/`1m`/`1a`.

Chaves curtas no array `leituras` porque o nome do campo é cobrado em
armazenamento **em cada entrada**: `t` instante, `p` preço em centavos (`null` na
falha), `d` disponível, `s` suspeito, `o` origem (`j` jsonld / `d` seletor de DOM
(Amazon) / `e` estado JSON embutido (Pichau, preço à vista) / `g` opengraph /
`m` microdata), `e` motivo do erro (só quando houve falha).

`soma` e `n` em vez de `media` para que a média seja recalculável de forma
incremental sem perder precisão. Chave do dia com prefixo `d` e sem hífen:
field path do Firestore com caractere especial exige escaping por crase, e isso
é fonte silenciosa de bug em update aninhado.

---

## Alertas

Há **dois gatilhos independentes**, e o efetivo é o maior dos dois — porque
`preço ≤ alvo OU preço ≤ limite_da_média` é `preço ≤ max(alvo, limite)`. Isso
também deixa a regra de rearme correta sem código extra.

| Gatilho | Condição | Quando existe |
|---|---|---|
| Preço-alvo | `preço ≤ alvo × (1 + tolerância%)` | sempre |
| Média histórica | `preço ≤ média × (1 − MARGEM_MEDIA_PCT%)` | a partir de 30 dias de histórico |

A margem no gatilho da média não é decoração: **"abaixo da média" sem margem
dispararia em cerca de metade das leituras**, porque preço oscila em torno da
própria média por definição. Default 10%.

A média histórica cobre todo o histórico, ponderada por amostra (`soma`/`n`
acumulados), nunca média de médias. É diferente da média de 30 dias, que aparece
na mensagem como referência de variação.

### O que limita a quantidade de mensagens

Existem **dois modos**, escolhidos por `ALERTA_REPETE_NO_RANGE` no workflow.

#### Modo repetição (padrão hoje: `true`)

Avisa a cada ciclo enquanto o preço estiver na faixa, **até 3 mensagens no mesmo
preço** (`LIMITE_DE_REPETICOES` em `coletor/alertas.py`). Da quarta em diante,
pausa.

| Situação | Ação |
|---|---|
| Preço entra na faixa | notifica, vai para `EM_ALERTA`, contador = 1 |
| Continua na faixa, mesmo preço, contador < 3 | notifica de novo |
| Continua na faixa, mesmo preço, contador = 3 | **pausa** (`repeticoes_esgotadas`) |
| Qualquer preço diferente, ainda na faixa | contador zera, libera outras 3 |
| Volta acima do gatilho | silêncio, rearma para `ACIMA`, contador zera |
| Indisponível ou leitura suspeita | silêncio, estado inalterado |

A pausa é **por preço, não por tempo**. Preço novo é informação nova; preço
repetido não é — a terceira mensagem já não diz nada que a primeira não tenha
dito. Sem esse freio, um produto parado por uma semana renderia ~340 mensagens
idênticas (ciclo de 30 min).

A constante é a única fonte do número: os testes a importam em vez de repetir o
literal, então ajustá-la move comportamento e asserções juntos.

Sair da faixa e voltar também zera: voltar a cair depois de subir é notícia.

#### Modo oferta única (`ALERTA_REPETE_NO_RANGE=false`)

| Situação | Ação |
|---|---|
| Preço cruza o gatilho pela primeira vez | notifica, vai para `EM_ALERTA` |
| Continua abaixo, sem cair mais 5% | silêncio |
| Cai mais 5% abaixo do último preço avisado | renotifica |
| Volta acima do gatilho | silêncio e rearma para `ACIMA` |

Mais cooldown de no máximo 1 mensagem por produto a cada 24h. Numa simulação de
84h com o preço abaixo do alvo a maior parte do tempo: **4 mensagens em 14
ciclos**.

> O cooldown **não** vale no modo repetição — se valesse, seguraria tudo por 24h
> e a repetição não existiria.

#### Envio que falha não conta como alerta

`notificador.enviar` devolve `False` quando o Telegram recusa, e `processar`
**não** marca o produto nesse caso. Marcar seria o pior desfecho possível: o
produto entraria em `EM_ALERTA` com `ultimoPrecoAlertado` preenchido e ficaria
calado — no modo oferta única, indefinidamente. O sistema acharia que avisou, e
o usuário nunca teria recebido nada. Sem marcar, o ciclo seguinte tenta de novo
em 30 minutos.

A mensagem muda de título conforme o gatilho. Dizer "Preço atingido" quando só a
média justificou o alerta seria falso, então nesse caso o título é
"📉 Abaixo da média histórica" e a referência exibida é a média, não o alvo.

## O que o front faz

O front publicado é o app Vue "Radar" ([frontend/](frontend/)), organizado em
duas abas — **Monitoramento** e **Catálogo** — com o cadastro em modal:

- **Login** com e-mail/senha e Google
- **Monitoramento**: busca por nome **ou loja** e paginação de 4 em 4; cartões
  com preço atual, **média de 30 dias** (a primeira
  vez que o número que dispara o alerta "abaixo da média" aparece em tela),
  menor preço do período e estado (`alerta de preço baixo` / `monitorando` /
  `aguardando primeira coleta` / `pausado`)
- **Análise detalhada** do produto selecionado: fontes com status e preço,
  flutuação em barras com **quatro períodos** (dia / 7 dias / mensal / anual) +
  tabela equivalente (acessibilidade)
- **Descoberta**: sugestões do catálogo ainda não acompanhadas
- **Catálogo**: vitrine completa com filtro por categoria, busca, ordenação e
  paginação; acompanhar um item pré-preenche o cadastro
- **Cadastrar/editar** produto com N pares loja/URL em modal. A loja vem de uma
  lista fechada de quatro e é preenchida sozinha ao colar a URL; loja
  incompatível é recusada com o motivo verificado
- **Pausar / retomar** coleta sem perder histórico
- **Excluir** produto, com cascata manual (ver abaixo)
- **Tentar de novo** numa fonte que falhou

> **Diferença deliberada para o front antigo:** o gráfico de LINHAS com uma série
> por fonte foi substituído por barras com o menor preço do período, seguindo o
> desenho "Radar". Os quatro períodos voltaram; o que não voltou foi a escala em
> variação % e a comparação multi-produto no mesmo eixo — ver "O que falta".

**As duas origens de dado do gráfico**, e a diferença importa:

| Período | Vem de | Um ponto é |
|---|---|---|
| **Dia** | `historico` bruto, últimas 24h | uma **leitura** (menor entre as fontes no minuto) |
| 7 dias / mensal / anual | rollup `diario` | o fechamento do **dia** |

O custo é o mesmo nos quatro, e é para isso que o bucketing existe: `diario` é 1
documento por fonte por **ano**, então o período anual custa as mesmas leituras
que o de 7 dias.

**A "Média 30 dias" NÃO muda com o período**, de propósito. Ela é a referência do
alerta "abaixo da média histórica" (`DIAS_DA_MEDIA` no coletor). Fazer o rótulo
seguir o gráfico deixaria a tela dizendo um número e o Telegram outro.

### Cascata é manual, e tem que ser

O Firestore **não apaga subcoleções** ao apagar o documento pai. Excluir um
produto sem limpar `fontes`, `historico` e `diario` deixaria esses documentos
órfãos, ocupando espaço para sempre. O front apaga tudo num `writeBatch`.

Isso exigiu permitir `delete` (não `create`/`update`) em `historico` e `diario`
nas rules. Poder apagar o próprio histórico não é poder forjá-lo, que é o que
importa proteger.

### Editar a URL preserva o histórico

Quando você troca a URL de uma fonte, ela volta para `pendente` e o histórico
**é mantido**. A razão: quase toda edição corrige um slug ou remove
`?utm_...` do mesmo produto, e descartar meses de série por isso seria pior.

O risco é real e a rede de proteção é a guarda de sanidade: se a nova URL for de
outro produto, a leitura discrepante entra como `suspeito`, fica fora do gráfico
e não dispara alerta. Para trocar de produto, prefira remover e cadastrar de novo.

## Setup

### 1. Projeto Firebase

1. [console.firebase.google.com](https://console.firebase.google.com) → novo projeto
2. **Firestore Database** → criar, modo produção, região `southamerica-east1`
3. **Authentication** → Sign-in method → habilitar **E-mail/senha** e **Google**
4. Configurações do projeto → **Contas de serviço** → Gerar nova chave privada

```bash
npm i -g firebase-tools
firebase login
firebase use <seu-project-id>
firebase deploy --only firestore:rules,firestore:indexes
firebase deploy --only hosting
```

A config **pública** do front fica em `frontend/src/firebase.js`. Isso não é
segredo: a `apiKey` identifica o projeto, não autoriza nada. A proteção real são
as rules. Não tente ofuscar.

### 2. Service account como secret

```bash
base64 -i chave-privada.json | tr -d '\n' | pbcopy
rm chave-privada.json          # não deixe no disco
```

Cole em `FIREBASE_SA_BASE64`. **Nunca** comite o `.json`, e nunca cole a chave em
chat, issue ou log — ela dá acesso administrativo total ao Firestore e o Admin
SDK ignora as security rules.

### 3. Bot do Telegram

```bash
# no Telegram: @BotFather → /newbot → guarda o token
# manda qualquer mensagem para o bot, depois:
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
# o chat.id está na resposta
```

Se o token vazar: `@BotFather → /revoke`. Gerar chave nova **não** invalida a
antiga — no Google Cloud é preciso apagar a chave velha em
IAM → contas de serviço → aba CHAVES.

### 4. Repositório e secrets

Repo **público** no GitHub → Settings (do repositório, não da conta) → Secrets
and variables → Actions:

| Secret | Conteúdo |
|---|---|
| `FIREBASE_SA_BASE64` | service account em base64 |
| `TELEGRAM_BOT_TOKEN` | token do @BotFather |
| `TELEGRAM_CHAT_ID` | id do chat |

---

## Desenvolvimento local

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.exemplo .env          # preencha; .env é ignorado pelo git
```

### Testes

```bash
# tudo menos o repositório (sem rede, sem emulador)
.venv/bin/python -m pytest -q

# repositório: precisa do emulador (Java + firebase-tools)
brew install openjdk
firebase emulators:start --only firestore --project demo-monitor
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 GCLOUD_PROJECT=demo-monitor \
  .venv/bin/python -m pytest tests/test_repositorio.py -q
```

Nenhum teste toca a rede nem o Firestore de produção. O emulador roda com project
id `demo-monitor` e é apagado antes de cada teste.

> **`88 skipped` não é ruído — é a camada do Firestore sem cobertura.** Sem Java,
> os testes do emulador pulam e o pytest ainda sai verde. Foi assim que um
> `NameError` chegou em produção em 2026-08-14 (ver *Lição aprendida em
> produção*).
>
> A rede é `tests/test_sanidade_estatica.py`: roda pyflakes em `coletor/` e
> `tests/` sem precisar de emulador, de Java nem de rede, e pega **nome
> indefinido**, que era exatamente aquele bug. O workflow
> [`testes.yml`](.github/workflows/testes.yml) roda isso e a suíte a cada push.
>
> O que **nada disso** pega: erro que só aparece falando com o Firestore —
> índice ausente, transação malformada, campo com nome trocado na gravação. O
> CI é enxuto por opção e não sobe o emulador, então esses continuam só nos 88
> testes pulados. **Rode o emulador na mão antes de mexer em `repositorio.py`**
> (`brew install openjdk` e o comando acima). Verde no CI significa "não quebrei
> o que dá para checar barato", não "está testado".

### Fixtures

`tests/fixtures/` contém 4 páginas de produto capturadas de lojas reais em
2026-08-10, e o `esperado.json` com preço e disponibilidade lidos do JSON-LD cru
de cada uma. São fotografias de um instante: se uma loja mudar o markup, a
fixture continua válida como caso de teste — **não recapture para "consertar" um
teste vermelho** sem antes entender o que mudou.

### Front

O front atual é o app Vue em [frontend/](frontend/) — visual "Radar", build com
Vite. Ver [frontend/README.md](frontend/README.md) para decisões e estrutura.

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

O deploy continua `firebase deploy --only hosting`: o `predeploy` em
`firebase.json` instala e builda sozinho.

> Evite a porta 8080 para qualquer servidor local: é a porta do emulador do
> Firestore, e um servidor de arquivos parado ali já travou a suíte de testes uma
> vez (o probe dos testes hoje distingue os dois, mas não há motivo para conviver
> com a colisão).

---

## Operação

**O GitHub desabilita workflows agendados após um período de inatividade no
repositório.** Dispare o `workflow_dispatch` manualmente ao menos uma vez por
mês, ou faça um commit. O GitHub avisa por e-mail antes de desabilitar — não
ignore esse e-mail.

O cron roda de 15 em 15 minutos, mas a coleta pesada só acontece quando
`sistema/controle.ultimaColetaEm` indica que o intervalo real passou. O GitHub
atrasa e **pula** execuções sob carga; a cadência efetiva é "pelo menos a cada
3h", não "exatamente às 00h, 03h, 06h…". Nunca calcule o tempo decorrido a
partir do horário agendado.

### Coletar os produtos agora (conferência manual)

Actions → **coletor** → *Run workflow*, com **Forçar** marcado (é o padrão).
Ignora a janela de 30 minutos e lê o preço de todas as fontes ativas na hora.

Três coisas que esse modo **não** faz, de propósito:

- **Não mexe no relógio de cadência.** Forçar fora da janela não grava
  `sistema/controle`. Se gravasse, uma conferência às 12h05 empurraria a coleta
  automática de 12h30 para 12h35 — um teste manual deslocaria o agendamento de
  produção. Forçar *dentro* da janela grava normal: ali a coleta ia acontecer de
  qualquer jeito, e não gravar faria a próxima rodar em 15 min, o dobro da
  cadência combinada.
- **Não força a raspagem do catálogo.** Ela tem portão próprio de 24h e varre
  dezenas de páginas de listagem; a composição da vitrine muda em dias, não em
  minutos. Só os produtos acompanhados são lidos.
- **Não silencia os alertas.** Preço lido numa execução forçada é preço real: se
  bater o valor máximo, o Telegram dispara (respeitando o cooldown de 24h). Para
  conferir sem risco de mensagem, o caminho é o cooldown, não o modo forçado.

O portão está em `executar_ciclo` e é coberto por `tests/test_ciclo.py`.

---

## Decisões tomadas por ambiguidade da spec

| # | Decisão | Alternativa descartada |
|---|---|---|
| 1 | **Teto prevalece** sobre a linha `"1.234.567,89"` da tabela 7.5 | elevar `TETO_CENTAVOS` |
| 2 | Sinal negativo detectado **antes** do passo 2 da normalização | seguir o passo 2 ao pé da letra |
| 3 | `priceCurrency` ausente → assume BRL | falhar com `moeda_nao_suportada` |
| 4 | `moeda_nao_suportada` **não** cai para o fallback | tentar Open Graph em moeda estrangeira |
| 5 | `offers` inexistente → `sem_offers`; preço ilegível → `preco_invalido` | usar `sem_offers` para os dois |
| 6 | `@type` comparado em caixa baixa | comparação sensível a caixa |
| 7 | Cooldown cala a mensagem mas **avança o estado**; `ultimoPrecoAlertado` intacto | não avançar o estado |
| 8 | Variação vs. média trunca em direção ao zero | `//`, que exagera o desconto |
| 9 | `sistema/controle` **global**, em coleção raiz | por usuário |
| 10 | Chave `e` no histórico para o motivo da falha | não gravar o motivo |
| 11 | Sucesso na coleta não gera escrita extra na fonte | 4 escritas por coleta |
| 12 | Front grava `precoGatilhoCentavos = precoAlvoCentavos`; coletor corrige | duplicar `calcular_gatilho` em JS |
| 13 | Sem teto no preço-alvo digitado pelo usuário | aplicar `TETO_CENTAVOS` também ali |
| 14 | `coleta.py` recebe o repositório por injeção (`Protocol`) | importar `repositorio` direto |
| 15 | `.gitignore` criado (fora da lista de arquivos da spec) | confiar em não rodar `git add .` |
| 16 | Erro de **transporte** (403, timeout, rede) mantém a fonte pendente e retenta até 5×; só erro de **parse** condena de imediato | condenar a fonte em qualquer falha |
| 17 | Gatilho da média exige margem (`MARGEM_MEDIA_PCT`, default 10) | alertar em qualquer preço abaixo da média |
| 18 | Gatilho da média exige 30 dias distintos de histórico | usar a média disponível desde o primeiro dia |
| 19 | Editar a URL de uma fonte **preserva** o histórico | descartar a série a cada edição |
| 20 | Rules liberam `delete` em `historico`/`diario` para o dono | deixar histórico órfão ao excluir produto |
| 21 | Rules permitem reenfileirar fonte **saudável**, não só quebrada | impedir a edição de um link que funciona |
| 22 | `tests/test_rules.py` criado (fora da lista da §3) | deixar o item "rules testadas" da §17 sem teste |
| 23 | Erro de inicialização do Admin SDK sai com código 1 | sair 0 sempre, como diz a §11.2 |
| 24 | Índice em construção sai com código 0 (transitório) | job vermelho a cada deploy de índice |
| 25 | Nova variável `MARGEM_MEDIA_PCT`, fora da lista da §15 | fixar a margem em código |

### Decisão B revista após implementar

A denormalização de `produtoAtivo` na fonte foi aprovada, mas **não fecha**: as
rules têm `allow update: if false` para `fontes`, então o cliente nunca poderia
manter o campo sincronizado. A consulta passou a filtrar `status` + `comErro` no
servidor, e o `ativo` do produto é aplicado em Python com cache por produto —
custo zero, já que o produto é lido na etapa de alerta de qualquer forma.

**Erro cometido nessa troca:** eu afirmei que o índice de 3 campos
(`status`, `comErro`, `produtoAtivo`) atenderia a consulta de 2 campos "pelo
prefixo". Está errado, e a produção provou com
`FAILED_PRECONDITION: The query requires an index`. O índice foi criado com
`density: SPARSE_ALL`, o que significa que um documento só entra nele se tiver
**todos** os campos indexados — e como `produtoAtivo` deixou de ser gravado,
o índice estava vazio. Mudar a estratégia de consulta exige mudar o índice na
mesma passada. O índice correto é `(comErro, status)` em collection group, e o
de 3 campos foi removido.

---

## Contradições encontradas na spec

1. **Tabela 7.5 vs. passo 7 da mesma seção.** A tabela manda aceitar
   `"1.234.567,89"` → `123456789`, mas o passo 7 rejeita tudo acima de
   `TETO_CENTAVOS` = 100.000.000 — e a mesma tabela manda rejeitar
   `"2.000.000,00"` pelo mesmo motivo. Resolvido a favor do teto.
2. **Passo 2 da normalização apaga o sinal negativo.** Aplicado literalmente,
   `"-10,00"` viraria `1000` e passaria pelo passo 7, contrariando a tabela.
3. **Check da §17 acusa a fórmula da §6.** `grep "/ 100\|/100"` casa com
   `(alvo * (100 + tol)) // 100`, que é divisão inteira e é exatamente o que o
   check quer garantir. O check precisa virar `grep -n "[^/]/ *100"`.
4. **Formato do índice da §5.5.** Índice de campo único no array `indexes` é
   recusado pelo Firestore com `HTTP 400: this index is not necessary, configure
   using single field index controls`. O lugar certo é `fieldOverrides`.
5. **§5.3 não prevê campo para o motivo da falha**, mas a §9 exige gravá-lo.
   Adicionada a chave curta `e`.
6. **§12 diz que a única divisão por 100 está no front**, mas a §10.2 exige
   formatar `R$` na mensagem do Telegram. Resolvido com `divmod`, sem float.

---

## Lição aprendida em produção

**O emulador não valida índice nem IAM.** Os 28 testes verdes da fase 2 não
provaram que as consultas funcionam no Firestore de verdade — as duas primeiras
execuções reais falharam por coisas que o emulador aceita sem reclamar:

| Erro em produção | Causa | O emulador |
|---|---|---|
| `PERMISSION_DENIED` | service account sem papel no Firestore | não tem IAM |
| `FAILED_PRECONDITION` | índice de collection group errado | responde qualquer consulta sem índice |

E **a verificação de rede feita em laboratório não vale para produção**: a
Pichau, aprovada de IP residencial, recusou o datacenter do runner na primeira
execução. Ver o aviso na seção de lojas.

### Suíte verde, produção quebrada (2026-08-14)

Em 2026-08-14 a coleta estourou nas **9 fontes**, ciclo após ciclo:

```
NameError: name '_dia_atualizado' is not defined
```

A função tinha sido apagada dias antes, num refactor que removeu a média de 30
dias — mas `registrar_leitura` continuava chamando. **A suíte estava verde: 266
passed.**

Três coisas conspiraram, e só a primeira tem conserto automático:

| O que falhou | Por quê | Situação |
|---|---|---|
| A suíte não pegou | Python só resolve nome global ao **executar** a linha; o módulo importa numa boa | ✅ `tests/test_sanidade_estatica.py` — pyflakes resolve na hora de **ler** |
| Nada rodava teste antes do deploy | `coletor.yml` só executa o coletor | ✅ `testes.yml` em todo push e PR |
| O único teste do caminho não rodou | Exige o emulador, que exige Java, ausente na máquina de dev | ⚠️ **aberto por opção** — o CI é enxuto e não sobe emulador |

A linha aberta é **decisão consciente**, não esquecimento: subir o emulador no
runner levava ~3 min por push para cobrir um arquivo que muda pouco. O preço é
que `repositorio.py` só tem cobertura real quando alguém roda o emulador na mão.

O prejuízo foi menor do que parecia: a exceção sobe de dentro da
`@firestore.transactional`, **antes do commit**, então nada foi escrito pela
metade — e `falhasSeguidas` também não foi incrementado, porque fazia parte da
mesma transação abortada. Nenhuma fonte foi condenada injustamente. Perdeu-se só
a coleta do período.

**A lição que generaliza:** "N passed" não é o número que importa quando existe
um "M skipped" ao lado. Skip é cobertura ausente disfarçada de aprovação, e o
resumo do pytest apresenta os dois com o mesmo peso.

## O que falta

- **Verificar o front Vue no navegador e fazer o primeiro deploy dele.** O build
  compila e o preview serve, mas ninguém olhou as telas renderizadas com dados
  reais. O deploy é `firebase deploy --only hosting` (o `predeploy` builda
  sozinho).
- **Paridade do gráfico:** os quatro períodos já voltaram. Falta a escala em
  **variação %** (que permitia comparar produtos de faixas de preço diferentes) e
  a **comparação multi-produto** no mesmo eixo, que o front antigo tinha.
- **O seletor de período parece não fazer nada hoje**, e não é bug: o histórico
  tem 2 dias, então 7 dias / mensal / anual mostram os mesmos 2 pontos. Só o
  período "dia" difere (12 leituras contra 2 fechamentos). Isso se resolve
  sozinho com o tempo.
- **As quatro lojas nunca foram buscadas DO RUNNER.** O ciclo real de 2026-08-12
  rodou desta máquina e aprovou as quatro (ver tabela acima), mas o runner é IP
  de datacenter e a Amazon é justamente o tipo de loja que trata os dois de forma
  diferente. Portão: disparar o `workflow_dispatch` e ler o log. Se vier
  `pagina_de_bloqueio` para a Amazon, o diagnóstico já está certo — é bloqueio,
  não parser.
- **A Pichau está em `falhasSeguidas=4` — uma de ser desligada.** Depois do
  primeiro acerto (200), veio uma sequência de `http_403`. O desenho aguenta,
  mas se ela ficar mais errando que acertando, a série histórica fica cheia de
  buracos e vale reconsiderar se compensa mantê-la.
- **O ajuste do preço à vista da Pichau nunca rodou contra a página ao vivo.**
  Está verificado contra a captura (4.699,99, origem `e`), e é só isso: todas as
  buscas ao vivo desde então tomaram 403, então o caminho completo
  busca → estado → centavos ainda não foi exercitado de ponta a ponta com HTML
  fresco.
- **`sem_oferta_ativa` da Amazon é um estado, não um conserto.** A URL cadastrada
  hoje é de um produto sem vendedor. Quando alguém voltar a vender, a fonte lê
  sozinha — mas até lá ela vai acumular falhas e, na quinta, ser desativada.
  Se o produto ficar muito tempo sem oferta, troque a URL.
- Conferir o consumo no console do Firebase após 48h de operação — a raspagem
  de 14 categorias escreve mais do que o desenho original previa.
- Não existe `tests/test_main.py`: a lista de arquivos da §3 não prevê esse
  arquivo e o portão da fase é a execução real. `esta_na_hora` e o agrupamento
  por produto estão cobertos apenas pela verificação manual no emulador.
- O front Vue não tem teste automatizado — a validação portada de
  do front antigo está coberta apenas pela leitura; um smoke com Vitest seria
  o próximo investimento se o front continuar crescendo.
