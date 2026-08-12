<script setup>
import { computed, ref } from "vue";
import { formatarBRL } from "../dinheiro.js";
import { nomeDaLojaPorHost, hostDaUrl } from "../lojas.js";
import { useProdutos } from "../composables/useProdutos.js";
import { useCatalogo } from "../composables/useCatalogo.js";
import CartaoDescoberta from "./CartaoDescoberta.vue";
import CartaoProduto from "./CartaoProduto.vue";
import AnaliseDetalhada from "./AnaliseDetalhada.vue";

const props = defineProps({
  selecionadoId: { type: String, default: null },
});
const emit = defineEmits([
  "selecionar", "ver-detalhes", "editar", "acompanhar", "novo-produto", "ir-catalogo",
]);

const { produtos, carregando } = useProdutos();
const { catalogo, carregado } = useCatalogo();

const selecionado = computed(() =>
  produtos.value.find((p) => p.id === props.selecionadoId) || null);

/** URLs que o usuário já acompanha, para não oferecer duas vezes. */
const urlsAcompanhadas = computed(() => {
  const urls = new Set();
  for (const produto of produtos.value) {
    for (const fonte of produto.fontes) urls.add(fonte.url);
  }
  return urls;
});

// A faixa de descoberta: 3 itens do catálogo ainda não acompanhados, os mais
// baratos com preço e disponíveis. Sem dado de popularidade, barato é o
// critério honesto que existe.
const sugestoes = computed(() =>
  catalogo.value
    .filter((i) => i.preco !== null && i.disponivel !== false)
    .filter((i) => !urlsAcompanhadas.value.has(i.url))
    .sort((a, b) => a.preco - b.preco)
    .slice(0, 3));

// ---------------------------------------------------------------------------
// Busca e paginação do radar
//
// Mesmo desenho do catálogo (`VisaoCatalogo.vue`), de propósito: as duas listas
// se parecem, então filtrar tem de funcionar do mesmo jeito nas duas.
// ---------------------------------------------------------------------------

const POR_PAGINA = 4;
const busca = ref("");
const pagina = ref(1);

/** Busca por nome do produto E por loja.
 *
 *  A loja entra porque é a segunda pergunta natural de quem tem vários produtos
 *  ("o que eu sigo na Amazon?"), e a informação já está no cartão — filtrar por
 *  algo que está na tela é o que o usuário espera poder fazer. */
const filtrados = computed(() => {
  const texto = busca.value.trim().toLowerCase();
  if (!texto) return produtos.value;
  return produtos.value.filter((p) => {
    const nome = (p.dados.nome || "").toLowerCase();
    if (nome.includes(texto)) return true;
    return p.fontes.some((f) => (f.loja || "").toLowerCase().includes(texto));
  });
});

const paginas = computed(() => Math.max(1, Math.ceil(filtrados.value.length / POR_PAGINA)));

const visiveis = computed(() => {
  const atual = Math.min(Math.max(1, pagina.value), paginas.value);
  return filtrados.value.slice((atual - 1) * POR_PAGINA, atual * POR_PAGINA);
});

function aoFiltrar() { pagina.value = 1; }   // filtrar sempre volta ao começo

function irPara(direcao) {
  pagina.value = Math.min(Math.max(1, pagina.value + direcao), paginas.value);
}

function acompanharItem(item) {
  emit("acompanhar", {
    nome: item.nome,
    loja: nomeDaLojaPorHost(hostDaUrl(item.url)),
    url: item.url,
    alvoPlaceholder: item.preco !== null
      ? `abaixo de ${formatarBRL(item.preco).replace("R$", "").trim()}` : "",
  });
}
</script>

<template>
  <div>
    <!-- Descoberta -->
    <section v-if="sugestoes.length" class="descoberta">
      <p class="olho">Descoberta</p>
      <h2 class="titulo-secao">Sugestões do catálogo</h2>
      <div class="grade-descoberta">
        <CartaoDescoberta
          v-for="item in sugestoes"
          :key="item.sku"
          :item="item"
          @acompanhar="acompanharItem(item)"
        />
      </div>
    </section>

    <!-- Seu radar -->
    <section class="radar">
      <p class="olho">Seu radar</p>
      <h2 class="titulo-secao">Produtos em acompanhamento</h2>

      <div v-if="produtos.length" class="filtros">
        <input v-model="busca" class="busca" placeholder="filtrar por nome ou loja…"
               @input="aoFiltrar">
        <span class="dica">{{ filtrados.length }} de {{ produtos.length }}</span>
      </div>

      <div v-if="visiveis.length" class="grade-produtos">
        <CartaoProduto
          v-for="produto in visiveis"
          :key="produto.id"
          :produto="produto"
          :selecionado="produto.id === selecionadoId"
          @selecionar="emit('selecionar', produto.id)"
          @ver-detalhes="emit('ver-detalhes', produto.id)"
        />
      </div>

      <p v-else-if="produtos.length" class="vazio">
        Nenhum produto com esse filtro.
      </p>

      <div v-if="paginas > 1" class="paginacao">
        <button class="botao-discreto" :disabled="pagina <= 1" @click="irPara(-1)">‹ anterior</button>
        <span class="dica mono">{{ Math.min(pagina, paginas) }} / {{ paginas }}</span>
        <button class="botao-discreto" :disabled="pagina >= paginas" @click="irPara(1)">próxima ›</button>
      </div>

      <div v-if="!produtos.length && !carregando" class="vazio">
        <p>Nenhum produto no radar ainda.</p>
        <p>
          <button class="botao-primario" @click="emit('novo-produto')">+ Novo produto</button>
          <button v-if="carregado && catalogo.length" class="botao-discreto"
                  @click="emit('ir-catalogo')">ou explore o catálogo</button>
        </p>
      </div>
    </section>

    <!-- Análise detalhada do produto selecionado -->
    <AnaliseDetalhada
      v-if="selecionado"
      :produto="selecionado"
      @editar="emit('editar', $event)"
    />
  </div>
</template>

<style scoped>
.descoberta { margin-bottom: 15px; }
.grade-descoberta {
  display: grid; gap: 14px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
@media (max-width: 900px) { .grade-descoberta { grid-template-columns: 1fr; } }

.filtros {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  margin-bottom: 18px;
}
.busca { flex: 1; min-width: 180px; }

.grade-produtos {
  display: grid; gap: 18px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
@media (max-width: 840px) { .grade-produtos { grid-template-columns: 1fr; } }

.paginacao {
  display: flex; align-items: center; justify-content: center;
  gap: 14px; margin-top: 20px;
}
.paginacao button:disabled { opacity: 0.35; cursor: default; }

.vazio p { margin: 6px 0; }
.vazio p:last-child { display: flex; gap: 10px; justify-content: center; align-items: center; flex-wrap: wrap; }
</style>
