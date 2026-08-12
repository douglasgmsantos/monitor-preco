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

const props = defineProps({
  produtoId: { type: String, default: null },   // null = criação
  prefill: { type: Object, default: null },     // {nome, loja, url, alvoPlaceholder}
});
const emit = defineEmits(["fechar", "salvo"]);

const { produtos, criarProduto, salvarEdicao } = useProdutos();

const edicao = computed(() =>
  props.produtoId ? produtos.value.find((p) => p.id === props.produtoId) : null);

const nome = ref("");
const alvo = ref("");
const tolerancia = ref("0");
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
    alvo.value = formatarBRL(edicao.value.dados.precoAlvoCentavos).replace("R$", "").trim();
    tolerancia.value = String(edicao.value.dados.toleranciaPct ?? 0);
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

/** Lê e valida o formulário. Devolve os dados, ou null se algo está errado. */
function lerFormulario() {
  erro.value = "";
  const nomeLimpo = nome.value.trim();
  if (!nomeLimpo || nomeLimpo.length > 200) {
    erro.value = "Informe um nome de até 200 caracteres.";
    return null;
  }

  const alvoCentavos = paraCentavos(alvo.value);
  if (alvoCentavos === null) {
    erro.value = "Preço-alvo inválido. Use o formato 1.789,90 ou 1789.90.";
    return null;
  }
  const tol = parseInt(tolerancia.value, 10);
  if (!Number.isInteger(tol) || tol < 0 || tol > 100) {
    erro.value = "Tolerância precisa ser um inteiro entre 0 e 100.";
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
  return { nome: nomeLimpo, alvoCentavos, tolerancia: tol, fontes: lidas };
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
      <input id="m-nome" v-model="nome" class="campo" placeholder="Ex.: Placa de vídeo RX 7600">

      <div class="dupla">
        <div>
          <label class="rotulo-campo" for="m-alvo">Preço-alvo</label>
          <input id="m-alvo" v-model="alvo" class="campo mono" inputmode="decimal"
                 :placeholder="(prefill && prefill.alvoPlaceholder) || '1.789,90'">
        </div>
        <div>
          <label class="rotulo-campo" for="m-tol">Tolerância %</label>
          <input id="m-tol" v-model="tolerancia" class="campo mono" type="number"
                 min="0" max="100" step="1">
        </div>
      </div>

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
