<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { formatarBRL, variacaoPct } from "../dinheiro.js";
import { haQuantoTempo } from "../tempo.js";
import { useAuth } from "../composables/useAuth.js";
import {
  menorPrecoAtual, ultimaVerificacao, fontesComProblema, useProdutos,
} from "../composables/useProdutos.js";
import { useCatalogo } from "../composables/useCatalogo.js";
import { resumo30d } from "../composables/useHistorico.js";
import SeloProduto from "./SeloProduto.vue";

const props = defineProps({
  produto: { type: Object, required: true },
  selecionado: { type: Boolean, default: false },
});
const emit = defineEmits(["selecionar", "ver-detalhes", "editar"]);

const { usuario } = useAuth();
const { imagemPorUrl, carregado } = useCatalogo();
const { alternarAtivo, excluirProduto } = useProdutos();

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

// ---------------------------------------------------------------------------
// Menu de ações
//
// Num menu, e não como três botões soltos: `excluir` apaga TODO o histórico e
// não tem desfazer. Botão de destruição ao lado de um de uso diário é convite a
// clique errado — o menu obriga um gesto a mais justamente onde precisa.
// ---------------------------------------------------------------------------

const menuAberto = ref(false);

function fecharAoClicarFora(evento) {
  if (!evento.target.closest(".menu-acoes")) menuAberto.value = false;
}

function alternarMenu() {
  menuAberto.value = !menuAberto.value;
  if (menuAberto.value) {
    document.addEventListener("click", fecharAoClicarFora);
  } else {
    document.removeEventListener("click", fecharAoClicarFora);
  }
}
onUnmounted(() => document.removeEventListener("click", fecharAoClicarFora));

async function pausarOuRetomar() {
  menuAberto.value = false;
  try {
    await alternarAtivo(props.produto.id, !pausado.value);
  } catch (erro) {
    console.error("falha ao pausar/retomar", erro);
  }
}

async function excluir() {
  menuAberto.value = false;
  const quantas = props.produto.fontes.length;
  const confirmado = confirm(
    `Excluir “${props.produto.dados.nome}”?\n\n` +
    `Isso apaga ${quantas} fonte(s) e TODO o histórico de preços do produto. ` +
    `Não há como desfazer.\n\n` +
    `Para só parar de coletar sem perder o histórico, use “pausar”.`
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

      <div class="menu-acoes">
        <button
          class="gatilho" aria-label="Ações do produto" aria-haspopup="menu"
          :aria-expanded="String(menuAberto)"
          @click.stop="alternarMenu"
        >⋯</button>
        <div v-if="menuAberto" class="menu" role="menu" @click.stop>
          <button role="menuitem" @click="menuAberto = false; emit('editar', produto.id)">
            ✎ Editar
          </button>
          <button role="menuitem" @click="pausarOuRetomar">
            {{ pausado ? "▶ Retomar coleta" : "⏸ Pausar coleta" }}
          </button>
          <button role="menuitem" class="perigo" @click="excluir">
            🗑 Excluir
          </button>
        </div>
      </div>
    </header>

    <div class="divisor"></div>

    <div class="estatisticas">
      <div class="estat destaque-atual">
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
  padding: 16px;
  display: flex; flex-direction: column; gap: 14px;
  cursor: pointer;
  min-width: 0;
}
.produto.selecionado { border-color: var(--tinta); }
.produto.pausado { opacity: 0.6; }   /* visível e com histórico intacto — só não é coletado */

.cabeca { display: flex; gap: 16px; align-items: flex-start; }

/* Menu no canto superior direito. `position: relative` no pai para o painel
   ancorar nele, e z-index acima das barras do gráfico do cartão vizinho. */
.menu-acoes { position: relative; flex: none; margin-left: auto; }
.gatilho {
  border: none; background: none; padding: 4px 8px; border-radius: 8px;
  font-size: 18px; line-height: 1; color: var(--tinta-2);
}
.gatilho:hover { background: var(--suave); color: var(--tinta); }
.menu {
  position: absolute; top: 100%; right: 0; z-index: 20;
  min-width: 190px; padding: 6px;
  background: var(--superficie);
  border: 1px solid var(--borda); border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  display: grid; gap: 2px;
}
.menu button {
  border: none; background: none; border-radius: 8px;
  padding: 9px 12px; text-align: left; font-size: 13.5px;
  color: var(--tinta);
}
.menu button:hover { background: var(--suave); }
.menu button.perigo { color: var(--critico); }
.menu button.perigo:hover { background: var(--critico-fundo); }
.thumb {
  width: 84px; height: 84px; flex: none;
  border-radius: 16px; background: var(--suave);
  display: grid; place-items: center; overflow: hidden;
  font-size: 30px; font-weight: 700; color: var(--tinta-fraca);
}
.thumb img { width: 100%; height: 100%; object-fit: contain; }
.cabeca-texto { min-width: 0; display: grid; gap: 6px; justify-items: start; }
.nome {
  margin: 0; font-size: 15px; font-weight: 650; line-height: 1.3;
  letter-spacing: -0.01em;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;   /* 2 linhas: cortar o nome no meio esconde o modelo */
}
.verificado { margin: 0; }

.divisor { border-top: 1px solid var(--borda); }

/* "Atual" ocupa a linha inteira e as outras duas dividem a de baixo.
   Três colunas num cartão de ~250px dariam 80px cada, e "R$ 4.899,99" não cabe
   — o número quebraria no meio. Nenhuma informação some: só muda o arranjo. */
.estatisticas {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px;
}
.estat { display: grid; gap: 2px; align-content: start; min-width: 0; }
.estat.destaque-atual { grid-column: 1 / -1; }
.rotulo {
  font-size: 10px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--tinta-fraca);
}
.valor {
  font-size: 15px; font-weight: 600; letter-spacing: -0.01em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.destaque-atual .valor { font-size: 24px; }
.valor.destaque { color: var(--critico); }
.valor.menor { font-style: italic; }
.sub { font-size: 11px; color: var(--tinta-fraca); }
.sub.destaque { color: var(--critico); }

.faixa {
  margin-top: auto;
  background: var(--suave); border-radius: 10px;
  padding: 8px 10px;
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  font-size: 11.5px; color: var(--tinta-2);
}
.situacao { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.situacao { display: inline-flex; align-items: center; gap: 8px; }
.ver {
  border: none; background: none; padding: 2px 4px; flex: none;
  font-weight: 650; font-size: 11.5px; color: var(--tinta);
  text-decoration: underline; text-underline-offset: 3px;
}
.ver:hover { background: none; opacity: 0.7; }

/* Numa coluna só o cartão volta a ter espaço: aproveita para respirar. */
@media (max-width: 560px) {
  .produto { padding: 20px; }
  .thumb { width: 64px; height: 64px; font-size: 24px; }
  .nome { font-size: 17px; }
  .destaque-atual .valor { font-size: 26px; }
}
</style>
