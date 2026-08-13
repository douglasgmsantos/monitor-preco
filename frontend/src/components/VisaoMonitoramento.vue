<script setup>
import { computed, ref, watch } from "vue";
import { formatarBRL } from "../dinheiro.js";
import { nomeDaLojaPorHost, hostDaUrl } from "../lojas.js";
import {
  menorPrecoAtual, ultimaVerificacao, useProdutos,
} from "../composables/useProdutos.js";
import FiltrosProdutos from "./FiltrosProdutos.vue";
import { useCatalogo } from "../composables/useCatalogo.js";
import CartaoDescoberta from "./CartaoDescoberta.vue";
import CartaoProduto from "./CartaoProduto.vue";

const props = defineProps({
  selecionadoId: { type: String, default: null },
});
const emit = defineEmits([
  "selecionar", "ver-detalhes", "editar", "acompanhar", "novo-produto", "ir-catalogo",
]);

const { produtos, carregando } = useProdutos();
const { catalogo, carregado } = useCatalogo();

/** URLs que o usuário já acompanha, para não oferecer duas vezes. */
const urlsAcompanhadas = computed(() => {
  const urls = new Set();
  for (const produto of produtos.value) {
    for (const fonte of produto.fontes) urls.add(fonte.url);
  }
  return urls;
});

// Descoberta a partir do que VOCÊ já monitora, e não do catálogo inteiro.
//
// Antes eram os 3 itens mais baratos da vitrine — o que, com 3.276 itens de dez
// categorias, sugeria cooler para quem acompanha placa de vídeo. Agora o
// critério é semelhança com os produtos do radar: as palavras do nome que você
// cadastrou viram o filtro.
const PALAVRAS_IGNORADAS = new Set([
  "de", "da", "do", "com", "para", "por", "e", "em", "a", "o", "os", "as",
  "placa", "kit", "gb", "tb", "mhz",   // genéricas demais neste domínio
]);

/** Palavras significativas dos produtos monitorados. */
const termosDoRadar = computed(() => {
  const termos = new Set();
  for (const produto of produtos.value) {
    for (const palavra of (produto.dados.nome || "").toLowerCase().split(/[^\wÀ-ÿ]+/)) {
      // 3 letras é o piso: abaixo disso ("rx", "ti") casa quase tudo.
      if (palavra.length >= 3 && !PALAVRAS_IGNORADAS.has(palavra)) termos.add(palavra);
    }
  }
  return termos;
});

const MAXIMO_DE_SUGESTOES = 3;

const sugestoes = computed(() => {
  const disponiveis = catalogo.value
    .filter((i) => i.preco !== null && i.disponivel !== false)
    .filter((i) => !urlsAcompanhadas.value.has(i.url));

  // Sem produtos ainda? Não há de que se parecer — cai no mais barato, que é o
  // critério honesto quando não se sabe nada sobre o gosto do usuário.
  if (!termosDoRadar.value.size) {
    return [...disponiveis].sort((a, b) => a.preco - b.preco).slice(0, MAXIMO_DE_SUGESTOES);
  }

  const pontuados = [];
  for (const item of disponiveis) {
    const palavras = (item.nome || "").toLowerCase().split(/[^\wÀ-ÿ]+/);
    let pontos = 0;
    for (const palavra of new Set(palavras)) {
      if (termosDoRadar.value.has(palavra)) pontos += 1;
    }
    if (pontos > 0) pontuados.push({ item, pontos });
  }

  return pontuados
    // Mais parecido primeiro; empate desempata pelo mais barato.
    .sort((a, b) => b.pontos - a.pontos || a.item.preco - b.item.preco)
    .slice(0, MAXIMO_DE_SUGESTOES)
    .map((p) => p.item);
});

// ---------------------------------------------------------------------------
// Busca e paginação do radar
//
// Mesmo desenho do catálogo (`VisaoCatalogo.vue`), de propósito: as duas listas
// se parecem, então filtrar tem de funcionar do mesmo jeito nas duas.
// ---------------------------------------------------------------------------

// Duas fileiras completas na grade de 4 colunas. Com 4 por página a paginação
// aparecia a partir do quinto produto e mostrava uma fileira só — mais clique
// do que conteúdo.
const POR_PAGINA = 8;
const busca = ref("");
const pagina = ref(1);
const filtros = ref({
  ordem: "", precoMin: null, precoMax: null, desde: "", ate: "", loja: "",
});

/** Só as lojas que aparecem nos produtos do usuário — filtro por loja que ele
 *  não usa é ruído. */
const lojasPresentes = computed(() => {
  const nomes = new Set();
  for (const p of produtos.value) {
    for (const f of p.fontes) if (f.loja) nomes.add(f.loja);
  }
  return [...nomes].sort((a, b) => a.localeCompare(b, "pt-BR"));
});

/** Fim do dia informado: o usuário que escolhe "até 13/08" espera incluir o dia
 *  13 inteiro, não parar à meia-noite dele. */
function fimDoDia(iso) {
  const [ano, mes, dia] = iso.split("-").map(Number);
  return new Date(ano, mes - 1, dia, 23, 59, 59, 999);
}
function inicioDoDia(iso) {
  const [ano, mes, dia] = iso.split("-").map(Number);
  return new Date(ano, mes - 1, dia, 0, 0, 0, 0);
}

