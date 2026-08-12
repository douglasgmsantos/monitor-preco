// Resumo de 30 dias por produto: média, menor preço e a série diária que
// alimenta o gráfico de flutuação.
//
// Vem do rollup `diario` (fechamento por dia), nunca do histórico bruto — a
// mesma decisão do front antigo para períodos longos. O valor de cada dia é o
// MENOR entre as fontes naquele dia: a mesma regra que a máquina de estados usa
// para decidir alerta, para o gráfico não contar uma história diferente da
// mensagem do Telegram.
import { doc, getDoc } from "firebase/firestore";
import { db } from "../firebase.js";
import { chaveAno, chaveDia } from "../tempo.js";

const DIAS = 30;

// Cache por produto: o cartão e a análise detalhada pedem o mesmo resumo, e
// sem isto cada um pagaria as próprias leituras. Invalida ao trocar snapshot.
const cache = new Map();

export function invalidarResumo(produtoId) {
  if (produtoId) cache.delete(produtoId);
  else cache.clear();
}

async function lerBucket(caminho) {
  const instantaneo = await getDoc(doc(db, caminho));
  return instantaneo.exists() ? instantaneo.data() : null;
}

/** {serie: [{chave, quando, centavos}], media, menor} dos últimos 30 dias. */
export async function resumo30d(uid, produtoId, fontes) {
  const chaveCache = `${produtoId}:${fontes.map((f) => f.id).join(",")}`;
  if (cache.has(chaveCache)) return cache.get(chaveCache);

  const promessa = calcular(uid, produtoId, fontes);
  cache.set(chaveCache, promessa);
  try {
    return await promessa;
  } catch (erro) {
    cache.delete(chaveCache);   // erro não pode ficar cacheado
    throw erro;
  }
}

async function calcular(uid, produtoId, fontes) {
  const agora = new Date();
  const dias = [];
  const anos = new Set();
  for (let i = DIAS - 1; i >= 0; i--) {
    const dia = new Date(agora.getTime() - i * 24 * 3600 * 1000);
    anos.add(chaveAno(dia));
    dias.push({ chave: chaveDia(dia), quando: dia });
  }

  // menor fechamento entre as fontes, dia a dia
  const menorPorDia = new Map();
  for (const fonte of fontes) {
    for (const ano of anos) {
      const bucket = await lerBucket(
        `usuarios/${uid}/produtos/${produtoId}/diario/${fonte.id}_${ano}`);
      for (const [chave, valores] of Object.entries((bucket && bucket.dias) || {})) {
        if (typeof valores.fech !== "number") continue;
        const atual = menorPorDia.get(chave);
        if (atual === undefined || valores.fech < atual) {
          menorPorDia.set(chave, valores.fech);
        }
      }
    }
  }

  const serie = dias
    .filter(({ chave }) => menorPorDia.has(chave))
    .map(({ chave, quando }) => ({ chave, quando, centavos: menorPorDia.get(chave) }));

  const valores = serie.map((p) => p.centavos);
  const media = valores.length
    ? Math.round(valores.reduce((soma, v) => soma + v, 0) / valores.length)
    : null;
  const menor = valores.length ? Math.min(...valores) : null;

  return { serie, media, menor };
}
