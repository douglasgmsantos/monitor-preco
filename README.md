# Monitor de Preços

Monitora o preço de produtos em lojas de e-commerce brasileiras. Você cadastra o
produto com preço-alvo, tolerância e as URLs onde ele é vendido. Um coletor
agendado extrai o preço do bloco `application/ld+json` das páginas, grava a série
histórica e avisa no Telegram quando o preço entra na faixa aceitável.

Além do acompanhamento por URL, existe um **catálogo de descoberta**: o coletor
varre páginas de listagem das lojas verificadas (14 categorias hoje) e monta uma
vitrine para achar o que cadastrar — o preço-alvo é a única informação que a
vitrine não tem.

A interface é o app Vue em [frontend/](frontend/) (visual "Radar"). O site é
https://report-price.web.app — **o que está no ar ainda é o front antigo**; o
Vue entra no próximo `firebase deploy --only hosting`. O front antigo, sem
build, segue em `publico/` como referência e rota de retorno.

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
| 6 | front (`publico/`) | ✅ substituído pelo Vue; mantido como referência |
| — | security rules | ✅ 24 testes contra o emulador (`tests/test_rules.py`) |
| — | raspagem de catálogo (`coletor/raspagem.py`) | ✅ 14 categorias (KaBuM via JSON-LD, Terabyte via seletores DOM); vitrine acumulativa |
| — | front Vue "Radar" (`frontend/`) | ✅ build ok; **pendente de verificação visual e deploy** |

```
205 passed, 77 skipped        # sem o emulador do Firestore (76 pulados são dele)
281 passed, 1 skipped         # com o emulador rodando
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
├── frontend/     app Vue "Radar" — o front publicado
├── publico/      front antigo sem build — referência e rota de retorno
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

Só entram lojas verificadas na página de produto real: o preço vem em
`application/ld+json` por HTTP simples, e o User-Agent honesto do coletor
(`MonitorPrecos/1.0`) não é bloqueado.

| Loja | `price` observado | `availability` |
|---|---|---|
| KaBuM | `3499.9` (float) | `https://schema.org/OutOfStock` |
| Terabyte Shop | `"1789.99"` (string) | `http://schema.org/InStock` |
| Carrefour | `9990` (int) | `http://schema.org/InStock` |

### Lojas que NÃO funcionam

| Loja | Motivo (verificado) |
|---|---|
| Amazon | não publica JSON-LD — zero blocos em 1,8 MB de HTML |
| Mercado Livre | serve um shell de ~39 KB e monta tudo por JavaScript |
| Magazine Luiza | HTTP 403 em **tudo**, inclusive na home, com qualquer User-Agent |
| Pichau | responde de IP residencial, **recusa o datacenter** onde o coletor roda (HTTP 403) |
| Americanas | responde 200, mas monta tudo por JS: home só tem `WebSite`/`Organization`, busca vem com 0 preços no HTML |
| Submarino, Shoptime | mesma plataforma da Americanas |

O front recusa todas essas de saída. Outras lojas podem ser cadastradas em
"Outra loja", mas só a primeira coleta dirá se a página é legível.

> **Aviso sobre a lista acima.** A verificação inicial foi feita de um IP
> residencial brasileiro. O coletor roda de um IP de datacenter (Azure, via
> GitHub Actions), e lojas com anti-bot tratam os dois de forma diferente — foi
> exatamente assim que a Pichau, aprovada em laboratório, falhou na primeira
> execução real. **Só a produção decide quais lojas funcionam.** KaBuM, Terabyte
> e Carrefour seguem sem confirmação em produção.

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
falha), `d` disponível, `s` suspeito, `o` origem (`j` jsonld / `g` opengraph /
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

| Situação | Ação |
|---|---|
| Preço cruza o gatilho pela primeira vez | notifica, vai para `EM_ALERTA` |
| Continua abaixo, sem cair mais 5% | silêncio |
| Cai mais 5% abaixo do último preço avisado | renotifica |
| Volta acima do gatilho | silêncio e rearma para `ACIMA` |
| Indisponível ou leitura suspeita | silêncio, estado inalterado |

Mais cooldown de no máximo 1 mensagem por produto a cada 24h. Numa simulação de
84h com o preço abaixo do alvo a maior parte do tempo: **4 mensagens em 14
ciclos**.

A mensagem muda de título conforme o gatilho. Dizer "Preço atingido" quando só a
média justificou o alerta seria falso, então nesse caso o título é
"📉 Abaixo da média histórica" e a referência exibida é a média, não o alvo.

## O que o front faz

O front publicado é o app Vue "Radar" ([frontend/](frontend/)), organizado em
duas abas — **Monitoramento** e **Catálogo** — com o cadastro em modal:

- **Login** com e-mail/senha e Google
- **Monitoramento**: cartões com preço atual, **média de 30 dias** (a primeira
  vez que o número que dispara o alerta "abaixo da média" aparece em tela),
  menor preço do período e estado (`alerta de preço baixo` / `monitorando` /
  `aguardando primeira coleta` / `pausado`)
- **Análise detalhada** do produto selecionado: fontes com status e preço,
  flutuação de 30 dias em barras + tabela equivalente (acessibilidade)
- **Descoberta**: sugestões do catálogo ainda não acompanhadas
- **Catálogo**: vitrine completa com filtro por categoria, busca, ordenação e
  paginação; acompanhar um item pré-preenche o cadastro
- **Cadastrar/editar** produto com N pares loja/URL em modal, com a recusa de
  loja incompatível explicando o motivo verificado
- **Pausar / retomar** coleta sem perder histórico
- **Excluir** produto, com cascata manual (ver abaixo)
- **Tentar de novo** numa fonte que falhou

> **Diferença deliberada para o front antigo:** o gráfico de linhas com períodos
> 1d/1s/1m/1a e escala R$/% foi substituído pela flutuação de 30 dias em barras,
> seguindo o desenho "Radar". A lógica das séries longas continua em
> `publico/app.js` se a paridade fizer falta — está listada em "O que falta".

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

A config **pública** do front fica em `publico/firebase-config.js`. Isso não é
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

O front antigo (HTML + JS puro, sem build) segue intacto em `publico/` como
referência e rota de retorno:

```bash
cd publico && python3 -m http.server 8090   # localhost já é domínio autorizado
```

> Evite a porta 8080 para servir o front: é a porta do emulador do Firestore, e
> um servidor de arquivos parado ali já travou a suíte de testes uma vez (o
> probe dos testes hoje distingue os dois, mas não há motivo para conviver com
> a colisão).

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

## O que falta

- **Verificar o front Vue no navegador e fazer o primeiro deploy dele.** O build
  compila e o preview serve, mas ninguém olhou as telas renderizadas com dados
  reais. O deploy é `firebase deploy --only hosting` (o `predeploy` builda
  sozinho); reverter é apontar `firebase.json` de volta para `publico`.
- **Paridade do gráfico, se fizer falta no uso:** o front novo mostra só a
  flutuação de 30 dias; os períodos 1d/1s/1a, a escala em variação % e a
  comparação multi-produto do front antigo não foram portados.
- Conferir o consumo no console do Firebase após 48h de operação — a raspagem
  de 14 categorias escreve mais do que o desenho original previa.
- Não existe `tests/test_main.py`: a lista de arquivos da §3 não prevê esse
  arquivo e o portão da fase é a execução real. `esta_na_hora` e o agrupamento
  por produto estão cobertos apenas pela verificação manual no emulador.
- O front Vue não tem teste automatizado — a validação portada de
  `publico/app.js` está coberta apenas pela leitura; um smoke com Vitest seria
  o próximo investimento se o front continuar crescendo.