/** Busca por nome do produto E por loja.
 *
 *  A loja entra porque é a segunda pergunta natural de quem tem vários produtos
 *  ("o que eu sigo na Amazon?"), e a informação já está no cartão — filtrar por
 *  algo que está na tela é o que o usuário espera poder fazer. */
const filtrados = computed(() => {
  const texto = busca.value.trim().toLowerCase();
  const f = filtros.value;
  let lista = produtos.value;

  if (texto) {
    lista = lista.filter((p) => {
      const nome = (p.dados.nome || "").toLowerCase();
      if (nome.includes(texto)) return true;
      return p.fontes.some((x) => (x.loja || "").toLowerCase().includes(texto));
    });
  }

  if (f.loja) {
    lista = lista.filter((p) => p.fontes.some((x) => x.loja === f.loja));
  }

  // Faixa de preço: sobre o preço ATUAL (menor entre as fontes). Produto sem
  // preço fica de fora quando há filtro de faixa — não dá para afirmar que ele
  // cabe numa faixa que não se conhece.
  if (f.precoMin !== null || f.precoMax !== null) {
    lista = lista.filter((p) => {
      const preco = menorPrecoAtual(p);
      if (preco === null) return false;
      if (f.precoMin !== null && preco < f.precoMin) return false;
      if (f.precoMax !== null && preco > f.precoMax) return false;
      return true;
    });
  }

  if (f.desde || f.ate) {
    lista = lista.filter((p) => {
      const quando = ultimaVerificacao(p);
      if (!quando) return false;
      const data = quando.toDate ? quando.toDate() : new Date(quando);
      if (isNaN(data)) return false;
      if (f.desde && data < inicioDoDia(f.desde)) return false;
      if (f.ate && data > fimDoDia(f.ate)) return false;
      return true;
    });
  }

  if (f.ordem) {
    // Cópia antes de ordenar: `produtos` é reativo e ordenar no lugar
    // embaralharia a fonte para todo mundo que a observa.
    lista = [...lista].sort((a, b) => {
      if (f.ordem === "recentes") {
        const da = ultimaVerificacao(a), db = ultimaVerificacao(b);
        const ta = da ? (da.toDate ? da.toDate() : new Date(da)).getTime() : 0;
        const tb = db ? (db.toDate ? db.toDate() : new Date(db)).getTime() : 0;
        return tb - ta;
      }
      const pa = menorPrecoAtual(a), pb = menorPrecoAtual(b);
      // Sem preço vai para o fim em qualquer ordenação: um `null` no topo da
      // lista de "menor valor" seria mentira.
      if (pa === null) return 1;
      if (pb === null) return -1;
      return f.ordem === "menor" ? pa - pb : pb - pa;
    });
  }

  return lista;
});

const paginas = computed(() => Math.max(1, Math.ceil(filtrados.value.length / POR_PAGINA)));

const visiveis = computed(() => {
  const atual = Math.min(Math.max(1, pagina.value), paginas.value);
  return filtrados.value.slice((atual - 1) * POR_PAGINA, atual * POR_PAGINA);
});

function aoFiltrar() { pagina.value = 1; }   // filtrar sempre volta ao começo

// Mudar filtro também volta para a página 1: filtrar estando na página 3 e cair
// numa lista vazia é o jeito mais rápido de achar que os produtos sumiram.
watch(filtros, aoFiltrar, { deep: true });

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
      <h2 class="titulo-secao">
        {{ termosDoRadar.size ? "Parecidos com o que você monitora" : "Sugestões do catálogo" }}
      </h2>
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

      <template v-if="produtos.length">
        <div class="filtros">
          <input v-model="busca" class="busca" placeholder="filtrar por nome ou loja…"
                 @input="aoFiltrar">
          <span class="dica">{{ filtrados.length }} de {{ produtos.length }}</span>
        </div>
        <FiltrosProdutos v-model="filtros" :lojas="lojasPresentes" />
      </template>

      <div v-if="visiveis.length" class="grade-produtos">
        <CartaoProduto
          v-for="produto in visiveis"
          :key="produto.id"
          :produto="produto"
          :selecionado="produto.id === selecionadoId"
          @selecionar="emit('selecionar', produto.id)"
          @ver-detalhes="emit('ver-detalhes', produto.id)"
          @editar="emit('editar', $event)"
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

/* 4 por linha no desktop. Os pontos de quebra saem da LARGURA MÍNIMA em que o
   cartão ainda cabe legível (~250px), não de tamanhos redondos de tela. */
.grade-produtos {
  display: grid; gap: 16px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
@media (max-width: 1180px) { .grade-produtos { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px)  { .grade-produtos { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px)  { .grade-produtos { grid-template-columns: 1fr; } }

.paginacao {
  display: flex; align-items: center; justify-content: center;
  gap: 14px; margin-top: 20px;
}
.paginacao button:disabled { opacity: 0.35; cursor: default; }

.vazio p { margin: 6px 0; }
.vazio p:last-child { display: flex; gap: 10px; justify-content: center; align-items: center; flex-wrap: wrap; }
</style>
