<script setup>
// Cartão compacto da faixa "Descoberta". O desenho original traz "Monitorado
// por 1.2k usuários", mas esse dado NÃO existe no sistema (não há contagem de
// usuários por produto) — em vez de inventar, a sublinha mostra o que é real:
// preço de vitrine e loja.
import { formatarBRL } from "../dinheiro.js";
import { hostDaUrl } from "../lojas.js";

defineProps({
  item: { type: Object, required: true },   // item do catálogo
  jaSegue: { type: Boolean, default: false },
});
defineEmits(["acompanhar"]);
</script>

<template>
  <article class="cartao descoberta">
    <div class="thumb">
      <img v-if="item.imagem" :src="item.imagem" alt="" loading="lazy">
      <span v-else aria-hidden="true">🖥</span>
    </div>
    <div class="texto">
      <span class="categoria">{{ item.categoria }}</span>
      <span class="nome" :title="item.nome">{{ item.nome }}</span>
      <span class="dica">{{ formatarBRL(item.preco) }} · {{ hostDaUrl(item.url) || item.loja }}</span>
    </div>
    <button
      class="mais"
      :disabled="jaSegue"
      :title="jaSegue ? 'Você já acompanha este produto' : 'Acompanhar este produto'"
      @click="$emit('acompanhar')"
    >{{ jaSegue ? "✓" : "+" }}</button>
  </article>
</template>

<style scoped>
.descoberta {
  padding: 14px 16px;
  display: flex; align-items: center; gap: 14px;
  min-width: 0;
}
.thumb {
  width: 56px; height: 56px; flex: none;
  border-radius: 12px; background: var(--suave);
  display: grid; place-items: center; overflow: hidden;
  font-size: 22px;
}
.thumb img { width: 100%; height: 100%; object-fit: contain; }
.texto { flex: 1 1 auto; min-width: 0; display: grid; gap: 1px; }
.categoria {
  font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--tinta-fraca);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.nome {
  font-size: 14px; font-weight: 650; line-height: 1.3;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mais {
  width: 42px; height: 42px; flex: none;
  border-radius: 50%; font-size: 19px; font-weight: 500;
  display: grid; place-items: center; padding: 0;
}
.mais:disabled { color: var(--bom); border-color: var(--borda); cursor: default; }
</style>
