<script setup>
// O selo do cartão, com o vocabulário do desenho:
//   EM_ALERTA          -> ALERTA DE PREÇO BAIXO (vermelho)
//   pausado            -> PAUSADO (neutro)
//   nenhuma fonte ok   -> AGUARDANDO PRIMEIRA COLETA (laranja)
//   caso normal        -> MONITORANDO (neutro)
import { computed } from "vue";

const props = defineProps({
  produto: { type: Object, required: true },
});

const selo = computed(() => {
  const { dados, fontes } = props.produto;
  if (dados.ativo === false) return { classe: "neutro", texto: "Pausado" };
  if (dados.estado === "EM_ALERTA") return { classe: "alerta", texto: "Alerta de preço baixo" };
  const algumaOk = fontes.some((f) => f.status === "ok");
  if (!algumaOk) return { classe: "aguardando", texto: "Aguardando primeira coleta" };
  return { classe: "neutro", texto: "Monitorando" };
});
</script>

<template>
  <span class="selo" :class="selo.classe">{{ selo.texto }}</span>
</template>
