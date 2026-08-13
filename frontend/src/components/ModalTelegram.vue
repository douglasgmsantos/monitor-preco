<script setup>
// Passo a passo para o usuário ligar o próprio bot do Telegram.
//
// Três passos, e cada um só abre quando o anterior deu certo. É deliberado:
// pedir token e chat_id juntos num formulário produz o erro mais comum dessa
// configuração — o usuário cola o token, inventa o chat_id, salva, e descobre
// dias depois que nunca recebeu nada. Aqui cada passo é VERIFICADO contra a
// API antes de liberar o seguinte.
//
// O chat_id não é digitado: ele é descoberto. Um bot só sabe com quem falar
// depois de receber uma mensagem — daí o passo 2 mandar o usuário dar /start.
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useAuth } from "../composables/useAuth.js";
import { useConfigTelegram } from "../composables/useConfigTelegram.js";

defineProps({
  // true quando o modal abriu sozinho no primeiro login, e não pelo menu.
  primeiraVez: { type: Boolean, default: false },
});
const emit = defineEmits(["fechar"]);

const { usuario } = useAuth();
const {
  config, salvarConfigTelegram, apagarConfigTelegram,
  verificarToken, descobrirChat, enviarTeste,
} = useConfigTelegram();

const token = ref(config.value?.botToken || "");
const bot = ref(config.value?.nomeDoBot ? { usuario: config.value.nomeDoBot } : null);
const chat = ref(config.value?.chatId
  ? { id: config.value.chatId, titulo: "chat já configurado" } : null);

const erro = ref("");
const ocupado = ref(false);
const salvo = ref(false);

const passo = computed(() => {
  if (!bot.value) return 1;
  if (!chat.value) return 2;
  return 3;
});

async function tentar(acao) {
  erro.value = "";
  ocupado.value = true;
  try {
    await acao();
  } catch (excecao) {
    erro.value = excecao.message || String(excecao);
  } finally {
    ocupado.value = false;
  }
}

const validarToken = () => tentar(async () => {
  bot.value = await verificarToken(token.value);
  chat.value = null;
});

const procurarChat = () => tentar(async () => {
  const achado = await descobrirChat(token.value);
  if (!achado) {
    throw new Error(
      "Nenhuma mensagem encontrada. Abra a conversa com o bot e envie /start — " +
      "sem isso o Telegram não informa o chat.",
    );
  }
  chat.value = achado;
});

const salvar = () => tentar(async () => {
  await enviarTeste(
    token.value, chat.value.id,
    "✅ Pronto! É por aqui que os alertas de preço vão chegar.",
  );
  await salvarConfigTelegram(usuario.value.uid, {
    botToken: token.value,
    chatId: chat.value.id,
    nomeDoBot: bot.value.usuario,
  });
  salvo.value = true;
});

const desconectar = () => tentar(async () => {
  await apagarConfigTelegram(usuario.value.uid);
  token.value = ""; bot.value = null; chat.value = null; salvo.value = false;
});

function recomecar() {
  bot.value = null; chat.value = null; salvo.value = false; erro.value = "";
}

function aoTeclar(evento) {
  if (evento.key === "Escape") emit("fechar");
}
onMounted(() => document.addEventListener("keydown", aoTeclar));
onUnmounted(() => document.removeEventListener("keydown", aoTeclar));
</script>

