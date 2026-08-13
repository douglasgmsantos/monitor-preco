// Diário do que foi NOTIFICADO. Responde outra pergunta que o histórico de
// preço: aquele diz "quanto custava", este diz "o que te avisamos, e quando".
//
// Escrito só pelo coletor (Admin SDK). O cliente lê e pode apagar — apagar o
// próprio registro não é forjá-lo, e criar/alterar seguem bloqueados nas rules.
import { ref } from "vue";
import {
  collection, deleteDoc, doc, getDocs, limit, orderBy, query,
} from "firebase/firestore";
import { db } from "../firebase.js";

// Teto por carregamento. Um alerta a cada 24h por produto (o cooldown) com
// alguns produtos rende dezenas por mês; 200 cobre meses de uso sem transformar
// a abertura da aba numa leitura de coleção inteira.
const LIMITE = 200;

const notificacoes = ref([]);
const carregando = ref(false);
const carregado = ref(false);

export async function carregarNotificacoes(uid) {
  if (!uid) return;
  carregando.value = true;
  try {
    const consulta = query(
      collection(db, `usuarios/${uid}/notificacoes`),
      orderBy("enviadaEm", "desc"),
      limit(LIMITE),
    );
    const instantaneo = await getDocs(consulta);
    notificacoes.value = instantaneo.docs.map((d) => {
      const dados = d.data();
      const quando = dados.enviadaEm;
      return {
        id: d.id,
        ...dados,
        // Timestamp do Firestore vira Date aqui, uma vez, em vez de em cada
        // componente que for exibir.
        quando: quando?.toDate ? quando.toDate() : new Date(quando),
      };
    });
    carregado.value = true;
  } catch (erro) {
    console.error("falha ao carregar as notificações", erro);
  } finally {
    carregando.value = false;
  }
}

export async function apagarNotificacao(uid, id) {
  await deleteDoc(doc(db, `usuarios/${uid}/notificacoes/${id}`));
  notificacoes.value = notificacoes.value.filter((n) => n.id !== id);
}

export function limparNotificacoes() {
  notificacoes.value = [];
  carregado.value = false;
}

export function useNotificacoes() {
  return {
    notificacoes, carregando, carregado,
    carregarNotificacoes, apagarNotificacao, limparNotificacoes,
  };
}
