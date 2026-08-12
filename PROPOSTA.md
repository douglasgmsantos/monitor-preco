# Monitor de Preços — o projeto, para redesenho de layout

Documento autocontido para alimentar uma ferramenta de geração de layout. Quem
ler isto **não tem acesso ao código**.

O pedido é **layout e posicionamento**: onde cada coisa fica, o que ganha
destaque, o que se agrupa com o quê, como se comporta em telas diferentes.
Portanto este documento descreve **o que o app é, o que ele faz e quais peças ele
tem** — de propósito não descreve o arranjo atual, para não amarrar a proposta ao
que já existe. Você tem liberdade total de posicionamento.

---

## 1. O que é o app

Um monitor pessoal de preço de hardware de PC.

O usuário cadastra um produto que quer comprar, diz **por quanto compraria**, e
aponta uma ou mais URLs de páginas de produto em lojas brasileiras. Um robô
visita essas páginas de tempo em tempo, guarda o preço, e manda mensagem no
Telegram quando o preço cai até o alvo — ou quando fica abaixo da média
histórica.

O valor não está no alerta em si: está em não abrir dez abas por semana para
descobrir que nada mudou.

**A interface web serve para cadastrar, acompanhar e entender o histórico.** Ela
não coleta nada e não dispara nada — quem faz isso é o robô, sozinho, de hora em
hora.

### Quem usa

Uma pessoa. Sem times, papéis, permissões ou convites. Dois modos de uso, bem
diferentes em peso:

| Momento | Onde | O que quer |
|---|---|---|
| **Constante** | celular, poucos segundos | "caiu algo? o que mudou desde ontem?" |
| **Raro** | desktop, alguns minutos | cadastrar produto, comparar histórico, arrumar fonte quebrada |

O uso frequente é **leitura**. O cadastro é a exceção, não a regra.

### Três conceitos, e é só

```
PRODUTO  ──┬── FONTE (loja + URL)  ──▶ série histórica de preço
"o que eu  ├── FONTE (loja + URL)  ──▶ série histórica de preço
 quero     └── FONTE (loja + URL)  ──▶ série histórica de preço
 comprar"

CATÁLOGO   uma vitrine separada, de produtos que o robô encontrou varrendo
           páginas de categoria. Serve para DESCOBRIR o que cadastrar.
```

Um produto tem N fontes porque o mesmo item é vendido em várias lojas, e o que
interessa é o menor preço entre elas.

---

## 2. Funcionalidades

Lista completa do que o app faz hoje. Tudo isto precisa caber em algum lugar do
layout novo.

### Conta

- Entrar com e-mail e senha
- Criar conta com e-mail e senha
- Entrar com Google
- Sair
- Alternar tema: claro, escuro, ou seguir o sistema

### Cadastrar e manter produtos

