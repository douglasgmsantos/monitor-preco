// Série de preço por período, para o gráfico de flutuação e para os números do
// cartão.
//
// DUAS ORIGENS, e a escolha entre elas não é detalhe de implementação:
//
//   dia      histórico BRUTO (`historico/{fonteId}_{AAAA-MM}`), filtrado nas
//            últimas 24h. É o único período em que uma leitura individual
//            importa — nos demais o dia inteiro vira um ponto só.
//   demais   rollup `diario` (`diario/{fonteId}_{AAAA}`), fechamento por dia.
//
// O custo é o mesmo nos quatro casos, e é por isso que o bucketing existe: o
// `diario` é 1 documento por fonte por ANO, então o período anual custa as
// mesmas leituras que o de 7 dias. Um documento por leitura faria o anual custar
// 365 leituras cobradas por abertura de tela.
//
// O valor de cada ponto é o MENOR entre as fontes naquele instante: a mesma
// regra que a máquina de estados usa para decidir alerta, para o gráfico não
// contar uma história diferente da mensagem do Telegram.
import { doc, getDoc } from "firebase/firestore";
import { db } from "../firebase.js";
import { chaveAno, chaveDia, chaveMes } from "../tempo.js";

/** Períodos oferecidos, na ordem em que aparecem na tela. */
export const PERIODOS = [
  { id: "dia", rotulo: "Dia", titulo: "Flutuação de 24 horas", dias: 1 },
  { id: "7d", rotulo: "7 dias", titulo: "Flutuação de 7 dias", dias: 7 },
  { id: "30d", rotulo: "Mensal", titulo: "Flutuação de 30 dias", dias: 30 },
  { id: "ano", rotulo: "Anual", titulo: "Flutuação de 12 meses", dias: 365 },
];

export const PERIODO_PADRAO = "30d";

// A média que o cartão mostra e que o alerta usa é SEMPRE de 30 dias, escolha o
// usuário o período que escolher no gráfico. Ver `DIAS_DA_MEDIA` no coletor:
// mudar este número aqui faria a tela dizer uma coisa e o Telegram outra.
const PERIODO_DA_MEDIA = "30d";

function diasDe(periodo) {
  const achado = PERIODOS.find((p) => p.id === periodo);
  return achado ? achado.dias : 30;
}

// Cache por produto+período: o cartão e a análise pedem séries, e sem isto cada
// troca de aba pagaria as leituras de novo. Invalida ao trocar snapshot.
const cache = new Map();

export function invalidarResumo(produtoId) {
  if (!produtoId) return cache.clear();
  for (const chave of [...cache.keys()]) {
    if (chave.startsWith(`${produtoId}:`)) cache.delete(chave);
  }
}

async function lerBucket(caminho) {
  const instantaneo = await getDoc(doc(db, caminho));
  return instantaneo.exists() ? instantaneo.data() : null;
}

/** {serie: [{chave, quando, centavos}], media, menor} do período pedido. */
export async function serieDoPeriodo(uid, produtoId, fontes, periodo = PERIODO_PADRAO) {
  const chaveCache = `${produtoId}:${periodo}:${fontes.map((f) => f.id).join(",")}`;
  if (cache.has(chaveCache)) return cache.get(chaveCache);

  const promessa = periodo === "dia"
    ? calcularPorHora(uid, produtoId, fontes)
    : calcularPorDia(uid, produtoId, fontes, diasDe(periodo));

  cache.set(chaveCache, promessa);
  try {
    return await promessa;
  } catch (erro) {
    cache.delete(chaveCache);   // erro não pode ficar cacheado
    throw erro;
  }
}

/** Compatibilidade: é o que o cartão consome, e é a referência do alerta. */
export function resumo30d(uid, produtoId, fontes) {
  return serieDoPeriodo(uid, produtoId, fontes, PERIODO_DA_MEDIA);
}

