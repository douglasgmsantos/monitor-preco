<script setup>
import { useAuth } from "../composables/useAuth.js";

defineProps({
  aba: { type: String, required: true },
  email: { type: String, default: "" },
});
defineEmits(["trocar-aba", "novo-produto"]);

const { sair } = useAuth();

function alternarTema() {
  const raiz = document.documentElement;
  const atual = raiz.getAttribute("data-theme");
  const escuroAgora =
    atual === "dark" ||
    (!atual && matchMedia("(prefers-color-scheme: dark)").matches);
  raiz.setAttribute("data-theme", escuroAgora ? "light" : "dark");
}
</script>

<template>
  <header class="topo">
    <div class="interno">
      <span class="marca"><span class="ponto bom"></span> Radar</span>

      <nav class="abas" aria-label="Seções">
        <button
          :class="{ ativa: aba === 'monitoramento' }"
          @click="$emit('trocar-aba', 'monitoramento')"
        >Monitoramento</button>
        <button
          :class="{ ativa: aba === 'catalogo' }"
          @click="$emit('trocar-aba', 'catalogo')"
        >Catálogo</button>
      </nav>

      <div class="espaco"></div>

      <span class="quem dica" :title="email">{{ email }}</span>
      <button class="botao-discreto" title="Alternar tema" @click="alternarTema">◐</button>
      <button class="botao-discreto" @click="sair">Sair</button>
      <button class="botao-primario" @click="$emit('novo-produto')">+ Novo produto</button>
    </div>
  </header>
</template>

<style scoped>
.topo {
  position: sticky; top: 0; z-index: 10;
  background: var(--superficie);
  border-bottom: 1px solid var(--borda);
}
.interno {
  max-width: 1180px; margin: 0 auto;
  display: flex; align-items: center; gap: 18px;
  padding: 12px 28px;
}
.marca {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 17px; font-weight: 700; letter-spacing: -0.01em;
}
.abas { display: inline-flex; gap: 4px; }
.abas button {
  border: none; background: none; color: var(--tinta-2);
  font-weight: 600; border-radius: 999px; padding: 8px 18px;
}
.abas button:hover { background: var(--suave); }
.abas button.ativa {
  background: var(--primario); color: var(--primario-texto);
}
.espaco { flex: 1; }
.quem { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 700px) {
  .interno { padding: 10px 16px; gap: 10px; }
  .quem { display: none; }
}
</style>
