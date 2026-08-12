<script setup>
import { computed } from "vue";
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

      <div v-if="produtos.length" class="grade-produtos">
        <CartaoProduto
          v-for="produto in produtos"
          :key="produto.id"
          :produto="produto"
          :selecionado="produto.id === selecionadoId"
          @selecionar="emit('selecionar', produto.id)"
          @ver-detalhes="emit('ver-detalhes', produto.id)"
        />
      </div>

      <div v-else-if="!carregando" class="vazio">
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
.descoberta { margin-bottom: 48px; }
.grade-descoberta {
  display: grid; gap: 14px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
@media (max-width: 900px) { .grade-descoberta { grid-template-columns: 1fr; } }

.grade-produtos {
  display: grid; gap: 18px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
@media (max-width: 840px) { .grade-produtos { grid-template-columns: 1fr; } }

.vazio p { margin: 6px 0; }
.vazio p:last-child { display: flex; gap: 10px; justify-content: center; align-items: center; flex-wrap: wrap; }
</style>
