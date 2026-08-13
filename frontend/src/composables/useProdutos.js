// Produtos e fontes: leitura em tempo real + todas as escritas que as rules
// permitem ao cliente. Portado de publico/app.js — os comentários sobre as
// rules valem letra por letra, porque firestore.rules não mudou.
import { ref } from "vue";
import {
  collection, doc, addDoc, getDocs, onSnapshot, updateDoc, writeBatch,
  serverTimestamp,
} from "firebase/firestore";
import { db } from "../firebase.js";

const produtos = ref([]);
const carregando = ref(true);

let uid = null;
let cancelarProdutos = null;
const cancelarFontes = new Map();

function observar(novoUid) {
  parar();
  uid = novoUid;
  if (!uid) return;

  carregando.value = true;
  cancelarProdutos = onSnapshot(
    collection(db, `usuarios/${uid}/produtos`),
    (instantaneo) => {
      const vistos = new Set();
      const lista = [...produtos.value];
      instantaneo.forEach((documento) => {
        vistos.add(documento.id);
        const existente = lista.find((p) => p.id === documento.id);
        if (existente) existente.dados = documento.data();
        else lista.push({ id: documento.id, dados: documento.data(), fontes: [] });
        if (!cancelarFontes.has(documento.id)) observarFontes(documento.id);
      });
      produtos.value = lista.filter((p) => vistos.has(p.id));
      carregando.value = false;
    },
    (erro) => console.error("falha ao observar produtos", erro),
  );
}

function observarFontes(produtoId) {
  const cancelar = onSnapshot(
    collection(db, `usuarios/${uid}/produtos/${produtoId}/fontes`),
    (instantaneo) => {
      const produto = produtos.value.find((p) => p.id === produtoId);
      if (!produto) return;
      // Ordem estável por id: a cor segue a fonte, não a posição na lista.
      produto.fontes = instantaneo.docs
        .map((d) => ({ id: d.id, ...d.data() }))
        .sort((a, b) => (a.id < b.id ? -1 : 1));
      produtos.value = [...produtos.value];   // acorda quem depende da lista
    },
    (erro) => console.error("falha ao observar fontes", erro),
  );
  cancelarFontes.set(produtoId, cancelar);
}

function parar() {
  if (cancelarProdutos) cancelarProdutos();
  cancelarProdutos = null;
  cancelarFontes.forEach((fn) => fn());
  cancelarFontes.clear();
  produtos.value = [];
  uid = null;
}

// ---------------------------------------------------------------------------
// Escritas
// ---------------------------------------------------------------------------

/** Campos do produto que o cliente pode escrever. As rules exigem exatamente
 *  estes — nem mais, nem menos.
 *
 *  `valorMaxCentavos` É o gatilho do alerta, sem intermediário: não existe mais
 *  campo derivado para o coletor recalcular a cada ciclo. `valorMinCentavos` é
 *  referência do usuário e não participa da decisão — quem decide é o máximo.
 *  Ver `coletor/alertas.py`. */
function camposDoProduto({ nome, minCentavos, maxCentavos }) {
  return {
    nome,
    valorMinCentavos: minCentavos,
    valorMaxCentavos: maxCentavos,
  };
}

const CAMPOS_DE_FONTE_NOVA = {
  status: "pendente",   // as rules exigem; quem promove é o coletor
  motivoInvalida: null,
  falhasSeguidas: 0,
  comErro: false,
  ultimoPrecoCentavos: null,
  ultimaColetaEm: null,
};

async function criarProduto(dados) {
  const refProduto = await addDoc(collection(db, `usuarios/${uid}/produtos`), {
    ...camposDoProduto(dados),
    estado: "ACIMA",
    ultimoAlertaEm: null,
    ultimoPrecoAlertadoCentavos: null,
    ativo: true,
    criadoEm: serverTimestamp(),
  });
  for (const fonte of dados.fontes) {
    await addDoc(collection(db, `usuarios/${uid}/produtos/${refProduto.id}/fontes`), {
      loja: fonte.loja, url: fonte.url, ...CAMPOS_DE_FONTE_NOVA,
    });
  }
  return refProduto.id;
}

async function salvarEdicao(produtoId, dados) {
  const produto = produtos.value.find((p) => p.id === produtoId);
  const antes = new Map((produto ? produto.fontes : []).map((f) => [f.id, f]));

  await updateDoc(doc(db, `usuarios/${uid}/produtos/${produtoId}`), camposDoProduto(dados));

  const mantidas = new Set();
  for (const fonte of dados.fontes) {
    const base = `usuarios/${uid}/produtos/${produtoId}/fontes`;
    if (!fonte.fonteId) {
      await addDoc(collection(db, base), {
        loja: fonte.loja, url: fonte.url, ...CAMPOS_DE_FONTE_NOVA,
      });
      continue;
    }
    mantidas.add(fonte.fonteId);
    const anterior = antes.get(fonte.fonteId);
    if (anterior && anterior.url === fonte.url && anterior.loja === fonte.loja) {
      continue;   // nada mudou: não revalida de graça
    }
    // Mudou loja ou URL: volta para a fila. Quem decide se a URL presta é o
    // coletor. O histórico da fonte é preservado — ver README.
    await updateDoc(doc(db, `${base}/${fonte.fonteId}`), {
      loja: fonte.loja,
      url: fonte.url,
      status: "pendente",
      motivoInvalida: null,
      falhasSeguidas: 0,
      comErro: false,
    });
  }

  // Fontes que o usuário tirou do formulário
  for (const id of antes.keys()) {
    if (!mantidas.has(id)) await apagarFonteComHistorico(produtoId, id);
  }
}

