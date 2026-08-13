<script setup>
// Colunas = preço de cada ponto do período. Linha = a média do período.
//
// A linha horizontal é o que dá sentido às colunas: sozinhas elas mostram
// oscilação, mas não respondem "está barato agora?". Contra a média, cada barra
// vira uma resposta — e é a MESMA média de 30 dias que o alerta usa, então a
// tela e o Telegram contam a mesma história.
//
// SVG e não <div>: linha, rótulo e barra precisam compartilhar o mesmo sistema
// de coordenadas. Com divs a linha da média seria um `top: %` calculado à parte,
// que sai do lugar assim que a escala muda.
import { computed } from "vue";
import { formatarBRL } from "../dinheiro.js";

const props = defineProps({
  serie: { type: Array, required: true },   // [{chave, quando, centavos}]
  media: { type: Number, default: null },   // centavos; null = sem histórico
  periodo: { type: String, default: "30d" },
});

// Coordenadas internas. O SVG escala sozinho via viewBox, então estes números
// são só proporção — não pixels.
const L = 8, R = 8, TOPO = 18, BASE = 34;   // BASE abriga os rótulos do eixo
const LARGURA = 600, ALTURA = 200;

const porHora = computed(() => props.periodo === "dia");

function quandoLegivel(quando) {
  return porHora.value
    ? quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

const valores = computed(() => props.serie.map((p) => p.centavos));

// A escala inclui a média de propósito: se ela ficasse fora do intervalo das
// barras, a linha sairia do quadro e o gráfico mentiria por omissão.
const faixa = computed(() => {
  const todos = [...valores.value];
  if (props.media !== null) todos.push(props.media);
  if (!todos.length) return { min: 0, max: 1 };
  const min = Math.min(...todos);
  const max = Math.max(...todos);
  if (min === max) return { min: min * 0.98, max: max * 1.02 };
  const folga = (max - min) * 0.12;
  return { min: min - folga, max: max + folga };
});

function y(centavos) {
  const { min, max } = faixa.value;
  const proporcao = (centavos - min) / (max - min);
  return TOPO + (1 - proporcao) * (ALTURA - TOPO - BASE);
}

const larguraDaBarra = computed(() => {
  const util = LARGURA - L - R;
  const passo = util / Math.max(1, props.serie.length);
  return Math.max(2, Math.min(28, passo * 0.72));
});

const barras = computed(() => {
  const util = LARGURA - L - R;
  const passo = util / Math.max(1, props.serie.length);
  const menor = Math.min(...valores.value);
  const maior = Math.max(...valores.value);
  return props.serie.map((ponto, i) => ({
    ...ponto,
    x: L + passo * i + (passo - larguraDaBarra.value) / 2,
    y: y(ponto.centavos),
    altura: Math.max(1, ALTURA - BASE - y(ponto.centavos)),
    eMinimo: ponto.centavos === menor,
    eMaximo: ponto.centavos === maior && maior !== menor,
    eUltimo: i === props.serie.length - 1,
    centro: L + passo * i + passo / 2,
  }));
});

// Com 30 barras, escrever o valor em todas vira ruído ilegível. Até 10 mostra
// tudo; acima disso, só o que se procura num gráfico de preço: o mais barato, o
// mais caro e o de agora.
const MAXIMO_COM_TODOS_OS_ROTULOS = 10;

const rotulados = computed(() =>
  barras.value.filter((b) =>
    props.serie.length <= MAXIMO_COM_TODOS_OS_ROTULOS
      ? true
      : b.eMinimo || b.eMaximo || b.eUltimo));

const yMedia = computed(() => (props.media === null ? null : y(props.media)));

// Rótulo de período por coluna. Com 30 barras não cabe um em cada — escrever
// todos vira borrão. Mostra no máximo 8, espaçados por igual, e SEMPRE o
// último: "hoje" é a referência que o olho procura primeiro.
const MAXIMO_DE_ROTULOS_NO_EIXO = 8;

const rotulosDoEixo = computed(() => {
  const total = barras.value.length;
  if (!total) return [];
  const passo = Math.max(1, Math.ceil(total / MAXIMO_DE_ROTULOS_NO_EIXO));
  return barras.value.filter((_, i) => i % passo === 0 || i === total - 1);
});

/** Valor curto para caber sobre a barra: "4,7k" em vez de "R$ 4.699,99". */
function curto(centavos) {
  const reais = centavos / 100;
  if (reais >= 1000) {
    const milhares = reais / 1000;
    return `${milhares.toFixed(milhares >= 10 ? 0 : 1).replace(".", ",")}k`;
  }
  return String(Math.round(reais));
}
</script>

<template>
  <div class="grafico">
    <!-- Sem preserveAspectRatio="none": esticar o SVG deformaria os rótulos de
         valor junto com as barras. Escala uniforme, altura pelo viewBox. -->
    <svg :viewBox="`0 0 ${LARGURA} ${ALTURA}`" role="img"
         :aria-label="`Flutuação de preço em ${serie.length} pontos` +
                      (media !== null ? `; média ${formatarBRL(media)}` : '')">
      <!-- linha da média, atrás das barras para não competir com elas -->
      <template v-if="yMedia !== null">
        <line class="linha-media" :x1="L" :x2="LARGURA - R" :y1="yMedia" :y2="yMedia" />
      </template>

      <g v-for="b in barras" :key="b.chave">
        <rect
          class="barra"
          :class="{ minima: b.eMinimo, maxima: b.eMaximo }"
          :x="b.x" :y="b.y" :width="larguraDaBarra" :height="b.altura" rx="3"
        >
          <title>{{ quandoLegivel(b.quando) }} — {{ formatarBRL(b.centavos) }}</title>
        </rect>
      </g>

      <text
        v-for="b in rotulosDoEixo" :key="`e-${b.chave}`"
        class="rotulo-eixo"
        :x="b.centro" :y="ALTURA - 8" text-anchor="middle"
      >{{ quandoLegivel(b.quando) }}</text>

      <text
        v-for="b in rotulados" :key="`r-${b.chave}`"
        class="rotulo-valor" :class="{ minima: b.eMinimo }"
        :x="b.centro" :y="b.y - 5" text-anchor="middle"
      >{{ curto(b.centavos) }}</text>
    </svg>

    <div class="legenda">
      <span class="item"><i class="amostra barra"></i>Preço do período</span>
      <span v-if="media !== null" class="item">
        <i class="amostra linha"></i>Média 30 dias: {{ formatarBRL(media) }}
      </span>
      <span class="item"><i class="amostra minima"></i>Menor preço</span>
    </div>

  </div>
</template>

<style scoped>
.grafico { display: grid; gap: 10px; }
svg {
  width: 100%; height: auto; display: block;
  background: var(--suave);
  border-radius: 16px;
}
.barra { fill: var(--barra); }
.barra:hover { filter: brightness(0.92); }
.barra.minima { fill: var(--critico); }
.barra.maxima { fill: var(--tinta-fraca); }

.linha-media {
  stroke: var(--tinta); stroke-width: 1.5; stroke-dasharray: 6 4;
  vector-effect: non-scaling-stroke;
  opacity: 0.75;
}

.rotulo-valor {
  font-size: 11px; font-weight: 600; fill: var(--tinta-2);
}
.rotulo-valor.minima { fill: var(--critico); }

.rotulo-eixo { font-size: 10px; fill: var(--tinta-fraca); }

.legenda {
  display: flex; flex-wrap: wrap; gap: 16px;
  font-size: 12px; color: var(--tinta-2);
}
.legenda .item { display: inline-flex; align-items: center; gap: 6px; }
.amostra { width: 12px; height: 10px; border-radius: 3px; display: inline-block; }
.amostra.barra { background: var(--barra); }
.amostra.minima { background: var(--critico); }
.amostra.linha {
  height: 0; border-top: 2px dashed var(--tinta); border-radius: 0; opacity: 0.75;
}

</style>
