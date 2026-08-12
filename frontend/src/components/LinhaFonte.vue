<script setup>
// Uma fonte na análise detalhada: sigla, loja, URL, STATUS e PREÇO.
//
// O status segue o vocabulário do desenho, mas o mapa vem do modelo real:
//   comErro                    -> ERRO DE COLETA (vermelho, borda vermelha)
//   status invalida            -> INVÁLIDA (vermelho, motivo no title)
//   status pendente            -> VALIDANDO (laranja; com contagem de falhas)
//   ok sem preço               -> INDISPONÍVEL (apagado)
//   ok                         -> OK (verde)
import { computed } from "vue";
import { formatarBRL } from "../dinheiro.js";
import { encurtarUrl, siglaDaLoja } from "../lojas.js";
import { explicar } from "../composables/useProdutos.js";

const props = defineProps({
  fonte: { type: Object, required: true },
});
defineEmits(["retentar", "remover"]);

const situacao = computed(() => {
  const f = props.fonte;
  if (f.comErro) {
    return { texto: "Erro de coleta", ponto: "critico", classe: "erro",
             motivo: "desativada após 5 falhas seguidas" };
  }
  if (f.status === "invalida") {
    return { texto: "Inválida", ponto: "critico", classe: "erro", motivo: explicar(f.motivoInvalida) };
  }
  if (f.status === "pendente") {
    const falhas = f.falhasSeguidas || 0;
    return {
      texto: falhas > 0 ? `Validando (tentativa ${falhas + 1})` : "Validando",
      ponto: "atencao", classe: "", motivo: null,
    };
  }
  if (typeof f.ultimoPrecoCentavos !== "number") {
    return { texto: "Indisponível", ponto: "fraco", classe: "apagada", motivo: null };
  }
  return { texto: "OK", ponto: "bom", classe: "", motivo: null };
});

const quebrada = computed(() => props.fonte.comErro || props.fonte.status === "invalida");
</script>

<template>
  <div class="linha cartao" :class="situacao.classe">
    <span class="sigla mono">{{ siglaDaLoja(fonte.loja) }}</span>

    <div class="identidade">
      <span class="loja">{{ fonte.loja }}</span>
      <a class="endereco" :href="fonte.url" target="_blank" rel="noopener noreferrer"
         :title="fonte.url" @click.stop>{{ encurtarUrl(fonte.url) }}</a>
    </div>

    <div class="coluna">
      <span class="rotulo">Status</span>
      <span class="valor-status" :title="situacao.motivo || undefined">
        <span class="ponto" :class="situacao.ponto"></span> {{ situacao.texto }}
      </span>
    </div>

    <div class="coluna preco">
      <span class="rotulo">Preço</span>
      <span class="mono valor">{{
        typeof fonte.ultimoPrecoCentavos === "number"
          ? formatarBRL(fonte.ultimoPrecoCentavos) : "———"
      }}</span>
    </div>

    <div v-if="quebrada" class="acoes">
      <button class="botao-discreto" title="Volta a fonte para a fila de validação"
              @click="$emit('retentar')">↻ tentar de novo</button>
      <button class="botao-discreto perigo" @click="$emit('remover')">remover</button>
    </div>
  </div>
</template>

<style scoped>
.linha {
  border-radius: 14px;
  padding: 14px 18px;
  display: flex; align-items: center; gap: 16px;
  min-width: 0;
}
.linha.erro { border-color: var(--critico); }
.linha.apagada { opacity: 0.6; }

.sigla {
  width: 44px; height: 44px; flex: none;
  border-radius: 10px; background: var(--suave);
  display: grid; place-items: center;
  font-size: 11px; font-weight: 700; color: var(--tinta-2);
}
.identidade { flex: 1 1 auto; min-width: 0; display: grid; gap: 1px; }
.loja { font-weight: 650; font-size: 15px; }
.endereco {
  color: var(--tinta-fraca); font-size: 13px; text-decoration: none;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.endereco:hover { color: var(--tinta); text-decoration: underline; }

.coluna { display: grid; gap: 2px; justify-items: end; flex: none; }
.rotulo {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--tinta-fraca);
}
.valor-status {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 13px; font-weight: 650; text-transform: uppercase;
  letter-spacing: 0.03em;
}
.preco .valor { font-size: 16px; font-weight: 600; }
.acoes { display: flex; gap: 2px; flex: none; }
.acoes button { font-size: 12px; }

@media (max-width: 640px) {
  .linha { flex-wrap: wrap; }
  .identidade { flex-basis: calc(100% - 60px); }
  .coluna { justify-items: start; }
}
</style>
