<script setup>
// Flutuação de 30 dias em barras, como no desenho. Uma barra por dia com
// leitura; a barra do MENOR preço ganha o destaque vermelho — é a informação
// acionável ("quanto já esteve mais barato").
//
// O valor exato de cada dia está no title da barra e na tabela equivalente
// (AnaliseDetalhada) — a regra de "nunca só a cor" vale para gráfico também.
import { computed } from "vue";
import { formatarBRL } from "../dinheiro.js";

const props = defineProps({
  serie: { type: Array, required: true },   // [{chave, quando, centavos}]
});

const menor = computed(() =>
  props.serie.length ? Math.min(...props.serie.map((p) => p.centavos)) : null);
const maior = computed(() =>
  props.serie.length ? Math.max(...props.serie.map((p) => p.centavos)) : null);

function altura(ponto) {
  if (menor.value === null || maior.value === menor.value) return 60;
  return 16 + (84 * (ponto.centavos - menor.value)) / (maior.value - menor.value);
}

function titulo(ponto) {
  const dia = ponto.quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  return `${dia} — ${formatarBRL(ponto.centavos)}`;
}

const rotuloInicio = computed(() =>
  props.serie.length
    ? props.serie[0].quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })
    : "");
</script>

<template>
  <div>
    <div class="palco" role="img"
         :aria-label="`Flutuação de preço em ${serie.length} dias; menor ${formatarBRL(menor)}`">
      <div
        v-for="ponto in serie"
        :key="ponto.chave"
        class="barra"
        :class="{ minima: ponto.centavos === menor }"
        :style="{ height: altura(ponto) + '%' }"
        :title="titulo(ponto)"
      ></div>
    </div>
    <div class="eixo dica">
      <span>{{ rotuloInicio }}</span>
      <span>hoje</span>
    </div>
  </div>
</template>

<style scoped>
.palco {
  height: 170px;
  background: var(--suave);
  border-radius: 16px;
  padding: 14px;
  display: flex; align-items: flex-end; gap: 5px;
}
.barra {
  flex: 1 1 0;
  min-width: 4px;
  background: var(--barra);
  border-radius: 6px 6px 3px 3px;
  transition: height 200ms ease;
}
.barra:hover { filter: brightness(0.92); }
.barra.minima { background: var(--critico); }
.eixo {
  display: flex; justify-content: space-between;
  padding: 6px 4px 0;
}
</style>
