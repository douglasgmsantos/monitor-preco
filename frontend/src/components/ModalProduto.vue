<script setup>
// Cadastro e edição, no modal do desenho. A validação é a MESMA do front
// antigo (lerFormulario), incluindo a recusa de loja incompatível com o motivo
// verificado — esse aviso é conteúdo, não decoração: é o que impede o usuário
// de achar que o sistema quebrou.
//
// O desenho original traz só nome + URL, mas preço-alvo e tolerância são
// obrigatórios no modelo (as rules exigem os campos) — então eles estão aqui,
// na mesma linguagem visual.
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { formatarBRL, paraCentavos } from "../dinheiro.js";
import {
  LOJAS, motivoDeIncompatibilidade, hostCombinaComLoja, hostDaUrl,
  lojaSugeridaPelaUrl,
} from "../lojas.js";
import { useProdutos } from "../composables/useProdutos.js";
import { useCatalogo } from "../composables/useCatalogo.js";

const props = defineProps({
  produtoId: { type: String, default: null },   // null = criação
  prefill: { type: Object, default: null },     // {nome, loja, url, alvoPlaceholder}
});
const emit = defineEmits(["fechar", "salvo"]);

const { produtos, criarProduto, salvarEdicao } = useProdutos();
const { catalogo } = useCatalogo();

const edicao = computed(() =>
  props.produtoId ? produtos.value.find((p) => p.id === props.produtoId) : null);

const nome = ref("");
// A FAIXA que o usuário aceita pagar. O MÁXIMO é o gatilho do alerta; o mínimo
// é referência dele ("meu preço ideal") e não dispara nada — ver coletor/alertas.py.
const valorMin = ref("");
const valorMax = ref("");
const fontes = reactive([]);
const erro = ref("");
const salvando = ref(false);

function novaLinha({ loja = "", url = "", fonteId = "" } = {}) {
  // Loja fora da lista fechada vem de fonte antiga (ex.: "Carrefour"). Cai como
  // vazia: o usuário precisa escolher uma suportada para salvar, e é isso mesmo
  // — o coletor não sabe ler as outras.
  const conhecida = LOJAS.some((l) => l.nome === loja);
  return { escolha: conhecida ? loja : "", url, fonteId };
}

/** Colou a URL primeiro? O domínio já diz a loja — preenche sozinho.
 *  Com a lista fechada o domínio determina a loja sem ambiguidade, então pedir
 *  para o usuário repetir no dropdown o que a URL já disse é só chance de erro. */
function aoDigitarUrl(linha) {
  if (linha.escolha) return;
  const sugerida = lojaSugeridaPelaUrl(linha.url);
  if (sugerida) linha.escolha = sugerida;
}

onMounted(() => {
  if (edicao.value) {
    nome.value = edicao.value.dados.nome || "";
    // reais na entrada, centavos no armazenamento
    // reais na entrada, centavos no armazenamento
    valorMin.value = formatarBRL(edicao.value.dados.valorMinCentavos).replace("R$", "").trim();
    valorMax.value = formatarBRL(edicao.value.dados.valorMaxCentavos).replace("R$", "").trim();
    for (const fonte of edicao.value.fontes) {
      fontes.push(novaLinha({ loja: fonte.loja, url: fonte.url, fonteId: fonte.id }));
    }
  } else if (props.prefill) {
    nome.value = props.prefill.nome || "";
    fontes.push(novaLinha({ loja: props.prefill.loja || "", url: props.prefill.url || "" }));
  }
  if (!fontes.length) fontes.push(novaLinha());
  document.addEventListener("keydown", aoTeclar);
});
onUnmounted(() => document.removeEventListener("keydown", aoTeclar));

function aoTeclar(evento) {
  if (evento.key === "Escape") emit("fechar");
}

function lojaDaLinha(linha) {
  return linha.escolha;
}

// ---------------------------------------------------------------------------
// Sugestões do catálogo enquanto se digita o nome
//
// O catálogo já sabe nome, URL, loja e preço de milhares de itens. Sem isto o
// usuário digita o nome à mão e depois vai caçar a URL no site da loja — duas
// tarefas que o sistema já tem como fazer por ele.
// ---------------------------------------------------------------------------

const MINIMO_PARA_SUGERIR = 3;
const MAXIMO_DE_SUGESTOES = 6;

const sugestoesVisiveis = ref(true);

/** Casa por PALAVRAS, não por substring: quem digita "9070 asrock" espera achar
 *  "ASRock ... RX 9070 XT", que um `includes` da frase inteira não acha. */
const sugestoes = computed(() => {
  if (props.produtoId) return [];               // editando: não faz sentido trocar
  const termo = nome.value.trim().toLowerCase();
  if (termo.length < MINIMO_PARA_SUGERIR || !sugestoesVisiveis.value) return [];

  const palavras = termo.split(/\s+/).filter(Boolean);
  const jaUsadas = new Set(fontes.map((f) => f.url.trim()).filter(Boolean));

  return catalogo.value
    .filter((item) => {
      if (!item.nome || jaUsadas.has(item.url)) return false;
      const alvo = item.nome.toLowerCase();
      return palavras.every((palavra) => alvo.includes(palavra));
    })
    // Mais barato primeiro: entre dois itens equivalentes, é a escolha óbvia.
    .sort((a, b) => (a.preco ?? Infinity) - (b.preco ?? Infinity))
    .slice(0, MAXIMO_DE_SUGESTOES);
});

