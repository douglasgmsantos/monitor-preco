<script setup>
// Detalhe do produto: fontes com preço, flutuação e ações.
//
// Antes isto era uma seção fixa embaixo da lista (`AnaliseDetalhada`), e tinha
// dois problemas: ocupava a tela de quem só queria conferir preços, e ficava
// longe do cartão que a selecionava — clicar num produto mudava um gráfico que
// podia estar fora da vista. Como modal, o detalhe aparece onde a atenção já
// está e some quando não interessa.
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { formatarBRL, variacaoPct } from "../dinheiro.js";
import { haQuantoTempo } from "../tempo.js";
import { useAuth } from "../composables/useAuth.js";
import {
  fonteMaisBarata, menorPrecoAtual, ultimaVerificacao, useProdutos,
} from "../composables/useProdutos.js";
import {
  PERIODOS, PERIODO_PADRAO, resumo30d, serieDoPeriodo,
} from "../composables/useHistorico.js";
import LinhaFonte from "./LinhaFonte.vue";
import GraficoCombinado from "./GraficoCombinado.vue";
import SeloProduto from "./SeloProduto.vue";

const props = defineProps({
  produto: { type: Object, required: true },
});
const emit = defineEmits(["fechar", "editar"]);

const { usuario } = useAuth();
const { retentarFonte, apagarFonteComHistorico } = useProdutos();

const resumo = ref(null);        // série do período escolhido
const media30d = ref(null);      // SEMPRE 30 dias — é a referência do alerta
const periodo = ref(PERIODO_PADRAO);
const carregando = ref(false);
const comoTabela = ref(false);

const atual = computed(() => menorPrecoAtual(props.produto));
const verificado = computed(() => haQuantoTempo(ultimaVerificacao(props.produto)));
const variacao = computed(() => variacaoPct(atual.value, media30d.value));
const idMaisBarata = computed(() => fonteMaisBarata(props.produto));

/** Fontes com a mais barata no topo. Ela é a resposta que o usuário veio
 *  buscar; deixá-la no meio da lista obriga a comparar preço a preço. */
const fontesOrdenadas = computed(() => {
  const vale = (f) =>
    f.status === "ok" && !f.comErro && typeof f.ultimoPrecoCentavos === "number";
  return [...props.produto.fontes].sort((a, b) => {
    if (vale(a) && vale(b)) return a.ultimoPrecoCentavos - b.ultimoPrecoCentavos;
    // Sem preço vai para o fim: ordená-la junto exigiria inventar um valor.
    if (vale(a)) return -1;
    if (vale(b)) return 1;
    return 0;
  });
});

const tituloDoPeriodo = computed(() =>
  (PERIODOS.find((p) => p.id === periodo.value) || {}).titulo || "Flutuação");

async function carregar() {
  if (!usuario.value || !props.produto.fontes.length) {
    resumo.value = null;
    media30d.value = null;
    return;
  }
  carregando.value = true;
  const pedido = periodo.value;
  try {
    const [serie, mensal] = await Promise.all([
      serieDoPeriodo(usuario.value.uid, props.produto.id, props.produto.fontes, pedido),
      resumo30d(usuario.value.uid, props.produto.id, props.produto.fontes),
    ]);
    // Troca de período no meio da leitura: descarta o resultado velho em vez de
    // deixá-lo sobrescrever o que o usuário pediu depois.
    if (pedido !== periodo.value) return;
    resumo.value = serie;
    media30d.value = mensal.media;
  } catch (erro) {
    console.error("falha ao carregar a flutuação", erro);
  } finally {
    if (pedido === periodo.value) carregando.value = false;
  }
}

watch(
  () => [props.produto.id, props.produto.fontes.map((f) => f.id).join(","), periodo.value],
  async () => { resumo.value = null; await carregar(); },
  { immediate: true },
);

function aoTeclar(evento) {
  if (evento.key === "Escape") emit("fechar");
}
onMounted(() => document.addEventListener("keydown", aoTeclar));
onUnmounted(() => document.removeEventListener("keydown", aoTeclar));
</script>

