<script setup>
// A vitrine completa, com os mesmos filtros do front antigo.
//
// O preço aqui é o de TABELA (10% a 31% acima do preço real da página do
// produto — medido em 2026-08-10). Ele nunca dispara alerta; serve para achar
// o produto. O aviso sob o título existe para o usuário não comparar dois
// números que não são comparáveis.
import { computed, ref, watch } from "vue";
import { formatarBRL } from "../dinheiro.js";
import { casaTermos } from "../busca.js";
import { nomeDaLojaPorHost, hostDaUrl } from "../lojas.js";
import { useCatalogo } from "../composables/useCatalogo.js";
import { useProdutos } from "../composables/useProdutos.js";
import FiltrosProdutos from "./FiltrosProdutos.vue";

const emit = defineEmits(["acompanhar"]);

const { catalogo, categorias, carregado } = useCatalogo();
const { produtos } = useProdutos();

const POR_PAGINA = 12;
const busca = ref("");
const pagina = ref(1);

// Mesmo componente e mesmo formato de estado do radar. Duas telas com listas
// parecidas precisam filtrar do mesmo jeito — inventar um segundo padrão aqui
// só criaria diferença sem motivo.
const filtros = ref({
  ordem: "", precoMin: null, precoMax: null, desde: "", ate: "",
  loja: "", categoria: "",
});
watch(filtros, () => { pagina.value = 1; }, { deep: true });

const lojasPresentes = computed(() => {
  const nomes = new Set();
  for (const item of catalogo.value) if (item.loja) nomes.add(item.loja);
  return [...nomes].sort((a, b) => a.localeCompare(b, "pt-BR"));
});

const categoriasParaFiltro = computed(() =>
  categorias.value.map((c) => ({
    valor: c.categoria,
    rotulo: `${c.categoria} (${c.quantidade})`,
  })));

const urlsAcompanhadas = computed(() => {
  const urls = new Set();
  for (const produto of produtos.value) {
    for (const fonte of produto.fontes) urls.add(fonte.url);
  }
  return urls;
});

const filtrados = computed(() => {
  const f = filtros.value;
  let itens = catalogo.value.filter((i) => i.preco !== null || i.disponivel === false);

  // Todos os termos precisam aparecer, em qualquer ordem: "ddr5 16gb" acha
  // "Memória Ram Adata Xpg Lancer Blade Ddr5 16gb". Ver src/busca.js.
  if (busca.value.trim()) {
    itens = itens.filter((i) => casaTermos(busca.value, i.nome, i.loja));
  }

  if (f.categoria) itens = itens.filter((i) => i.categoria === f.categoria);
  if (f.loja) itens = itens.filter((i) => i.loja === f.loja);

  if (f.precoMin !== null || f.precoMax !== null) {
    itens = itens.filter((i) => {
      if (i.preco === null) return false;   // esgotado não cabe em faixa nenhuma
      if (f.precoMin !== null && i.preco < f.precoMin) return false;
      if (f.precoMax !== null && i.preco > f.precoMax) return false;
      return true;
    });
  }

  return [...itens].sort((a, b) => {
    if (f.ordem === "nome") return a.nome.localeCompare(b.nome, "pt-BR");
    // Esgotado (preço nulo) vai para o fim em qualquer ordenação: no topo de
    // "maior valor" ele seria uma linha vazia liderando a lista.
    if (a.preco === null) return 1;
    if (b.preco === null) return -1;
    if (f.ordem === "maior") return b.preco - a.preco;
    return a.preco - b.preco;   // padrão: menor preço primeiro
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

function acompanhar(item) {
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
    <p class="olho">Catálogo</p>
    <h2 class="titulo-secao">Produtos descobertos nas lojas</h2>
    <p class="dica aviso">
      Preço de vitrine (tabela) — costuma ficar acima do preço real da página.
      Ao acompanhar, o preço passa a vir da página do produto.
    </p>

    <div class="filtros">
      <input v-model="busca" class="busca" placeholder="ddr5 16gb — vários termos, todos precisam aparecer" @input="aoFiltrar">
      <span class="dica">{{ filtrados.length }} item(ns)</span>
    </div>
    <FiltrosProdutos
      v-model="filtros"
      :lojas="lojasPresentes"
      :categorias="categoriasParaFiltro"
      :com-data="false"
    />

    <div v-if="visiveis.length" class="grade">
      <article
        v-for="item in visiveis"
        :key="item.sku"
        class="cartao item"
        :class="{ esgotado: item.disponivel === false, seguido: urlsAcompanhadas.has(item.url) }"
      >
        <div class="moldura-img">
          <img v-if="item.imagem" :src="item.imagem" alt="" loading="lazy">
          <span v-else class="sem-img" aria-hidden="true">🖥</span>
        </div>
        <span class="titulo" :title="item.nome">{{ item.nome }}</span>
        <span class="preco mono">
          {{ formatarBRL(item.preco) }}
          <s v-if="item.tabela && item.tabela !== item.preco" class="dica">{{ formatarBRL(item.tabela) }}</s>
        </span>
        <div class="rodape">
          <a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.loja }} ↗</a>
          <span v-if="item.disponivel === false" class="selo neutro">Esgotado</span>
          <span v-else-if="urlsAcompanhadas.has(item.url)" class="ja-segue">✓ já segue</span>
          <button v-else class="acompanhar" @click="acompanhar(item)">+ acompanhar</button>
        </div>
      </article>
    </div>

    <p v-else-if="carregado" class="vazio">
      {{ catalogo.length ? "Nenhum item com esses filtros." : "Catálogo ainda não foi raspado." }}
    </p>

    <div v-if="paginas > 1" class="paginacao">
      <button class="botao-discreto" :disabled="pagina <= 1" @click="irPara(-1)">‹ anterior</button>
      <span class="dica mono">{{ Math.min(pagina, paginas) }} / {{ paginas }}</span>
      <button class="botao-discreto" :disabled="pagina >= paginas" @click="irPara(1)">próxima ›</button>
    </div>
  </div>
</template>

<style scoped>
.aviso { margin: -12px 0 20px; }
.filtros {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  margin-bottom: 20px;
}
.busca { flex: 1; min-width: 180px; }

.grade {
  display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
}
.item {
  padding: 14px;
  display: flex; flex-direction: column; gap: 8px;
  min-width: 0;
}
.item.seguido { border-color: var(--tinta); }
.item.esgotado { opacity: 0.55; }
.item.esgotado .moldura-img img { filter: grayscale(1); }

.moldura-img {
  aspect-ratio: 1 / 1;   /* proporção fixa: cartões não dançam ao carregar */
  border-radius: 12px; overflow: hidden;
  background: var(--suave);
  display: grid; place-items: center;
}
.moldura-img img { width: 100%; height: 100%; object-fit: contain; display: block; }
.sem-img { font-size: 26px; }

.titulo {
  font-size: 13px; line-height: 1.35; min-height: 2.7em;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.preco { font-size: 17px; font-weight: 650; }
.preco s { font-weight: 400; font-size: 13px; margin-left: 6px; }

.rodape {
  margin-top: auto;
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.rodape a { color: var(--tinta-fraca); font-size: 12px; text-decoration: none; }
.rodape a:hover { color: var(--tinta); text-decoration: underline; }
.ja-segue { font-size: 12px; font-weight: 650; color: var(--bom); }
.acompanhar { font-size: 12px; padding: 6px 10px; border-radius: 999px; }

.paginacao {
  display: flex; align-items: center; justify-content: center;
  gap: 14px; margin-top: 20px;
}
.paginacao button:disabled { opacity: 0.35; cursor: default; }
</style>
