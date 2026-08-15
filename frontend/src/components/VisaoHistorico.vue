<script setup>
// O que já foi avisado, e o que exatamente foi avisado.
//
// A mensagem exibida é a que FOI ENVIADA, gravada pelo coletor no momento do
// disparo — não é remontada aqui. O formato da mensagem já mudou uma vez; se
// esta tela a reconstruísse com o código de hoje, mostraria um texto que o
// usuário nunca recebeu, exatamente quando ele veio conferir o que recebeu.
//
// O preço também é o do disparo. Ele é o registro do porquê do alerta; o preço
// de agora fica no cartão do produto, onde muda o tempo todo.
import { computed, ref, watch } from "vue";
import { formatarBRL } from "../dinheiro.js";
import { casaTermos } from "../busca.js";
import { encurtarUrl, siglaDaLoja } from "../lojas.js";
import { useAuth } from "../composables/useAuth.js";
import { useNotificacoes } from "../composables/useNotificacoes.js";

const { usuario } = useAuth();
const {
  notificacoes, carregando, carregado, carregarNotificacoes, apagarNotificacao,
} = useNotificacoes();

const busca = ref("");
const abertaId = ref(null);

// Nada de listener em tempo real: notificação é passado, não muda sozinha.
// Uma leitura ao abrir a aba é mais barata e não fica escutando à toa.
watch(usuario, (quem) => {
  if (quem && !carregado.value) carregarNotificacoes(quem.uid);
}, { immediate: true });

const filtradas = computed(() => {
  if (!busca.value.trim()) return notificacoes.value;
  return notificacoes.value.filter((n) => casaTermos(busca.value, n.nome, n.loja));
});

// Agrupa por dia. Ver "12 de agosto" uma vez acima de quatro alertas lê melhor
// que a data repetida em quatro linhas seguidas.
const porDia = computed(() => {
  const grupos = [];
  for (const item of filtradas.value) {
    const dia = rotuloDoDia(item.quando);
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.dia === dia) ultimo.itens.push(item);
    else grupos.push({ dia, itens: [item] });
  }
  return grupos;
});

const formatoDia = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit", month: "long", year: "numeric",
});
const formatoHora = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit", minute: "2-digit",
});

function rotuloDoDia(data) {
  if (!(data instanceof Date) || Number.isNaN(data.getTime())) return "sem data";
  const hoje = new Date();
  const mesmoDia = (a, b) => a.toDateString() === b.toDateString();
  if (mesmoDia(data, hoje)) return "Hoje";
  const ontem = new Date(hoje);
  ontem.setDate(ontem.getDate() - 1);
  if (mesmoDia(data, ontem)) return "Ontem";
  return formatoDia.format(data);
}

function hora(data) {
  return data instanceof Date && !Number.isNaN(data.getTime())
    ? formatoHora.format(data) : "—";
}

function alternar(id) {
  abertaId.value = abertaId.value === id ? null : id;
}

async function apagar(item) {
  if (!confirm(`Remover o registro de "${item.nome}" do histórico?`)) return;
  try {
    await apagarNotificacao(usuario.value.uid, item.id);
  } catch (erro) {
    console.error("falha ao apagar a notificação", erro);
  }
}
</script>

