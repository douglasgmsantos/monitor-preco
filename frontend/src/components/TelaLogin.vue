<script setup>
import { ref } from "vue";
import { useAuth } from "../composables/useAuth.js";

const { entrar, criarConta, entrarComGoogle, traduzir } = useAuth();

const email = ref("");
const senha = ref("");
const erro = ref("");

async function tentar(acao) {
  erro.value = "";
  try {
    if (acao === "entrar") await entrar(email.value, senha.value);
    else if (acao === "criar") await criarConta(email.value, senha.value);
    else await entrarComGoogle();
  } catch (excecao) {
    erro.value = traduzir(excecao);
  }
}
</script>

<template>
  <section class="palco">
    <div class="cartao caixa">
      <span class="marca"><span class="ponto bom"></span> Radar</span>
      <p class="dica sub">Monitor pessoal de preços. Entre para ver seu radar.</p>

      <label class="rotulo-campo" for="email">E-mail</label>
      <input id="email" v-model="email" class="campo" type="email"
             autocomplete="email" placeholder="voce@exemplo.com"
             @keyup.enter="tentar('entrar')">

      <label class="rotulo-campo" for="senha">Senha</label>
      <input id="senha" v-model="senha" class="campo" type="password"
             autocomplete="current-password" placeholder="••••••••"
             @keyup.enter="tentar('entrar')">

      <button class="botao-primario" @click="tentar('entrar')">Entrar</button>
      <button class="botao-discreto" @click="tentar('criar')">Criar conta com este e-mail</button>
      <button @click="tentar('google')">Entrar com Google</button>

      <p v-if="erro" class="erro">{{ erro }}</p>
    </div>
  </section>
</template>

<style scoped>
.palco {
  min-height: 100vh; display: grid; place-items: center;
  background: var(--plano); padding: 24px;
}
.caixa {
  width: 100%; max-width: 400px;
  padding: 32px; display: grid; gap: 12px;
}
.marca {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 22px; font-weight: 700;
}
.sub { margin: -6px 0 10px; }
</style>