/** Usa a sugestão: nome, URL e loja de uma vez. O valor máximo fica em branco
 *  de propósito — é a única informação que o catálogo não tem, e é justamente a
 *  decisão que só o usuário pode tomar. */
function usarSugestao(item) {
  nome.value = item.nome;
  const loja = lojaSugeridaPelaUrl(item.url);
  const vazia = fontes.find((f) => !f.url.trim());
  if (vazia) {
    vazia.url = item.url;
    vazia.escolha = loja;
  } else {
    fontes.push(novaLinha({ loja, url: item.url }));
  }
  if (item.preco && !valorMax.value) {
    // Preço da vitrine é o de TABELA e costuma ficar acima do real — serve de
    // ponto de partida para o teto, nunca de valor final.
    valorMax.value = formatarBRL(item.preco).replace("R$", "").trim();
  }
  sugestoesVisiveis.value = false;
}

/** Lê e valida o formulário. Devolve os dados, ou null se algo está errado. */
function lerFormulario() {
  erro.value = "";
  const nomeLimpo = nome.value.trim();
  if (!nomeLimpo || nomeLimpo.length > 200) {
    erro.value = "Informe um nome de até 200 caracteres.";
    return null;
  }

  const minCentavos = paraCentavos(valorMin.value);
  if (minCentavos === null) {
    erro.value = "Valor mínimo inválido. Use o formato 1.789,90 ou 1789.90.";
    return null;
  }
  const maxCentavos = paraCentavos(valorMax.value);
  if (maxCentavos === null) {
    erro.value = "Valor máximo inválido. Use o formato 1.789,90 ou 1789.90.";
    return null;
  }
  // Mesma checagem das security rules. Aqui é só para a mensagem ser útil: uma
  // faixa invertida seria recusada pelo servidor com um erro genérico.
  if (maxCentavos < minCentavos) {
    erro.value = "O valor máximo precisa ser maior ou igual ao mínimo.";
    return null;
  }

  const lidas = [];
  for (const linha of fontes) {
    const loja = lojaDaLinha(linha);
    const url = linha.url.trim();
    if (!loja && !url) continue;
    if (!loja) {
      erro.value = "Escolha uma das lojas suportadas.";
      return null;
    }
    if (!/^https:\/\/.+/.test(url)) {
      erro.value = `URL inválida em “${loja}”: precisa começar com https://`;
      return null;
    }
    // O motivo verificado vem ANTES da checagem de domínio: dizer por que a
    // loja não funciona ensina mais que dizer que ela não é a escolhida.
    const incompativel = motivoDeIncompatibilidade(url);
    if (incompativel) {
      erro.value = `Essa loja não pode ser monitorada: ${incompativel}.`;
      return null;
    }
    if (!hostCombinaComLoja(url, loja)) {
      erro.value =
        `A URL não é de ${loja} (domínio: ${hostDaUrl(url) || "desconhecido"}). ` +
        `Só são aceitas: ${LOJAS.map((l) => l.nome).join(", ")}.`;
      return null;
    }
    lidas.push({ loja, url, fonteId: linha.fonteId || "" });
  }
  if (!lidas.length) {
    erro.value = "Cadastre ao menos uma loja com URL.";
    return null;
  }
  return { nome: nomeLimpo, minCentavos, maxCentavos, fontes: lidas };
}

async function salvar() {
  const dados = lerFormulario();
  if (!dados) return;

  salvando.value = true;
  try {
    if (props.produtoId) {
      await salvarEdicao(props.produtoId, dados);
      emit("salvo", props.produtoId);
    } else {
      const id = await criarProduto(dados);
      emit("salvo", id);
    }
  } catch (excecao) {
    erro.value = `Não foi possível salvar: ${excecao.message || excecao}`;
  } finally {
    salvando.value = false;
  }
}
</script>

