# Frontend em Vue — "Radar"

Reescrita do front em Vue 3 + Vite, com o visual do desenho "Radar". A lógica
foi **portada, não reinventada**: validação de loja incompatível, conversão de
dinheiro, transições de status que as rules aceitam — tudo veio de
`publico/app.js` letra por letra. `publico/` continua no repositório como
referência e rota de retorno.

## Comandos

```bash
cd frontend
npm install        # uma vez
npm run dev        # desenvolvimento, em http://localhost:5173
npm run build      # gera dist/
npm run preview    # serve o dist/ localmente
```

O deploy não mudou de comando: `firebase deploy --only hosting` na raiz. O
`predeploy` em `firebase.json` instala e builda sozinho — não existe como
publicar um `dist/` desatualizado por esquecimento.

## Para voltar ao front antigo

Troque em `firebase.json`: `"public": "frontend/dist"` → `"public": "publico"`
e remova o bloco `predeploy`. Nada em `publico/` foi alterado.

## Decisões que divergem do desenho, e por quê

O desenho de referência mostra dados que o sistema NÃO tem. Em vez de inventar:

| No desenho | Aqui | Motivo |
|---|---|---|
| "Monitorado por 1.2k usuários" | preço de vitrine + loja | não existe contagem de usuários por produto |
| marca (SONY, APPLE) | categoria do catálogo | não existe campo de marca |
| imagem no cartão de produto | imagem do catálogo casada pela URL da fonte, ou a inicial do nome | produto criado à mão não tem imagem; as rules não guardam esse campo |
| modal só com nome + URL | nome + **preço-alvo + tolerância** + fontes | os campos são obrigatórios no modelo; sem alvo não há alerta |
| linha do gráfico ao vivo | flutuação de 30 dias em barras, do rollup diário | é o dado que existe; nada no sistema é ao vivo |

A média de 30 dias que aparece nos cartões e na análise vem do rollup `diario`
(fechamento por dia, menor entre as fontes) — o mesmo dado que alimenta o
alerta "abaixo da média histórica". É a primeira vez que esse número aparece em
tela.

## Estrutura

```
src/
  firebase.js               init do app/auth/db (config pública)
  dinheiro.js               formatarBRL + paraCentavos (cópia da seção 7.5)
  lojas.js                  lojas suportadas, incompatíveis com motivo, siglas
  tempo.js                  "há X minutos" + chaves de bucket (dia/mês/ano)
  composables/
    useAuth.js              login e-mail/senha + Google, tradução de erros
    useProdutos.js          snapshots em tempo real + todas as escritas
    useCatalogo.js          vitrine (1 leitura por categoria)
    useHistorico.js         resumo de 30 dias (média, menor, série), cacheado
  components/
    TopoRadar.vue           marca, abas Monitoramento/Catálogo, + Novo produto
    TelaLogin.vue
    VisaoMonitoramento.vue  Descoberta + Seu radar + Análise detalhada
    VisaoCatalogo.vue       vitrine completa com filtros e paginação
    CartaoProduto.vue       o cartão grande com ATUAL / MÉDIA 30D / MENOR
    CartaoDescoberta.vue    o cartão compacto da faixa de sugestões
    AnaliseDetalhada.vue    fontes + ações + flutuação de 30 dias
    LinhaFonte.vue          sigla, status com ponto, preço
    GraficoBarras.vue       barras em CSS puro (sem Chart.js)
    ModalProduto.vue        criação/edição com a validação portada
    SeloProduto.vue         ALERTA DE PREÇO BAIXO / MONITORANDO / etc.
```

Sem Chart.js: o desenho pede barras simples, e um componente de ~80 linhas
resolve sem dependência. A tabela equivalente continua existindo (regra de
alívio de acessibilidade), no botão "Ver como tabela".
