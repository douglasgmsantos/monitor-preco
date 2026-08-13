<script setup>
// Filtros do radar: um painel para escolher, e CHIPS para o que está ativo.
//
// Os chips não são enfeite. Filtro escondido atrás de um botão é a causa mais
// comum de "sumiu meu produto": o usuário filtra, esquece, e semanas depois
// acha que perdeu dado. Com cada filtro visível e removível em um clique, o
// estado da tela é sempre autoexplicativo.
import { computed, onUnmounted, ref } from "vue";
import { formatarBRL, paraCentavos } from "../dinheiro.js";

const props = defineProps({
  // Lojas presentes nos itens — só se oferece filtro do que existe.
  lojas: { type: Array, default: () => [] },
  // Categorias, quando a tela tem (catálogo). Vazio = a seção não aparece.
  categorias: { type: Array, default: () => [] },
  // A data filtra pela última verificação, que só existe em produto
  // acompanhado. No catálogo não há esse dado, então a seção some — oferecer
  // filtro que não filtra nada é pior que não oferecer.
  comData: { type: Boolean, default: true },
});
const filtros = defineModel({ type: Object, required: true });

const aberto = ref(false);

// Rascunho: o painel só aplica ao confirmar. Aplicar a cada tecla faria a lista
// pular embaixo do usuário enquanto ele ainda está digitando a faixa.
const rascunho = ref(vazio());

function vazio() {
  return {
    ordem: "",        // "menor" | "maior" | "recentes" | "nome"
    precoMin: "",
    precoMax: "",
    desde: "",        // AAAA-MM-DD
    ate: "",
    loja: "",
    categoria: "",
  };
}

function abrir() {
  rascunho.value = { ...filtros.value, precoMin: centavosParaTexto(filtros.value.precoMin),
                     precoMax: centavosParaTexto(filtros.value.precoMax) };
  aberto.value = true;
  document.addEventListener("click", fecharFora);
}
function fechar() {
  aberto.value = false;
  document.removeEventListener("click", fecharFora);
}
function fecharFora(evento) {
  if (!evento.target.closest(".area-filtros")) fechar();
}
onUnmounted(() => document.removeEventListener("click", fecharFora));

function centavosParaTexto(centavos) {
  return centavos ? formatarBRL(centavos).replace("R$", "").trim() : "";
}

const erro = ref("");

function aplicar() {
  const min = rascunho.value.precoMin.trim() ? paraCentavos(rascunho.value.precoMin) : null;
  const max = rascunho.value.precoMax.trim() ? paraCentavos(rascunho.value.precoMax) : null;
  if (rascunho.value.precoMin.trim() && min === null) {
    erro.value = "Preço mínimo inválido."; return;
  }
  if (rascunho.value.precoMax.trim() && max === null) {
    erro.value = "Preço máximo inválido."; return;
  }
  if (min !== null && max !== null && max < min) {
    erro.value = "O preço máximo precisa ser maior que o mínimo."; return;
  }
  if (rascunho.value.desde && rascunho.value.ate && rascunho.value.ate < rascunho.value.desde) {
    erro.value = "A data final precisa ser depois da inicial."; return;
  }
  erro.value = "";
  filtros.value = { ...rascunho.value, precoMin: min, precoMax: max };
  fechar();
}

function limparTudo() {
  filtros.value = { ...vazio(), precoMin: null, precoMax: null };
  rascunho.value = vazio();
  erro.value = "";
}

const ROTULOS_DE_ORDEM = {
  menor: "Menor valor",
  maior: "Maior valor",
  recentes: "Verificados recentemente",
  nome: "Nome (A–Z)",
};

/** "Verificados recentemente" só existe onde há data de verificação. */
const ordensDisponiveis = computed(() =>
  Object.entries(ROTULOS_DE_ORDEM).filter(
    ([valor]) => props.comData || valor !== "recentes"));