function resumir(serie, extra = {}) {
  const valores = serie.map((p) => p.centavos);
  return {
    serie,
    media: valores.length
      ? Math.round(valores.reduce((soma, v) => soma + v, 0) / valores.length)
      : null,
    menor: valores.length ? Math.min(...valores) : null,
    // A mínima REAL da janela e há quantos dias se observa. Vem separada do
    // `menor` porque `menor` é da série de fechamentos, e a série é o que o
    // gráfico desenha. Confundir os dois faria a tela afirmar um recorde que a
    // mensagem do Telegram não confirma.
    minimo: extra.minimo ?? (valores.length ? Math.min(...valores) : null),
    diasObservados: extra.diasObservados ?? serie.length,
  };
}

/** 7 / 30 / 365 dias, do rollup diário. */
async function calcularPorDia(uid, produtoId, fontes, dias) {
  const agora = new Date();
  const grade = [];
  const anos = new Set();
  for (let i = dias - 1; i >= 0; i--) {
    const dia = new Date(agora.getTime() - i * 24 * 3600 * 1000);
    anos.add(chaveAno(dia));
    grade.push({ chave: chaveDia(dia), quando: dia });
  }

  const menorPorDia = new Map();   // fechamento — é o que a série desenha
  const minimoPorDia = new Map();  // mínima REAL do dia — é o que vira recorde

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
        // `min` e `fech` são coisas diferentes: o dia pode ter tocado R$ 4.200
        // de manhã e fechado em R$ 4.800. O gráfico mostra o fechamento; o
        // "menor preço" precisa da mínima de verdade, senão a tela contradiz a
        // mensagem do Telegram, que lê `min` (ver `minima_historica`).
        const minimo = typeof valores.min === "number" ? valores.min : valores.fech;
        const menorAtual = minimoPorDia.get(chave);
        if (menorAtual === undefined || minimo < menorAtual) {
          minimoPorDia.set(chave, minimo);
        }
      }
    }
  }

  const dentroDaJanela = [...minimoPorDia.entries()]
    .filter(([chave]) => grade.some((g) => g.chave === chave));

  return resumir(
    grade
      .filter(({ chave }) => menorPorDia.has(chave))
      .map(({ chave, quando }) => ({ chave, quando, centavos: menorPorDia.get(chave) })),
    {
      minimo: dentroDaJanela.length
        ? Math.min(...dentroDaJanela.map(([, v]) => v)) : null,
      diasObservados: dentroDaJanela.length,
    },
  );
}

/** Últimas 24h, do histórico bruto.
 *
 *  Lê os buckets de DOIS meses quando a janela cruza a virada — sem isso, todo
 *  dia 1º o gráfico do dia apareceria vazio até a primeira coleta do mês.
 */
async function calcularPorHora(uid, produtoId, fontes) {
  const agora = new Date();
  const corte = new Date(agora.getTime() - 24 * 3600 * 1000);
  const meses = new Set([chaveMes(agora), chaveMes(corte)]);

  const menorPorInstante = new Map();
  for (const fonte of fontes) {
    for (const mes of meses) {
      const bucket = await lerBucket(
        `usuarios/${uid}/produtos/${produtoId}/historico/${fonte.id}_${mes}`);
      for (const leitura of (bucket && bucket.leituras) || []) {
        // Falha (preço nulo) e leitura suspeita ficam de fora: o rollup diário
        // já as exclui, e o gráfico do dia tem de contar a mesma história.
        if (leitura.p === null || leitura.p === undefined || leitura.s) continue;
        const quando = leitura.t && leitura.t.toDate
          ? leitura.t.toDate() : new Date(leitura.t);
        if (isNaN(quando) || quando < corte) continue;

        // Agrupa por minuto: as fontes de um mesmo ciclo são coletadas com
        // segundos de diferença e devem virar UM ponto, com o menor preço.
        const chave = quando.toISOString().slice(0, 16);
        const atual = menorPorInstante.get(chave);
        if (atual === undefined || leitura.p < atual.centavos) {
          menorPorInstante.set(chave, { chave, quando, centavos: leitura.p });
        }
      }
    }
  }

  return resumir(
    [...menorPorInstante.values()].sort((a, b) => a.quando - b.quando),
  );
}
