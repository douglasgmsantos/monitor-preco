<script setup>
import { ref, watch, nextTick } from "vue";
import { useAuth } from "./composables/useAuth.js";
import { useProdutos } from "./composables/useProdutos.js";
import { useCatalogo } from "./composables/useCatalogo.js";
import TelaLogin from "./components/TelaLogin.vue";
import TopoRadar from "./components/TopoRadar.vue";
import VisaoMonitoramento from "./components/VisaoMonitoramento.vue";
import VisaoCatalogo from "./components/VisaoCatalogo.vue";
import ModalProduto from "./components/ModalProduto.vue";

const { usuario, carregouAuth } = useAuth();
const { produtos, observar, parar } = useProdutos();
const { carregarCatalogo } = useCatalogo();

const aba = ref("monitoramento");        // "monitoramento" | "catalogo"
const selecionadoId = ref(null);
const modal = ref({ aberto: false, produtoId: null, prefill: null });

watch(usuario, (quem) => {
  if (quem) {
    observar(quem.uid);
    carregarCatalogo();
  } else {
    parar();
    selecionadoId.value = null;
    aba.value = "monitoramento";
  }
}, { immediate: true });

// Sem seleção (ou seleção apagada), o primeiro produto assume — igual ao
// front antigo, para a análise detalhada nunca apontar para o vazio.
watch(produtos, (lista) => {
  if (!selecionadoId.value || !lista.some((p) => p.id === selecionadoId.value)) {
    selecionadoId.value = lista.length ? lista[0].id : null;
  }
}, { deep: false });

function abrirCriacao(prefill = null) {
  modal.value = { aberto: true, produtoId: null, prefill };
}

function abrirEdicao(produtoId) {
  modal.value = { aberto: true, produtoId, prefill: null };
}

function fecharModal() {
  modal.value = { aberto: false, produtoId: null, prefill: null };
}

function aoSalvar(produtoId) {
  selecionadoId.value = produtoId;
  fecharModal();
  aba.value = "monitoramento";
}

/** Acompanhar do catálogo: pré-preenche o cadastro — o preço-alvo é a única
 *  informação que o catálogo não tem, então a decisão fica com o usuário. */
function acompanhar(prefill) {
  abrirCriacao(prefill);
}

async function verDetalhes(produtoId) {
  selecionadoId.value = produtoId;
  aba.value = "monitoramento";
  await nextTick();
  document.getElementById("analise")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<template>
  <TelaLogin v-if="carregouAuth && !usuario" />

  <template v-else-if="usuario">
    <TopoRadar
      :aba="aba"
      :email="usuario.email || usuario.displayName || ''"
      @trocar-aba="aba = $event"
      @novo-produto="abrirCriacao()"
    />

    <main class="envelope">
      <VisaoMonitoramento
        v-if="aba === 'monitoramento'"
        :selecionado-id="selecionadoId"
        @selecionar="selecionadoId = $event"
        @ver-detalhes="verDetalhes"
        @editar="abrirEdicao"
        @acompanhar="acompanhar"
        @novo-produto="abrirCriacao()"
        @ir-catalogo="aba = 'catalogo'"
      />
      <VisaoCatalogo v-else @acompanhar="acompanhar" />
    </main>

    <ModalProduto
      v-if="modal.aberto"
      :produto-id="modal.produtoId"
      :prefill="modal.prefill"
      @fechar="fecharModal"
      @salvo="aoSalvar"
    />
  </template>
</template>

<style scoped>
.envelope {
  max-width: 1180px;
  margin: 0 auto;
  padding: 36px 28px 80px;
}
@media (max-width: 640px) {
  .envelope { padding: 24px 16px 64px; }
}
</style>
