<script setup>
import { computed, ref, watch } from "vue";
import { formatarBRL } from "../dinheiro.js";
import { useAuth } from "../composables/useAuth.js";
import { useProdutos } from "../composables/useProdutos.js";
import {
  PERIODOS, PERIODO_PADRAO, resumo30d, serieDoPeriodo,
} from "../composables/useHistorico.js";
import LinhaFonte from "./LinhaFonte.vue";
import GraficoBarras from "./GraficoBarras.vue";

const props = defineProps({
  produto: { type: Object, required: true },
});
const emit = defineEmits(["editar"]);

const { usuario } = useAuth();
const { alternarAtivo, retentarFonte, apagarFonteComHistorico, excluirProduto } = useProdutos();

const resumo = ref(null);          // série do período escolhido, para o gráfico
const media30d = ref(null);        // SEMPRE 30 dias — é a referência do alerta
const comoTabela = ref(false);
const periodo = ref(PERIODO_PADRAO);
const carregandoSerie = ref(false);

const tituloDoPeriodo = computed(() =>
  (PERIODOS.find((p) => p.id === periodo.value) || {}).titulo || "Flutuação");

async function carregar() {
  if (!usuario.value || !props.produto.fontes.length) {
    resumo.value = null;
    media30d.value = null;
    return;
  }
  carregandoSerie.value = true;
  const pedido = periodo.value;
  try {
    const [serie, mensal] = await Promise.all([
      serieDoPeriodo(usuario.value.uid, props.produto.id, props.produto.fontes, pedido),
      resumo30d(usuario.value.uid, props.produto.id, props.produto.fontes),
    ]);
    // Troca de período durante a leitura: descarta o resultado velho em vez de
    // deixá-lo sobrescrever o que o usuário pediu depois.
    if (pedido !== periodo.value) return;
    resumo.value = serie;
    media30d.value = mensal.media;
  } catch (erro) {
    console.error("falha ao carregar a flutuação", erro);
  } finally {
    if (pedido === periodo.value) carregandoSerie.value = false;
  }
}

watch(
  () => [
    props.produto.id,
    props.produto.fontes.map((f) => f.id).join(","),
    periodo.value,
  ],
  async () => {
    resumo.value = null;
    await carregar();
  },
  { immediate: true },
);

const pausado = computed(() => props.produto.dados.ativo === false);

async function excluir() {
  const quantas = props.produto.fontes.length;
  const confirmado = confirm(
    `Excluir “${props.produto.dados.nome}”?\n\n` +
    `Isso apaga ${quantas} fonte(s) e TODO o histórico de preços do produto. ` +
    `Não há como desfazer.\n\n` +
    `Para só parar de coletar sem perder o histórico, use “pausar coleta”.`
  );
  if (!confirmado) return;
  try {
    await excluirProduto(props.produto.id);
  } catch (erro) {
    console.error("falha ao excluir o produto", erro);
    alert(`Não foi possível excluir: ${erro.message || erro}`);
  }
}
</script>

<template>
  <section id="analise" class="analise">
    <p class="olho">Análise detalhada</p>
    <h2 class="titulo-secao">Histórico de fontes: {{ produto.dados.nome }}</h2>

    <div class="fontes">
      <LinhaFonte
        v-for="fonte in produto.fontes"
        :key="fonte.id"
        :fonte="fonte"
        @retentar="retentarFonte(produto.id, fonte.id)"
        @remover="apagarFonteComHistorico(produto.id, fonte.id)"
      />
      <p v-if="!produto.fontes.length" class="vazio">Este produto está sem fontes.</p>
    </div>

    <div class="acoes-produto">
      <button class="botao-discreto" @click="emit('editar', produto.id)">✎ editar produto</button>
      <button class="botao-discreto" @click="alternarAtivo(produto.id, !pausado)">
        {{ pausado ? "▶ retomar coleta" : "⏸ pausar coleta" }}
      </button>
      <button class="botao-discreto perigo" @click="excluir">🗑 excluir</button>
    </div>

    <div class="flutuacao">
      <div class="cabeca-flutuacao">
        <p class="olho">{{ tituloDoPeriodo }}</p>
        <span class="mono media" v-if="media30d !== null">
          Média 30 dias: {{ formatarBRL(media30d) }}
        </span>
        <button
          v-if="resumo && resumo.serie.length"
          class="botao-discreto"
          :aria-pressed="String(comoTabela)"
          @click="comoTabela = !comoTabela"
        >{{ comoTabela ? "Ver como barras" : "Ver como tabela" }}</button>
      </div>

      <div class="periodos" role="group" aria-label="Período do gráfico">
        <button
          v-for="p in PERIODOS"
          :key="p.id"
          :aria-pressed="String(periodo === p.id)"
          @click="periodo = p.id"
        >{{ p.rotulo }}</button>
      </div>

      <template v-if="resumo && resumo.serie.length">
        <GraficoBarras v-if="!comoTabela" :serie="resumo.serie" :periodo="periodo" />
        <div v-else class="rolagem">
          <table>
            <thead>
              <tr>
                <th>Quando</th>
                <th class="num">{{ periodo === "dia" ? "Menor preço lido" : "Menor preço do dia" }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ponto in resumo.serie" :key="ponto.chave">
                <td>
                  {{ periodo === "dia"
                    ? ponto.quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
                    : ponto.quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) }}
                </td>
                <td class="num">{{ formatarBRL(ponto.centavos) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <p v-else-if="carregandoSerie" class="vazio">Carregando…</p>
      <p v-else class="vazio">
        <template v-if="periodo === 'dia'">
          Sem leituras nas últimas 24 horas. O coletor roda a cada 3 horas —
          experimente um período maior.
        </template>
        <template v-else>
          Sem leituras neste período. A série começa quando o coletor confirma a
          primeira fonte — em até 15 minutos após o cadastro.
        </template>
      </p>
    </div>
  </section>
</template>

<style scoped>
.analise { margin-top: 30px; scroll-margin-top: 80px; }
.fontes { display: grid; gap: 10px; }
.acoes-produto { display: flex; gap: 6px; flex-wrap: wrap; margin: 14px 0 0; }
.acoes-produto button { font-size: 13px; }

.flutuacao { margin-top: 28px; max-width: 880px; }
.cabeca-flutuacao {
  display: flex; align-items: baseline; gap: 16px; margin-bottom: 12px;
  flex-wrap: wrap;
}
.cabeca-flutuacao .olho { margin: 0; flex: 1; }
.media { font-size: 14px; color: var(--tinta-2); }
.rolagem { overflow-x: auto; max-height: 340px; overflow-y: auto; }

/* Grupo segmentado: os quatro períodos são exclusivos entre si, e ficam ACIMA
   do gráfico que eles escopam — mesma regra dos filtros nas outras telas. */
.periodos {
  display: inline-flex; margin-bottom: 14px;
  border: 1px solid var(--borda); border-radius: 12px; overflow: hidden;
}
.periodos button {
  border: none; border-radius: 0; padding: 7px 15px;
  font-size: 13px; background: var(--superficie);
}
.periodos button + button { border-left: 1px solid var(--borda); }
.periodos button:hover { background: var(--suave); }
.periodos button[aria-pressed="true"] {
  background: var(--primario); color: var(--primario-texto); font-weight: 600;
}
</style>
