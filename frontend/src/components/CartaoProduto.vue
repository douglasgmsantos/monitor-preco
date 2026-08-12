<script setup>
import { computed, ref, watch } from "vue";
import { formatarBRL, variacaoPct } from "../dinheiro.js";
import { haQuantoTempo } from "../tempo.js";
import { useAuth } from "../composables/useAuth.js";
import { menorPrecoAtual, ultimaVerificacao, fontesComProblema } from "../composables/useProdutos.js";
import { useCatalogo } from "../composables/useCatalogo.js";
import { resumo30d } from "../composables/useHistorico.js";
import SeloProduto from "./SeloProduto.vue";

const props = defineProps({
  produto: { type: Object, required: true },
  selecionado: { type: Boolean, default: false },
});
defineEmits(["selecionar", "ver-detalhes"]);

const { usuario } = useAuth();
const { imagemPorUrl, carregado } = useCatalogo();

const atual = computed(() => menorPrecoAtual(props.produto));
const verificado = computed(() => haQuantoTempo(ultimaVerificacao(props.produto)));
const problemas = computed(() => fontesComProblema(props.produto));
const ativas = computed(() =>
  props.produto.fontes.filter((f) => f.status === "ok" && !f.comErro).length);
const pausado = computed(() => props.produto.dados.ativo === false);

// Produto não guarda imagem (as rules não têm esse campo); quando uma fonte
// aponta para um item da vitrine, a imagem do catálogo vem de graça.
const imagem = computed(() => {
  if (!carregado.value) return null;
  return imagemPorUrl(props.produto.fontes.map((f) => f.url));
});

// Média e menor preço de 30 dias, do rollup diário. Assíncrono e cacheado.
const resumo = ref(null);
watch(
  () => [props.produto.id, props.produto.fontes.map((f) => f.id).join(",")],
  async () => {
    resumo.value = null;
    if (!usuario.value || !props.produto.fontes.length) return;
    try {
      resumo.value = await resumo30d(
        usuario.value.uid, props.produto.id, props.produto.fontes);
    } catch (erro) {
      console.error("falha ao carregar o resumo de 30 dias", erro);
    }
  },
  { immediate: true },
);

const variacao = computed(() =>
  variacaoPct(atual.value, resumo.value ? resumo.value.media : null));
</script>

<template>
  <article
    class="cartao produto"
    :class="{ pausado, selecionado }"
    @click="$emit('selecionar')"
  >
    <header class="cabeca">
      <div class="thumb">
        <img v-if="imagem" :src="imagem" alt="" loading="lazy">
        <span v-else aria-hidden="true">{{ (produto.dados.nome || "?").slice(0, 1).toUpperCase() }}</span>
      </div>
      <div class="cabeca-texto">
        <SeloProduto :produto="produto" />
        <h3 class="nome" :title="produto.dados.nome">{{ produto.dados.nome }}</h3>
        <p class="dica verificado">
          {{ verificado ? `Verificado ${verificado}` : "Ainda não verificado" }}
        </p>
      </div>
    </header>

    <div class="divisor"></div>

    <div class="estatisticas">
      <div class="estat">
        <span class="rotulo">Atual</span>
        <span class="valor mono" :class="{ destaque: variacao !== null && variacao < 0 }">
          {{ formatarBRL(atual) }}
        </span>
        <span v-if="variacao !== null" class="sub" :class="{ destaque: variacao < 0 }">
          {{ variacao > 0 ? "+" : "" }}{{ variacao }}% vs média
        </span>
      </div>
      <div class="estat">
        <span class="rotulo">Média 30 dias</span>
        <span class="valor mono">{{ formatarBRL(resumo && resumo.media) }}</span>
      </div>
      <div class="estat">
        <span class="rotulo">Menor preço</span>
        <span class="valor mono menor">{{ formatarBRL(resumo && resumo.menor) }}</span>
        <span v-if="resumo && resumo.menor !== null" class="sub">em 30 dias</span>
      </div>
    </div>

    <footer class="faixa">
      <span class="situacao">
        <span class="ponto" :class="problemas ? 'atencao' : (ativas ? 'bom' : 'fraco')"></span>
        {{ problemas
          ? `${problemas} fonte${problemas > 1 ? "s" : ""} com erro`
          : `${ativas} fonte${ativas === 1 ? "" : "s"} ativa${ativas === 1 ? "" : "s"}` }}
      </span>
      <button class="ver" @click.stop="$emit('ver-detalhes')">Ver detalhes</button>
    </footer>
  </article>
</template>

<style scoped>
.produto {
  padding: 22px;
  display: flex; flex-direction: column; gap: 18px;
  cursor: pointer;
  min-width: 0;
}
.produto.selecionado { border-color: var(--tinta); }
.produto.pausado { opacity: 0.6; }   /* visível e com histórico intacto — só não é coletado */

.cabeca { display: flex; gap: 16px; align-items: flex-start; }
.thumb {
  width: 84px; height: 84px; flex: none;
  border-radius: 16px; background: var(--suave);
  display: grid; place-items: center; overflow: hidden;
  font-size: 30px; font-weight: 700; color: var(--tinta-fraca);
}
.thumb img { width: 100%; height: 100%; object-fit: contain; }
.cabeca-texto { min-width: 0; display: grid; gap: 6px; justify-items: start; }
.nome {
  margin: 0; font-size: 19px; font-weight: 650; line-height: 1.25;
  letter-spacing: -0.01em;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;   /* 2 linhas: cortar o nome no meio esconde o modelo */
}
.verificado { margin: 0; }

.divisor { border-top: 1px solid var(--borda); }

.estatisticas {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
}
.estat { display: grid; gap: 3px; align-content: start; }
.rotulo {
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--tinta-fraca);
}
.valor { font-size: 21px; font-weight: 600; letter-spacing: -0.01em; }
.valor.destaque { color: var(--critico); }
.valor.menor { font-style: italic; }
.sub { font-size: 12px; color: var(--tinta-fraca); }
.sub.destaque { color: var(--critico); }

.faixa {
  margin-top: auto;
  background: var(--suave); border-radius: 12px;
  padding: 10px 14px;
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  font-size: 13px; color: var(--tinta-2);
}
.situacao { display: inline-flex; align-items: center; gap: 8px; }
.ver {
  border: none; background: none; padding: 2px 4px;
  font-weight: 650; font-size: 13px; color: var(--tinta);
  text-decoration: underline; text-underline-offset: 3px;
}
.ver:hover { background: none; opacity: 0.7; }

@media (max-width: 480px) {
  .estatisticas { grid-template-columns: 1fr 1fr; }
  .valor { font-size: 18px; }
}
</style>