/** Apaga uma fonte e o histórico que pertence a ela.
 *
 *  O Firestore não faz cascata: sem isso, os buckets `historico/{fonteId}_*` e
 *  `diario/{fonteId}_*` ficariam órfãos ocupando espaço para sempre.
 */
async function apagarFonteComHistorico(produtoId, fonteId) {
  const base = `usuarios/${uid}/produtos/${produtoId}`;
  const lote = writeBatch(db);
  for (const colecao of ["historico", "diario"]) {
    const docs = await getDocs(collection(db, `${base}/${colecao}`));
    docs.forEach((documento) => {
      if (documento.id.startsWith(`${fonteId}_`)) lote.delete(documento.ref);
    });
  }
  lote.delete(doc(db, `${base}/fontes/${fonteId}`));
  await lote.commit();
}

/** Exclui o produto inteiro, incluindo fontes, histórico e rollup. */
async function excluirProduto(produtoId) {
  const base = `usuarios/${uid}/produtos/${produtoId}`;
  const lote = writeBatch(db);
  for (const colecao of ["fontes", "historico", "diario"]) {
    const docs = await getDocs(collection(db, `${base}/${colecao}`));
    docs.forEach((documento) => lote.delete(documento.ref));
  }
  lote.delete(doc(db, base));
  await lote.commit();
}

async function alternarAtivo(produtoId, ativoAgora) {
  // As rules permitem alterar só ['nome', 'valorMinCentavos',
  // 'valorMaxCentavos', 'ativo'] — 'ativo' está na lista.
  await updateDoc(doc(db, `usuarios/${uid}/produtos/${produtoId}`), {
    ativo: !ativoAgora,
  });
}

async function retentarFonte(produtoId, fonteId) {
  // As rules só aceitam esta transição exata: quebrada -> pendente, zerando os
  // contadores. Promover para 'ok' continua sendo do coletor.
  await updateDoc(doc(db, `usuarios/${uid}/produtos/${produtoId}/fontes/${fonteId}`), {
    status: "pendente",
    motivoInvalida: null,
    falhasSeguidas: 0,
    comErro: false,
  });
}

// ---------------------------------------------------------------------------
// Derivados de leitura
// ---------------------------------------------------------------------------

export function menorPrecoAtual(produto) {
  const precos = produto.fontes
    .filter((f) => f.status === "ok" && !f.comErro && typeof f.ultimoPrecoCentavos === "number")
    .map((f) => f.ultimoPrecoCentavos);
  return precos.length ? Math.min(...precos) : null;
}

/** Id da fonte que está com o menor preço, ou null.
 *
 *  MESMA regra de `menorPrecoAtual` — só fonte `ok`, sem erro e com preço
 *  numérico. Precisa ser a mesma, senão a tela destacaria uma fonte e o alerta
 *  usaria outra, e o usuário veria dois "menores preços" diferentes.
 *
 *  Empate resolve pela primeira: as fontes vêm ordenadas por id, então a
 *  escolha é estável entre renders em vez de dançar a cada atualização.
 */
export function fonteMaisBarata(produto) {
  let escolhida = null;
  for (const f of produto.fontes) {
    if (f.status !== "ok" || f.comErro) continue;
    if (typeof f.ultimoPrecoCentavos !== "number") continue;
    if (escolhida === null || f.ultimoPrecoCentavos < escolhida.ultimoPrecoCentavos) {
      escolhida = f;
    }
  }
  return escolhida ? escolhida.id : null;
}

export function ultimaVerificacao(produto) {
  const instantes = produto.fontes
    .map((f) => f.ultimaColetaEm)
    .filter(Boolean)
    .map((t) => (t.toDate ? t.toDate() : new Date(t)))
    .filter((d) => !isNaN(d));
  return instantes.length ? new Date(Math.max(...instantes.map((d) => d.getTime()))) : null;
}

export function fontesComProblema(produto) {
  return produto.fontes.filter(
    (f) => f.comErro || f.status === "invalida" ||
      (f.status === "pendente" && (f.falhasSeguidas || 0) > 0),
  ).length;
}

/** Explica o motivo em português, quando dá para explicar. */
const EXPLICACAO_DO_ERRO = {
  sem_jsonld: "a página não publica preço em JSON-LD",
  sem_product: "o JSON-LD não tem um nó de produto",
  sem_offers: "o produto não declara oferta",
  preco_invalido: "o preço publicado não é legível",
  moeda_nao_suportada: "o preço não está em reais",
  http_403: "a loja recusou a requisição (bloqueio de IP)",
  http_404: "a página não existe mais",
  timeout: "a loja não respondeu em 15s",
  erro_rede: "falha de rede ao acessar a loja",
};

export function explicar(motivo) {
  if (!motivo) return "não foi possível ler o preço";
  return EXPLICACAO_DO_ERRO[motivo] || motivo;
}

export function useProdutos() {
  return {
    produtos, carregando,
    observar, parar,
    criarProduto, salvarEdicao, excluirProduto,
    alternarAtivo, retentarFonte, apagarFonteComHistorico,
  };
}