<template>
  <div class="veu" @click.self="emit('fechar')">
    <div class="janela" role="dialog" aria-modal="true"
         :aria-label="`Detalhes de ${produto.dados.nome}`">
      <header class="topo">
        <div class="titulo-bloco">
          <SeloProduto :produto="produto" />
          <h2 class="titulo">{{ produto.dados.nome }}</h2>
          <p class="dica">
            {{ verificado ? `Verificado ${verificado}` : "Ainda não verificado" }}
          </p>
        </div>
        <button class="fechar" aria-label="Fechar" @click="emit('fechar')">✕</button>
      </header>

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
          <span class="rotulo">{{ produto.dados.valorMinCentavos ? "Faixa aceita" : "Alerta em" }}</span>
          <span class="valor mono faixa">
            <template v-if="produto.dados.valorMinCentavos">
              {{ formatarBRL(produto.dados.valorMinCentavos) }}
              <span class="ate">até</span>
            </template>
            {{ formatarBRL(produto.dados.valorMaxCentavos) }}
          </span>
          <span class="sub">
            {{ produto.dados.valorMinCentavos
              ? "o máximo é o que dispara o alerta"
              : "avisa em até este valor" }}
          </span>
        </div>
        <div class="estat">
          <span class="rotulo">Média 30 dias</span>
          <span class="valor mono">{{ formatarBRL(media30d) }}</span>
        </div>
      </div>

      <!-- Fontes -->
      <section class="bloco">
        <p class="olho">Fontes</p>
        <div class="fontes">
          <LinhaFonte
            v-for="fonte in fontesOrdenadas"
            :key="fonte.id"
            :fonte="fonte"
            :mais-barata="produto.fontes.length > 1 && fonte.id === idMaisBarata"
            @retentar="retentarFonte(produto.id, fonte.id)"
            @remover="apagarFonteComHistorico(produto.id, fonte.id)"
          />
          <p v-if="!produto.fontes.length" class="vazio">Este produto está sem fontes.</p>
        </div>
      </section>

      <!-- Flutuação -->
      <section class="bloco">
        <div class="cabeca-flutuacao">
          <p class="olho">{{ tituloDoPeriodo }}</p>
          <button
            v-if="resumo && resumo.serie.length"
            class="botao-discreto"
            :aria-pressed="String(comoTabela)"
            @click="comoTabela = !comoTabela"
          >{{ comoTabela ? "Ver como gráfico" : "Ver como tabela" }}</button>
        </div>

        <div class="periodos" role="group" aria-label="Período do gráfico">
          <button
            v-for="p in PERIODOS" :key="p.id"
            :aria-pressed="String(periodo === p.id)"
            @click="periodo = p.id"
          >{{ p.rotulo }}</button>
        </div>

        <template v-if="resumo && resumo.serie.length">
          <GraficoCombinado
            v-if="!comoTabela"
            :serie="resumo.serie" :media="media30d" :periodo="periodo"
          />
          <div v-else class="rolagem">
            <table>
              <thead>
                <tr>
                  <th>Quando</th>
                  <th class="num">{{ periodo === "dia" ? "Menor preço lido" : "Menor preço do dia" }}</th>
                  <th class="num">vs média</th>
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
                  <td class="num">
                    <template v-if="media30d">
                      {{ variacaoPct(ponto.centavos, media30d) > 0 ? "+" : ""
                      }}{{ variacaoPct(ponto.centavos, media30d) }}%
                    </template>
                    <template v-else>—</template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <p v-else-if="carregando" class="vazio">Carregando…</p>
        <p v-else class="vazio">
          <template v-if="periodo === 'dia'">
            Sem leituras nas últimas 24 horas. O coletor roda a cada 3 horas —
            experimente um período maior.
          </template>
          <template v-else>
            Sem leituras neste período. A série começa quando o coletor confirma
            a primeira fonte — em até 15 minutos após o cadastro.
          </template>
        </p>
      </section>

      <footer class="acoes">
        <button class="botao-discreto" @click="emit('editar', produto.id)">
          ✎ editar produto
        </button>
        <button class="botao-primario" @click="emit('fechar')">Fechar</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.veu {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(10, 10, 10, 0.45);
  backdrop-filter: blur(6px);
  display: grid; place-items: center;
  padding: 20px;
  overflow-y: auto;
}
.janela {
  width: 100%; max-width: 760px;
  background: var(--superficie);
  border-radius: 20px;
  padding: 28px 30px;
  display: grid; gap: 20px;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
}

.topo { display: flex; align-items: flex-start; gap: 16px; }
.titulo-bloco { display: grid; gap: 6px; justify-items: start; flex: 1; min-width: 0; }
.titulo {
  margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.01em;
  line-height: 1.25;
}
.fechar {
  border: none; background: none; font-size: 16px; color: var(--tinta-2);
  padding: 4px 8px; border-radius: 8px; flex: none;
}
.fechar:hover { background: var(--suave); color: var(--tinta); }

.estatisticas {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
  padding: 16px; background: var(--suave); border-radius: 14px;
}
.estat { display: grid; gap: 3px; align-content: start; min-width: 0; }
.rotulo {
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--tinta-fraca);
}
.valor { font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
.valor.destaque { color: var(--critico); }
.valor.faixa { font-size: 15px; line-height: 1.35; }
.faixa .ate { color: var(--tinta-fraca); font-weight: 400; font-size: 12px; }
.sub { font-size: 12px; color: var(--tinta-fraca); }
.sub.destaque { color: var(--critico); }

.bloco { display: grid; gap: 12px; }
.fontes { display: grid; gap: 10px; }

.cabeca-flutuacao {
  display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
}
.cabeca-flutuacao .olho { margin: 0; flex: 1; }

/* Grupo segmentado: os períodos são exclusivos e ficam ACIMA do gráfico que
   eles escopam — mesma regra dos filtros nas outras telas. */
.periodos {
  display: inline-flex; justify-self: start;
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

.rolagem { overflow-x: auto; max-height: 340px; overflow-y: auto; }

.acoes {
  display: flex; gap: 10px; justify-content: flex-end; align-items: center;
  border-top: 1px solid var(--borda); padding-top: 16px;
}

@media (max-width: 620px) {
  .janela { padding: 22px 18px; }
  .estatisticas { grid-template-columns: 1fr; }
}
</style>