<template>
  <div class="veu" @click.self="emit('fechar')">
    <div class="janela" role="dialog" aria-modal="true"
         :aria-label="produtoId ? 'Editar produto' : 'Novo produto'">
      <h2 class="titulo">{{ produtoId ? "Editar produto" : "Novo produto" }}</h2>
      <p class="dica sub">
        Informe o nome, o preço-alvo e ao menos uma fonte.
        O histórico começa na primeira coleta.
      </p>

      <label class="rotulo-campo" for="m-nome">Nome do produto</label>
      <div class="campo-com-sugestao">
        <input id="m-nome" v-model="nome" class="campo"
               placeholder="Ex.: Placa de vídeo RX 7600"
               autocomplete="off"
               @input="sugestoesVisiveis = true">
        <ul v-if="sugestoes.length" class="sugestoes" role="listbox">
          <li v-for="item in sugestoes" :key="item.sku">
            <button type="button" role="option" @click="usarSugestao(item)">
              <img v-if="item.imagem" :src="item.imagem" alt="" loading="lazy">
              <span v-else class="sem-img" aria-hidden="true">🖥</span>
              <span class="texto">
                <span class="nome-sugestao">{{ item.nome }}</span>
                <span class="dica">{{ item.loja }} · {{ formatarBRL(item.preco) }}</span>
              </span>
            </button>
          </li>
        </ul>
      </div>
      <p v-if="!produtoId" class="dica-busca">
        Digite 3 letras e escolha do catálogo: nome, URL e loja vêm preenchidos.
      </p>

      <div class="dupla">
        <div>
          <label class="rotulo-campo" for="m-min">Valor mínimo</label>
          <input id="m-min" v-model="valorMin" class="campo mono" inputmode="decimal"
                 placeholder="1.500,00">
        </div>
        <div>
          <label class="rotulo-campo" for="m-max">Valor máximo</label>
          <input id="m-max" v-model="valorMax" class="campo mono" inputmode="decimal"
                 :placeholder="(prefill && prefill.alvoPlaceholder) || '1.789,90'">
        </div>
      </div>
      <p class="dica-faixa">
        O <strong>máximo</strong> é o que dispara o alerta — você é avisado assim
        que o preço ficar igual ou abaixo dele. O mínimo é a sua referência de
        preço ideal e não dispara nada.
      </p>

      <label class="rotulo-campo">Fontes (loja + URL)</label>
      <div v-for="(linha, indice) in fontes" :key="indice" class="par-fonte">
        <div class="celula-loja">
          <select v-model="linha.escolha" class="campo">
            <option value="">Selecione a loja…</option>
            <option v-for="l in LOJAS" :key="l.nome" :value="l.nome">{{ l.nome }}</option>
          </select>
        </div>
        <input v-model="linha.url" class="campo mono url"
               placeholder="https://loja.com.br/produto"
               @input="aoDigitarUrl(linha)">
        <button class="botao-discreto" title="Remover"
                :disabled="fontes.length <= 1"
                @click="fontes.splice(indice, 1)">✕</button>
      </div>
      <p class="dica-lojas">
        Só estas quatro: {{ LOJAS.map((l) => l.nome).join(", ") }}. Cole a URL da
        página do produto — a loja é preenchida sozinha.
      </p>
      <button class="botao-discreto mais-fonte" @click="fontes.push(novaLinha())">
        + adicionar loja
      </button>

      <p v-if="erro" class="erro">{{ erro }}</p>

      <div class="rodape">
        <button class="botao-discreto" @click="emit('fechar')">Cancelar</button>
        <button class="botao-primario" :disabled="salvando" @click="salvar">
          {{ produtoId ? "Salvar alterações" : "Monitorar" }}
        </button>
      </div>
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
  width: 100%; max-width: 600px;
  background: var(--superficie);
  border-radius: 20px;
  padding: 30px 32px;
  display: grid; gap: 14px;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
}
.titulo { margin: 0; font-size: 23px; font-weight: 700; letter-spacing: -0.01em; }
.sub { margin: -8px 0 4px; }

.dupla { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; }

.par-fonte {
  display: grid; grid-template-columns: 180px 1fr auto;
  gap: 8px; align-items: start;
}
.celula-loja { display: grid; gap: 6px; min-width: 0; }
.url { font-size: 13px; }
.mais-fonte { justify-self: start; font-size: 13px; }
.campo-com-sugestao { position: relative; }
.campo-com-sugestao .campo { width: 100%; }
.sugestoes {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 40;
  margin: 0; padding: 6px; list-style: none;
  background: var(--superficie);
  border: 1px solid var(--borda); border-radius: 12px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.2);
  max-height: 300px; overflow-y: auto;
  display: grid; gap: 2px;
}
.sugestoes button {
  width: 100%; border: none; background: none; border-radius: 9px;
  padding: 8px; display: flex; gap: 10px; align-items: center; text-align: left;
}
.sugestoes button:hover { background: var(--suave); }
.sugestoes img, .sugestoes .sem-img {
  width: 38px; height: 38px; flex: none; border-radius: 8px;
  background: var(--suave); object-fit: contain;
  display: grid; place-items: center; font-size: 16px;
}
.sugestoes .texto { display: grid; gap: 2px; min-width: 0; }
.nome-sugestao {
  font-size: 13px; line-height: 1.3;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.dica-busca { margin: -4px 0 0; font-size: 12px; color: var(--tinta-2); }

.dica-faixa {
  margin: -4px 0 0; font-size: 12px; line-height: 1.45;
  color: var(--tinta-2);
}
.dica-lojas {
  margin: -4px 0 0; font-size: 12px; line-height: 1.45;
  color: var(--tinta-2);
}

.rodape {
  display: flex; justify-content: flex-end; gap: 10px; margin-top: 6px;
}

@media (max-width: 560px) {
  .janela { padding: 22px 18px; }
  .dupla { grid-template-columns: 1fr; }
  .par-fonte { grid-template-columns: 1fr; }
}
</style>
