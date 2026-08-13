// O bot de Telegram de cada usuário.
//
// POR QUE POR USUÁRIO: o bot global vive num GitHub Secret e manda tudo para um
// chat só. Com dois usuários, o segundo receberia alerta de produto que não é
// dele — ou nada. Cada um aponta o próprio bot.
//
// O token é segredo DO USUÁRIO, não do sistema: fica em
// `usuarios/{uid}/config/telegram`, que só o dono lê e escreve (ver
// firestore.rules). O coletor lê pelo Admin SDK, que ignora rules.
//
// A API de bot do Telegram responde com `access-control-allow-origin: *`
// (verificado em 2026-08-13), então o navegador fala direto com ela. É isso que
// permite validar o token, descobrir o chat e mandar teste sem backend nenhum.
import { ref } from "vue";
import { deleteDoc, doc, getDoc, serverTimestamp, setDoc } from "firebase/firestore";
import { db } from "../firebase.js";

const config = ref(null);
const carregado = ref(false);

const API = "https://api.telegram.org";

export async function carregarConfigTelegram(uid) {
  if (!uid) return;
  try {
    const instantaneo = await getDoc(doc(db, `usuarios/${uid}/config/telegram`));
    config.value = instantaneo.exists() ? instantaneo.data() : null;
  } catch (erro) {
    console.error("falha ao ler a configuração do Telegram", erro);
    config.value = null;
  } finally {
    carregado.value = true;
  }
}

export async function salvarConfigTelegram(uid, { botToken, chatId, nomeDoBot }) {
  const dados = {
    botToken: botToken.trim(),
    chatId: String(chatId).trim(),
    nomeDoBot: nomeDoBot || "",
    atualizadoEm: serverTimestamp(),
  };
  await setDoc(doc(db, `usuarios/${uid}/config/telegram`), dados);
  config.value = dados;
}

export async function apagarConfigTelegram(uid) {
  await deleteDoc(doc(db, `usuarios/${uid}/config/telegram`));
  config.value = null;
}

export function limparConfigTelegram() {
  config.value = null;
  carregado.value = false;
}

// ---------------------------------------------------------------------------
// Conversa direta com a API do Telegram
// ---------------------------------------------------------------------------

async function chamar(token, metodo, corpo) {
  const resposta = await fetch(`${API}/bot${token.trim()}/${metodo}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo || {}),
  });
  const dados = await resposta.json().catch(() => ({}));
  if (!dados.ok) {
    // `description` é a mensagem do próprio Telegram e costuma ser específica
    // ("Unauthorized", "chat not found"). Repassá-la evita o clássico "erro ao
    // salvar" que não diz o que arrumar.
    throw new Error(dados.description || `Telegram recusou (${resposta.status})`);
  }
  return dados.result;
}

/** Valida o token e devolve o @usuario do bot. */
export async function verificarToken(token) {
  const bot = await chamar(token, "getMe");
  return { nome: bot.first_name || "", usuario: bot.username || "" };
}

/** Descobre o chat a partir das mensagens que o bot recebeu.
 *
 *  É por isso que o passo a passo manda o usuário enviar /start: sem uma
 *  mensagem dele, o Telegram não tem chat nenhum para informar, e não existe
 *  outra forma de um bot descobrir com quem falar.
 */
export async function descobrirChat(token) {
  const atualizacoes = await chamar(token, "getUpdates", { limit: 10 });
  for (const item of [...atualizacoes].reverse()) {
    const chat = item.message?.chat || item.channel_post?.chat;
    if (chat?.id) {
      return {
        id: String(chat.id),
        titulo: chat.title || [chat.first_name, chat.last_name].filter(Boolean).join(" ")
                || chat.username || String(chat.id),
      };
    }
  }
  return null;
}

export async function enviarTeste(token, chatId, texto) {
  await chamar(token, "sendMessage", {
    chat_id: chatId,
    text: texto,
    link_preview_options: { is_disabled: true },
  });
}

export function useConfigTelegram() {
  return {
    config, carregado,
    carregarConfigTelegram, salvarConfigTelegram, apagarConfigTelegram,
    limparConfigTelegram, verificarToken, descobrirChat, enviarTeste,
  };
}