function dataLegivel(iso) {
  // `new Date('2026-08-13')` é interpretado como UTC e volta um dia no fuso do
  // Brasil. Formatar a partir das partes evita esse clássico.
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

/** Um chip por filtro ativo, cada um sabendo como se remover. */
const chips = computed(() => {
  const f = filtros.value;
  const lista = [];
  if (f.ordem) {
    lista.push({ chave: "ordem", texto: ROTULOS_DE_ORDEM[f.ordem] || f.ordem });
  }
  if (f.loja) lista.push({ chave: "loja", texto: `Loja: ${f.loja}` });
  if (f.categoria) lista.push({ chave: "categoria", texto: `Categoria: ${f.categoria}` });
  if (f.precoMin !== null && f.precoMin !== undefined && f.precoMin !== "") {
    lista.push({ chave: "precoMin", texto: `A partir de ${formatarBRL(f.precoMin)}` });
  }
  if (f.precoMax !== null && f.precoMax !== undefined && f.precoMax !== "") {
    lista.push({ chave: "precoMax", texto: `Até ${formatarBRL(f.precoMax)}` });
  }
  if (f.desde) lista.push({ chave: "desde", texto: `Desde ${dataLegivel(f.desde)}` });
  if (f.ate) lista.push({ chave: "ate", texto: `Até ${dataLegivel(f.ate)}` });
  return lista;
});

function remover(chave) {
  const novo = { ...filtros.value };
  novo[chave] = chave === "precoMin" || chave === "precoMax" ? null : "";
  filtros.value = novo;
}
</script>

<template>
  <div class="area-filtros">
    <div class="linha">
      <button class="botao-filtro" :class="{ ativo: chips.length }"
              aria-haspopup="dialog" :aria-expanded="String(aberto)"
              @click.stop="aberto ? fechar() : abrir()">
        ⚙ Filtros
        <span v-if="chips.length" class="contador">{{ chips.length }}</span>
      </button>

      <!-- Os chips ficam na MESMA linha do botão: filtro ativo tem de ser
           visível sem abrir nada. -->
      <button v-for="chip in chips" :key="chip.chave" class="chip"
              :aria-label="`Remover filtro: ${chip.texto}`"
              @click="remover(chip.chave)">
        {{ chip.texto }}<span class="x" aria-hidden="true">✕</span>
      </button>

      <button v-if="chips.length > 1" class="limpar" @click="limparTudo">
        limpar tudo
      </button>
    </div>

    <div v-if="aberto" class="painel" role="dialog" aria-label="Filtros" @click.stop>
      <div class="campo-grupo">
        <span class="rotulo-filtro">Ordenar por</span>
        <div class="opcoes">
          <button v-for="[valor, texto] in ordensDisponiveis" :key="valor"
                  :aria-pressed="String(rascunho.ordem === valor)"
                  @click="rascunho.ordem = rascunho.ordem === valor ? '' : valor">
            {{ texto }}
          </button>
        </div>
      </div>

      <div v-if="lojas.length" class="campo-grupo">
        <span class="rotulo-filtro">Loja</span>
        <select v-model="rascunho.loja" class="campo">
          <option value="">todas</option>
          <option v-for="l in lojas" :key="l" :value="l">{{ l }}</option>
        </select>
      </div>

      <div v-if="categorias.length" class="campo-grupo">
        <span class="rotulo-filtro">Categoria</span>
        <select v-model="rascunho.categoria" class="campo">
          <option value="">todas</option>
          <option v-for="c in categorias" :key="c.valor" :value="c.valor">
            {{ c.rotulo }}
          </option>
        </select>
      </div>

      <div class="campo-grupo">
        <span class="rotulo-filtro">Faixa de preço</span>
        <div class="dupla">
          <input v-model="rascunho.precoMin" class="campo mono" inputmode="decimal"
                 placeholder="de 1.000,00" aria-label="Preço mínimo">
          <input v-model="rascunho.precoMax" class="campo mono" inputmode="decimal"
                 placeholder="até 5.000,00" aria-label="Preço máximo">
        </div>
      </div>

      <div v-if="comData" class="campo-grupo">
        <span class="rotulo-filtro">Última verificação</span>
        <div class="dupla">
          <input v-model="rascunho.desde" class="campo" type="date" aria-label="Desde">
          <input v-model="rascunho.ate" class="campo" type="date" aria-label="Até">
        </div>
      </div>

      <p v-if="erro" class="erro">{{ erro }}</p>

      <div class="acoes-painel">
        <button class="botao-discreto" @click="limparTudo">limpar</button>
        <button class="botao-primario" @click="aplicar">Aplicar</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.area-filtros { position: relative; }
.linha {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin-bottom: 18px;
}

.botao-filtro {
  display: inline-flex; align-items: center; gap: 8px;
  border-radius: 999px; padding: 8px 14px; font-size: 13px;
}
.botao-filtro.ativo { border-color: var(--tinta); font-weight: 600; }
.contador {
  background: var(--primario); color: var(--primario-texto);
  border-radius: 999px; min-width: 18px; height: 18px;
  display: inline-grid; place-items: center; font-size: 11px; font-weight: 700;
}

.chip {
  display: inline-flex; align-items: center; gap: 8px;
  border-radius: 999px; padding: 7px 12px; font-size: 12.5px;
  background: var(--suave); border-color: transparent;
}
.chip:hover { border-color: var(--critico); color: var(--critico); }
.chip .x { font-size: 10px; opacity: 0.6; }
.chip:hover .x { opacity: 1; }

.limpar {
  border: none; background: none; font-size: 12.5px; color: var(--tinta-2);
  text-decoration: underline; text-underline-offset: 3px; padding: 4px;
}

.painel {
  position: absolute; top: 44px; left: 0; z-index: 30;
  width: min(420px, calc(100vw - 40px));
  background: var(--superficie);
  border: 1px solid var(--borda); border-radius: 16px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.2);
  padding: 18px; display: grid; gap: 16px;
}
.campo-grupo { display: grid; gap: 8px; }
.rotulo-filtro {
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--tinta-fraca);
}
.opcoes { display: flex; flex-wrap: wrap; gap: 6px; }
.opcoes button {
  border-radius: 999px; padding: 7px 12px; font-size: 12.5px;
}
.opcoes button[aria-pressed="true"] {
  background: var(--primario); color: var(--primario-texto);
  border-color: var(--primario); font-weight: 600;
}
.dupla { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.campo { width: 100%; }
.acoes-painel {
  display: flex; justify-content: flex-end; gap: 10px; align-items: center;
}
</style>