<template>
  <div>
    <p class="olho">Histórico</p>
    <h2 class="titulo-secao">Alertas já enviados</h2>
    <p class="dica aviso">
      O preço e o texto abaixo são os do momento do envio — não o preço de agora.
    </p>

    <div class="filtros">
      <input v-model="busca" class="busca" placeholder="9070 kabum — vários termos, todos precisam aparecer">
      <span class="dica">{{ filtradas.length }} alerta(s)</span>
    </div>

    <div v-for="grupo in porDia" :key="grupo.dia" class="grupo">
      <p class="dia">{{ grupo.dia }}</p>

      <article
        v-for="item in grupo.itens"
        :key="item.id"
        class="cartao registro"
        :class="{ aberta: abertaId === item.id }"
      >
        <div class="cabeca">
          <div class="moldura">
            <img v-if="item.imagem" :src="item.imagem" alt="" loading="lazy">
            <span v-else class="sigla mono">{{ siglaDaLoja(item.loja) }}</span>
          </div>

          <div class="identidade">
            <span class="nome" :title="item.nome">{{ item.nome }}</span>
            <a v-if="item.url" class="endereco" :href="item.url"
               target="_blank" rel="noopener noreferrer" :title="item.url">
              {{ item.loja || "loja" }} · {{ encurtarUrl(item.url) }} ↗
            </a>
            <span v-else class="endereco">{{ item.loja || "loja não registrada" }}</span>
          </div>

          <div class="coluna">
            <span class="rotulo">Enviado</span>
            <span class="valor mono">{{ hora(item.quando) }}</span>
          </div>

          <div class="coluna">
            <span class="rotulo">Preço no alerta</span>
            <span class="valor mono preco">{{ formatarBRL(item.precoCentavos) }}</span>
          </div>

          <div class="acoes">
            <button class="botao-discreto" @click="alternar(item.id)">
              {{ abertaId === item.id ? "ocultar" : "ver mensagem" }}
            </button>
            <button class="botao-discreto perigo" @click="apagar(item)">remover</button>
          </div>
        </div>

        <div v-if="abertaId === item.id" class="detalhe">
          <span class="rotulo">Mensagem enviada</span>
          <pre class="mensagem">{{ item.mensagem || "(texto não registrado)" }}</pre>
          <p v-if="item.motivo" class="dica">Motivo: {{ item.motivo }}</p>
        </div>
      </article>
    </div>

    <p v-if="!filtradas.length && carregado" class="vazio">
      {{ notificacoes.length
        ? "Nenhum alerta com esse filtro."
        : "Nenhum alerta enviado ainda. Quando um preço bater o seu valor máximo, ele aparece aqui." }}
    </p>
    <p v-else-if="!filtradas.length && carregando" class="vazio">Carregando…</p>
  </div>
</template>

<style scoped>
.aviso { margin: -12px 0 20px; }
.filtros {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  margin-bottom: 22px;
}
.busca { flex: 1; min-width: 180px; }

.grupo { margin-bottom: 26px; }
.dia {
  margin: 0 0 10px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--tinta-fraca);
}

.registro { padding: 14px 18px; margin-bottom: 10px; }
.cabeca { display: flex; align-items: center; gap: 16px; min-width: 0; }

.moldura {
  width: 46px; height: 46px; flex: none;
  border-radius: 10px; overflow: hidden; background: var(--suave);
  display: grid; place-items: center;
}
.moldura img { width: 100%; height: 100%; object-fit: contain; display: block; }
.sigla { font-size: 11px; font-weight: 700; color: var(--tinta-2); }

.identidade { flex: 1 1 auto; min-width: 0; display: grid; gap: 2px; }
.nome {
  font-weight: 650; font-size: 15px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.endereco {
  color: var(--tinta-fraca); font-size: 12.5px; text-decoration: none;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.endereco:hover { color: var(--tinta); text-decoration: underline; }

.coluna { display: grid; gap: 2px; justify-items: end; flex: none; }
.rotulo {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--tinta-fraca);
}
.valor { font-size: 14px; font-weight: 600; }
.valor.preco { font-size: 16px; color: var(--bom); }
.acoes { display: flex; gap: 2px; flex: none; }
.acoes button { font-size: 12px; }

.detalhe {
  margin-top: 14px; padding-top: 14px;
  border-top: 1px solid var(--borda);
  display: grid; gap: 8px;
}
/* A mensagem sai em <pre> de propósito: o que o Telegram recebeu tem quebras de
   linha que fazem parte do formato. Reflow aqui mostraria outra coisa. */
.mensagem {
  margin: 0; padding: 12px 14px;
  background: var(--suave); border-radius: 12px;
  font-family: var(--fonte-mono); font-size: 12.5px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
}

@media (max-width: 760px) {
  .cabeca { flex-wrap: wrap; }
  .identidade { flex-basis: calc(100% - 62px); }
  .coluna { justify-items: start; }
  .acoes { margin-left: auto; }
}
</style>
