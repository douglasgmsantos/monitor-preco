<script setup>
import { computed, ref, watch } from "vue";
import { formatarBRL } from "../dinheiro.js";
import { useAuth } from "../composables/useAuth.js";
import { useProdutos } from "../composables/useProdutos.js";
import { resumo30d } from "../composables/useHistorico.js";
import LinhaFonte from "./LinhaFonte.vue";
import GraficoBarras from "./GraficoBarras.vue";

const props = defineProps({
  produto: { type: Object, required: true },
});
const emit = defineEmits(["editar"]);

const { usuario } = useAuth();
const { alternarAtivo, retentarFonte, apagarFonteComHistorico, excluirProduto } = useProdutos();

const resumo = ref(null);
const comoTabela = ref(false);

watch(
  () => [props.produto.id, props.produto.fontes.map((f) => f.id).join(",")],
  async () => {
    resumo.value = null;
    if (!usuario.value || !props.produto.fontes.length) return;
    try {
      resumo.value = await resumo30d(
        usuario.value.uid, props.produto.id, props.produto.fontes);
    } catch (erro) {
      console.error("falha ao carregar a flutuação", erro);
    }
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
        <p class="olho">Flutuação de 30 dias</p>
        <span class="mono media" v-if="resumo && resumo.media !== null">
          Média 30 dias: {{ formatarBRL(resumo.media) }}
        </span>
        <button
          v-if="resumo && resumo.serie.length"
          class="botao-discreto"
          :aria-pressed="String(comoTabela)"
          @click="comoTabela = !comoTabela"
        >{{ comoTabela ? "Ver como barras" : "Ver como tabela" }}</button>
      </div>

      <template v-if="resumo && resumo.serie.length">
        <GraficoBarras v-if="!comoTabela" :serie="resumo.serie" />
        <div v-else class="rolagem">
          <table>
            <thead><tr><th>Quando</th><th class="num">Menor preço do dia</th></tr></thead>
            <tbody>
              <tr v-for="ponto in resumo.serie" :key="ponto.chave">
                <td>{{ ponto.quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) }}</td>
                <td class="num">{{ formatarBRL(ponto.centavos) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <p v-else class="vazio">
        Sem leituras nos últimos 30 dias. A série começa quando o coletor
        confirma a primeira fonte — em até 15 minutos após o cadastro.
      </p>
    </div>
  </section>
</template>

<style scoped>
.analise { margin-top: 56px; scroll-margin-top: 80px; }
.fontes { display: grid; gap: 10px; max-width: 880px; }
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
</style>