- Cadastrar produto com **nome**, **preço-alvo** e **tolerância percentual**
- Adicionar **várias fontes** (loja + URL) ao mesmo produto
- Escolher a loja numa lista curta de lojas suportadas, ou digitar uma loja livre
- **Recusar loja incompatível**, mostrando o motivo verificado. Sete lojas estão
  na lista de incompatíveis, cada uma com um motivo específico ("monta a página
  por JavaScript", "bloqueia requisições automatizadas", e assim por diante).
  Este aviso é conteúdo, não decoração: é o que impede o usuário de achar que o
  sistema quebrou
- Editar produto e suas fontes. Trocar a URL de uma fonte **preserva o histórico**
- Remover uma fonte
- **Pausar** e **retomar** a coleta de um produto. Pausado continua visível e com
  histórico intacto — só não é visitado pelo robô
- Excluir produto
- **Retentar uma fonte quebrada**, devolvendo-a para a fila de validação

### Acompanhar

- Ver os produtos acompanhados com o **menor preço atual** entre as fontes
- Ver o **estado** de cada produto e de cada fonte
- Abrir a página da loja em nova aba
- Selecionar um produto para inspecionar o histórico dele

### Descobrir (catálogo)

- Navegar a vitrine de produtos que o robô encontrou
- Filtrar por categoria (com contagem de itens)
- Buscar por nome
- Ordenar por preço ou por nome
- Paginar
- Ver imagem, preço, e preço "de" riscado quando a loja publica os dois
- Reconhecer itens **já acompanhados** e itens **esgotados**
- **Acompanhar um item do catálogo**, o que inicia o cadastro já preenchido —
  falta só o preço-alvo, que é a única informação que o catálogo não tem

### Entender o histórico

- Gráfico de linha, **uma linha por fonte**, para comparar lojas
- Trocar o período: 1 dia, 1 semana, 1 mês, 1 ano
- Trocar a escala: reais, ou variação percentual (permite comparar produtos de
  faixas de preço diferentes na mesma tela)
- Ver os mesmos dados **como tabela** — não é conveniência, é acessibilidade:
  garante leitura quando o contraste da linha não alcança o mínimo
- Visão de todos os produtos ao mesmo tempo, em escala indexada, quando nenhum
  está selecionado

---

## 3. Peças de dado disponíveis

Isto é o inventário do que existe para mostrar. **Não invente campo fora desta
lista** — um layout que dependa de dado inexistente é um layout que não pode ser
implementado.

### De um produto

| Peça | Exemplo |
|---|---|
| nome | `Placa de vídeo RX 7600` |
| preço-alvo | `R$ 1.789,90` |
| tolerância | `0%` |
| preço-gatilho (calculado) | `R$ 1.789,90` |
| estado | `em alerta` \| `acima do alvo` |
| ativo ou pausado | booleano |
| quando foi o último alerta | data e hora |
| menor preço atual entre as fontes | `R$ 1.749,90` |

### De uma fonte

| Peça | Exemplo |
|---|---|
| loja | `KaBuM` |
| URL | `kabum.com.br/produto/123456/…` |
| estado | `ok` \| `validando` \| `inválida` \| `desativada após 5 falhas` |
| motivo, quando inválida | `sem_jsonld` |
| falhas seguidas | `0` a `5` |
| último preço lido | `R$ 1.749,90` |
| quando foi a última coleta | data e hora |

### Do histórico

Série temporal por fonte. Cada leitura tem: instante, preço, se estava
disponível, se o valor foi marcado como suspeito, e de onde o preço foi extraído.
Existe também um resumo diário, que é o que alimenta períodos longos.

### Do catálogo

| Peça | Exemplo |
|---|---|
| nome | `Placa de Vídeo RTX 4060 8GB` |
| imagem | URL |
| preço da vitrine | `R$ 1.899,00` |
| preço "de" riscado | `R$ 2.199,00` (quando existe) |
| disponível | booleano |
| loja e categoria | `kabum.com.br` · `placas-de-video` |
| link da página | URL |

### Dado que existe e hoje não aparece em lugar nenhum

**A média histórica de 30 dias.** O robô calcula, e ela é um dos dois motivos de
alerta ("abaixo da média histórica"). Mas a interface nunca mostra esse número.
Ou seja: hoje o usuário recebe um alerta que menciona uma média que ele não
consegue ver em tela. Se o layout novo tiver um bom lugar para isso, é ganho de
graça.

---

## 4. Estados que o layout precisa saber expressar

**Um produto** está em um destes:

- **em alerta** — o preço caiu e a notificação foi enviada. É a boa notícia
- **acima do alvo** — situação normal, nada a fazer
- **pausado** — o robô parou de visitar. Nada foi apagado

**Uma fonte** está em um destes:

- **ok** — funcionando
- **validando** — recém-cadastrada, o robô ainda não confirmou que consegue ler
- **inválida** — o robô não consegue extrair preço, e há um motivo
- **desativada após 5 falhas** — desistiu, e precisa de ação do usuário

Regra dura: **estado nunca é comunicado só por cor.** Sempre cor + ícone +
rótulo textual. Daltonismo e captura de tela em preto e branco continuam
legíveis.

---

## 5. Vocabulário

Português do Brasil em 100% da interface. Use exatamente estes termos — eles
aparecem no banco, nas mensagens do Telegram e na cabeça do usuário.

| Termo | Significa |
|---|---|
| **produto** | o que o usuário quer comprar |
| **fonte** | uma URL de uma loja para um produto |
| **coleta** | uma visita do robô a uma fonte |
| **catálogo** / **vitrine** | os produtos descobertos por varredura |
| **preço-alvo** | por quanto o usuário compraria |
| **tolerância** | folga percentual sobre o alvo |
| **gatilho** | o preço calculado em que o alerta dispara |
| **em alerta** | o preço caiu e a notificação foi enviada |
| **pausado** | a coleta parou, mas nada foi apagado |

Dinheiro: `R$ 1.789,90` — ponto de milhar, vírgula decimal, sempre duas casas.
Preço e número em tabela com dígitos de largura fixa, para as colunas não
dançarem quando o valor muda.

---

## 6. Dois fatos do domínio que mudam o desenho

**O preço do catálogo não é comparável com o preço acompanhado.** O da vitrine é
o preço de **tabela**, medido entre 10% e 31% ACIMA do preço real da página do
produto. Ele nunca dispara alerta; serve só para achar o produto. Quando o
usuário passa a acompanhar, o preço vem da página. **O layout precisa deixar isso
óbvio**, ou o usuário compara dois números que não são comparáveis e conclui que
o app está errado.

**Nada é ao vivo.** O robô roda a cada 15 minutos, mas só trabalha de verdade
quando o intervalo passou: 3 horas para preço, 24 horas para o catálogo. O dado
em tela tem horas de idade. Um layout que sugira tempo real — "atualizando
agora", pulso verde, contador em segundos — estaria mentindo. O que **ajudaria** é
mostrar com clareza quando foi a última leitura.

---

## 7. Restrições técnicas — não negociáveis

| | |
|---|---|
| Hospedagem | estática. Sem servidor próprio, sem SSR, sem rota de servidor |
| Build | **não existe**. Os arquivos são servidos como estão |
| Estrutura | um HTML com CSS embutido, um JavaScript de módulo, um de configuração |
| Framework | nenhum. JavaScript puro com `import` nativo |
| Dependência externa | uma só, para o gráfico |
| Banco | o front lê e escreve direto no banco. Não há API para chamar |
| Moeda | somente Real |

**Sobre framework:** proposta em React, Vue ou Svelte é inútil aqui, porque não
há passo de build para compilá-la. Se o redesenho exigir framework, ele exige
antes uma decisão de infraestrutura que está fora deste briefing. Prefira
HTML + CSS + JavaScript que rodem abertos no navegador.

**Sobre CSS:** preferência forte por CSS artesanal com variáveis (tokens). O CSS
atual tem ~230 linhas — o objetivo não é reduzir isso, é organizar melhor.

### Tema: três estados, não dois

Já funciona assim e precisa continuar:

1. **claro** é o padrão
2. **escuro** quando o sistema pede
3. **escolha explícita** do usuário, que **vence o sistema nos dois sentidos**

Escuro não é o inverso automático do claro: é uma paleta escolhida à mão.

### Paleta atual — reaproveitar é opcional

```
claro:  fundo #f9f9f7 · superfície #fcfcfb · texto #0b0b0b
        secundário #52514e · terciário #898781 · bordas #c3c2b7
escuro: fundo #0d0d0d · superfície #1a1a19 · texto #ffffff
        secundário #c3c2b7 · terciário #898781 · bordas #383835
semântico: bom #0ca30c · atenção #fab219 · crítico #d03b3b
séries (gráfico, 8 cores): #2a78d6 #eb6834 #1baf7a #eda100
                           #e87ba4 #008300 #4a3aa7 #e34948
```

As oito cores de série são a paleta categórica do gráfico, validada para
contraste nos dois modos. Pode trocar, mas a substituta precisa passar o mesmo
teste — e é por isso que o gráfico tem rótulo na ponta da linha e uma tabela
equivalente.

---

## 8. Objetivos do layout novo

O que eu quero que o novo arranjo resolva, em ordem de importância.

**1. Priorizar leitura sobre cadastro.** O usuário abre o app para saber se caiu
de preço. Cadastrar é raro. O que ele vê primeiro deve refletir essa proporção.

**2. Responder "o que mudou desde a última vez que eu olhei?"** É literalmente a
pergunta que traz o usuário, e hoje nenhuma parte da tela responde. Todo o dado
para responder existe.

**3. Aproximar o histórico do produto.** Selecionar um produto e inspecionar a
série dele deveriam ser um gesto, não dois passos distantes. A ligação entre
"qual produto" e "qual linha do gráfico" precisa ser evidente.

**4. Separar visualmente descobrir de acompanhar.** São duas coisas de natureza
diferente — "o que existe no mundo" e "o que eu vigio" — com preços que nem são
comparáveis (seção 6). Hoje elas se parecem demais.

**5. Fazer o celular funcionar de verdade.** É o dispositivo do uso frequente, e
hoje é o pior caso: tudo vira uma coluna e a página fica longuíssima.

**6. Dar um caminho suave de "achei no catálogo" até "estou acompanhando".** Esse
é o fluxo que transforma navegação em uso, e hoje ele joga o usuário para outro
canto da tela sem aviso.

**7. Tratar bem os estados chatos.** Vazio, carregando, fonte quebrada, primeira
vez sem nenhum produto. Hoje são parágrafos de texto cinza.

**8. Dar filtro e ordenação à lista de acompanhados.** O catálogo tem; a lista
principal não. Com trinta produtos vira uma parede.

### O que eu gostaria de receber

Propostas de **arranjo**: hierarquia, agrupamento, o que é primário e o que é
secundário, comportamento em telas estreitas. Formatos úteis, em ordem de
preferência: HTML + CSS navegável, wireframe anotado, ou descrição estruturada de
layout com hierarquia e responsividade explícitas.

Mais de uma alternativa é bem-vinda, sobretudo para o objetivo 1 — há mais de uma
resposta defensável para "o que aparece primeiro".

---

## 9. Não-objetivos

Cada item já foi decidido ou está fora de alcance.

- **Multiusuário, times, compartilhamento, comentários.** É um app de uma pessoa
- **Comprar dentro do app, cupom, cashback, link de afiliado**
- **Mais lojas.** A lista é curta porque cada loja foi verificada uma a uma; as
  ausentes estão ausentes por motivo medido, não por esquecimento
- **Tempo real, WebSocket, "atualizando agora".** Ver seção 6
- **Notificação push do navegador.** O alerta é por Telegram, por decisão de custo
- **Recomendação, "quem viu comprou", previsão de preço**
- **Framework com passo de build**, salvo se você declarar essa dependência como
  pré-requisito explícito
- **Trocar o banco ou a hospedagem**
- **Inventar dado que o sistema não tem.** Não existe avaliação, nota de
  vendedor, estoque exato, prazo de entrega, frete nem parcelamento. Layout que
  dependa de um desses é layout que não pode ser implementado — a seção 3 é a
  lista fechada