<template>
  <div class="veu" @click.self="emit('fechar')">
    <div class="janela" role="dialog" aria-modal="true" aria-label="Configurar Telegram">
      <header class="topo">
        <div>
          <h2 class="titulo">Receber alertas no Telegram</h2>
          <p class="dica sub">
            <template v-if="primeiraVez">
              Sem isto o sistema monitora os preços, mas não tem para onde te avisar.
              Leva um minuto — e dá para fazer depois, pelo menu.
            </template>
            <template v-else>
              Seu próprio bot, no seu Telegram. Nada passa por outro chat.
            </template>
          </p>
        </div>
        <button class="fechar" aria-label="Fechar" @click="emit('fechar')">✕</button>
      </header>

      <!-- Passo 1 -->
      <section class="passo" :class="{ feito: passo > 1, atual: passo === 1 }">
        <span class="numero">{{ passo > 1 ? "✓" : "1" }}</span>
        <div class="corpo">
          <h3>Crie um bot no Telegram</h3>
          <p class="dica">
            Abra <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a>,
            envie <code>/newbot</code> e siga as perguntas. No fim ele devolve um
            token parecido com <code>8661140522:AAF...</code>.
          </p>
          <div v-if="passo === 1" class="linha-campo">
            <input v-model="token" class="campo mono" placeholder="cole o token aqui"
                   autocomplete="off" @keyup.enter="validarToken">
            <button class="botao-primario" :disabled="!token.trim() || ocupado"
                    @click="validarToken">
              {{ ocupado ? "Verificando…" : "Verificar" }}
            </button>
          </div>
          <p v-else class="confirmado">
            Bot <strong>@{{ bot.usuario }}</strong> conectado.
            <button class="ligacao" @click="recomecar">trocar</button>
          </p>
        </div>
      </section>

      <!-- Passo 2 -->
      <section class="passo" :class="{ feito: passo > 2, atual: passo === 2 }">
        <span class="numero">{{ passo > 2 ? "✓" : "2" }}</span>
        <div class="corpo">
          <h3>Diga oi para o seu bot</h3>
          <p class="dica">
            Um bot só consegue te escrever depois que você fala com ele primeiro —
            é regra do Telegram, não do sistema.
          </p>
          <template v-if="passo === 2">
            <p>
              <a v-if="bot.usuario" class="botao-link"
                 :href="`https://t.me/${bot.usuario}`" target="_blank" rel="noopener">
                Abrir @{{ bot.usuario }} ↗
              </a>
              <span class="dica"> e envie <code>/start</code></span>
            </p>
            <button class="botao-primario" :disabled="ocupado" @click="procurarChat">
              {{ ocupado ? "Procurando…" : "Já enviei, procurar" }}
            </button>
          </template>
          <p v-else-if="passo > 2" class="confirmado">
            Conversa encontrada: <strong>{{ chat.titulo }}</strong>
          </p>
        </div>
      </section>

      <!-- Passo 3 -->
      <section class="passo" :class="{ atual: passo === 3, feito: salvo }">
        <span class="numero">{{ salvo ? "✓" : "3" }}</span>
        <div class="corpo">
          <h3>Confirme</h3>
          <template v-if="passo === 3 && !salvo">
            <p class="dica">
              Vamos enviar uma mensagem de teste. Se ela chegar, está tudo certo.
            </p>
            <button class="botao-primario" :disabled="ocupado" @click="salvar">
              {{ ocupado ? "Enviando…" : "Enviar teste e salvar" }}
            </button>
          </template>
          <p v-else-if="salvo" class="confirmado">
            Salvo. Os próximos alertas vão para <strong>{{ chat.titulo }}</strong>.
          </p>
          <p v-else class="dica">Conclua os passos acima.</p>
        </div>
      </section>

      <p v-if="erro" class="erro">{{ erro }}</p>

      <footer class="acoes">
        <button v-if="config" class="botao-discreto perigo" :disabled="ocupado"
                @click="desconectar">
          desconectar este bot
        </button>
        <div class="espaco"></div>
        <button class="botao-primario" @click="emit('fechar')">
          {{ salvo ? "Fechar" : (primeiraVez ? "Fazer isso depois" : "Fechar") }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.veu {
  position: fixed; inset: 0; z-index: 60;
  background: rgba(10, 10, 10, 0.45);
  backdrop-filter: blur(6px);
  display: grid; place-items: center;
  padding: 20px; overflow-y: auto;
}
.janela {
  width: 100%; max-width: 620px;
  background: var(--superficie);
  border-radius: 20px; padding: 28px 30px;
  display: grid; gap: 18px;
  max-height: calc(100vh - 40px); overflow-y: auto;
}
.topo { display: flex; align-items: flex-start; gap: 16px; }
.titulo { margin: 0 0 4px; font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }
.sub { margin: 0; }
.fechar {
  border: none; background: none; font-size: 16px; color: var(--tinta-2);
  padding: 4px 8px; border-radius: 8px; flex: none;
}
.fechar:hover { background: var(--suave); color: var(--tinta); }

.passo {
  display: flex; gap: 14px; align-items: flex-start;
  padding: 16px; border-radius: 14px;
  border: 1px solid var(--borda);
  /* O passo inativo fica apagado, mas VISÍVEL: esconder os próximos tiraria
     do usuário a noção de quanto falta. */
  opacity: 0.55;
}
.passo.atual { opacity: 1; border-color: var(--tinta); }
.passo.feito { opacity: 1; border-color: var(--bom); }
.numero {
  width: 26px; height: 26px; flex: none; border-radius: 999px;
  background: var(--suave); color: var(--tinta-2);
  display: grid; place-items: center;
  font-size: 12px; font-weight: 700;
}
.passo.feito .numero { background: var(--bom); color: #fff; }
.passo.atual .numero { background: var(--tinta); color: var(--superficie); }
.corpo { display: grid; gap: 8px; min-width: 0; flex: 1; }
.corpo h3 { margin: 0; font-size: 15px; font-weight: 650; }
.corpo p { margin: 0; }
code {
  background: var(--suave); border-radius: 5px; padding: 1px 5px;
  font-family: var(--fonte-mono); font-size: 12px;
}
.linha-campo { display: flex; gap: 8px; flex-wrap: wrap; }
.linha-campo .campo { flex: 1; min-width: 200px; font-size: 13px; }
.confirmado { font-size: 13.5px; }
.ligacao {
  border: none; background: none; padding: 0 0 0 6px; font-size: 13px;
  color: var(--tinta-2); text-decoration: underline; text-underline-offset: 3px;
}
.botao-link {
  display: inline-block; text-decoration: none;
  border: 1px solid var(--borda); border-radius: 10px;
  padding: 7px 12px; font-size: 13px; font-weight: 600; color: var(--tinta);
}
.botao-link:hover { background: var(--suave); }

.acoes { display: flex; gap: 10px; align-items: center; }
.acoes .espaco { flex: 1; }
</style>
