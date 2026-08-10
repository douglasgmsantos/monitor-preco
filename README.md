# Monitor de Preços

Monitora o preço de produtos em lojas de e-commerce brasileiras. Você cadastra o
produto com preço-alvo, tolerância e as URLs onde ele é vendido. Um coletor
agendado extrai o preço do bloco `application/ld+json` das páginas, grava a série
histórica e avisa no Telegram quando o preço entra na faixa aceitável.

Não há busca nem descoberta de produtos: você informa as URLs.

**Custo: R$ 0,00.** Nenhuma peça exige cartão de crédito.

---

## Estado atual

| Fase | Entrega | Situação |
|---|---|---|
| 0 | rules, índices, projeto Firebase | ✅ publicado e verificado no servidor |
| 1 | `coletor/parser.py` | ✅ tabela 7.5 + 4 fixtures reais |
| 2 | `coletor/repositorio.py` | ✅ 28 testes contra o emulador |
| 3 | `coletor/coleta.py` | ✅ 24 testes com `respx` |
| 4 | `coletor/alertas.py`, `notificador.py` | ✅ 31 testes, sem rede |
| 5 | `coletor/main.py`, workflow do Actions | ❌ **não implementada** |
| 6 | front (`publico/`) | ✅ publicado em https://report-price.web.app |

```
166 passed, 1 skipped
```

**Sem a Fase 5 o sistema não coleta nada.** As fontes cadastradas ficam
permanentemente em "validando fonte…", porque nada as promove a `ok`. O front e
todo o núcleo estão prontos e testados; falta o entrypoint e o agendamento.

---

## Arquitetura

```
┌─────────────────┐   Auth + leitura direta   ┌──────────────────┐
│  Front estático │◄─────────────────────────►│    Firestore     │
│ Firebase Hosting│      (security rules)     │     (Spark)      │
└─────────────────┘                           └────────▲─────────┘
                                                       │ Admin SDK
                                              ┌────────┴─────────┐
                                              │ GitHub Actions   │
                                              │ cron */15min     │
                                              │  → lojas (HTTP)  │
                                              │  → Telegram      │
                                              └──────────────────┘
```

Não existe servidor de API. O front autentica no Firebase Auth e lê o Firestore
direto, contido pelas security rules. O coletor roda no GitHub Actions com o
Admin SDK, que ignora as rules.

### Por que cada peça é gratuita

| Peça | Limite gratuito | Uso previsto |
|---|---|---|
| Firestore leituras | 50.000/dia | ~50/dia |
| Firestore escritas | 20.000/dia | ~50/dia |
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
| Pichau | `"34117.64"` (string) | `https://schema.org/InStock` |
| Carrefour | `9990` (int) | `http://schema.org/InStock` |

### Lojas que NÃO funcionam

| Loja | Motivo (verificado) |
|---|---|
| Amazon | não publica JSON-LD — zero blocos em 1,8 MB de HTML |
| Mercado Livre | serve um shell de ~39 KB e monta tudo por JavaScript |
| Magazine Luiza | HTTP 403 mesmo com User-Agent de navegador |

O front recusa essas três de saída. Outras lojas podem ser cadastradas em
"Outra loja", mas só a primeira coleta dirá se a página é legível.

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
```

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

```bash
cd publico && python3 -m http.server 8080   # localhost já é domínio autorizado
```

---

## Operação

**O GitHub desabilita workflows agendados após um período de inatividade no
repositório.** Dispare o `workflow_dispatch` manualmente ao menos uma vez por
mês, ou faça um commit. O GitHub avisa por e-mail antes de desabilitar — não
ignore esse e-mail.

O cron roda de 15 em 15 minutos, mas a coleta pesada só acontece quando
`sistema/controle.ultimaColetaEm` indica que o intervalo real passou. O GitHub
atrasa e **pula** execuções sob carga; a cadência efetiva é "pelo menos a cada
6h", não "exatamente às 00h, 06h, 12h, 18h". Nunca calcule o tempo decorrido a
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

### Decisão B revista após implementar

A denormalização de `produtoAtivo` na fonte foi aprovada, mas **não fecha**: as
rules têm `allow update: if false` para `fontes`, então o cliente nunca poderia
manter o campo sincronizado. A consulta filtra `status` + `comErro` no servidor
— o índice composto publicado atende pelo prefixo — e o `ativo` do produto é
aplicado em Python, com cache por produto. Custo zero: o produto é lido na etapa
de alerta de qualquer forma.

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

## O que falta

- **Fase 5:** `coletor/main.py` e `.github/workflows/coletor.yml`.
- Verificação visual do front em navegador (feita pelo usuário, não por mim).
- Confirmar que o provedor Google de login está habilitado — a API pública não
  permite sondar isso.
- Conferir o consumo no console do Firebase após 48h de operação.
