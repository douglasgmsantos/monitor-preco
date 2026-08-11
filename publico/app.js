// Front do monitor de preços. HTML + JS puro, sem build.
//
// Dinheiro trafega como INTEIRO DE CENTAVOS em todo o caminho. A única divisão
// por 100 do projeto está em `formatarBRL`, e existe só para exibir.

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, onAuthStateChanged, signInWithEmailAndPassword,
  createUserWithEmailAndPassword, GoogleAuthProvider, signInWithPopup, signOut,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getFirestore, collection, doc, addDoc, getDoc, getDocs, onSnapshot,
  updateDoc, writeBatch, serverTimestamp,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";

import { configFirebase } from "./firebase-config.js";

const app = initializeApp(configFirebase);
const auth = getAuth(app);
const db = getFirestore(app);

const $ = (id) => document.getElementById(id);
const MAX_SERIES = 8; // a paleta tem 8 slots; nunca gerar uma 9ª cor

let uid = null;
let produtos = [];              // {id, dados, fontes:[]}
let idSelecionado = null;
let modoEdicao = null;          // id do produto em edição, ou null para criação
let periodo = "1m";
let escala = "reais";   // "reais" | "indice"
let grafico = null;
let dadosDoGrafico = null;      // {rotulos, series:[{nome, cor, valores}]}
let cancelarProdutos = null;
const cancelarFontes = new Map();

// ---------------------------------------------------------------------------
// Dinheiro
// ---------------------------------------------------------------------------

/** A ÚNICA divisão por 100 do projeto. Existe só para exibição. */
function formatarBRL(centavos) {
  if (centavos === null || centavos === undefined) return "—";
  return (centavos / 100).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
  });
}

/**
 * Texto em reais -> inteiro de centavos, ou null se inválido.
 *
 * Espelha os passos 2 a 6 da seção 7.5 da spec. A fonte da verdade é
 * `normalizar_para_centavos` em coletor/parser.py; esta cópia existe porque a
 * seção 12 exige converter na entrada, antes de gravar no Firestore.
 */
function paraCentavos(texto) {
  if (typeof texto !== "string") return null;
  const cru = texto.trim();
  // sinal negativo tem de ser visto antes da limpeza apagá-lo
  for (const ch of cru) {
    if (ch >= "0" && ch <= "9") break;
    if (ch === "-" || ch === "−") return null;
  }
  let limpo = cru.replace(/[^\d.,]/g, "");
  const temVirgula = limpo.includes(",");
  const temPonto = limpo.includes(".");

  if (temVirgula && temPonto) {
    if (limpo.lastIndexOf(",") > limpo.lastIndexOf(".")) {
      limpo = limpo.replace(/\./g, "").replace(",", ".");
    } else {
      limpo = limpo.replace(/,/g, "");
    }
  } else if (temVirgula || temPonto) {
    const sep = temVirgula ? "," : ".";
    const quantas = limpo.split(sep).length - 1;
    if (quantas > 1) {
      limpo = limpo.split(sep).join("");
    } else {
      const depois = limpo.length - limpo.indexOf(sep) - 1;
      if (depois === 1 || depois === 2) limpo = limpo.replace(sep, ".");
      else if (depois === 3) limpo = limpo.replace(sep, "");
      else return null;
    }
  }
  if (!limpo) return null;

  const ponto = limpo.indexOf(".");
  let inteira = ponto === -1 ? limpo : limpo.slice(0, ponto);
  let fracao = ponto === -1 ? "" : limpo.slice(ponto + 1);
  inteira = inteira || "0";
  fracao = (fracao + "00").slice(0, 2);
  if (!/^\d+$/.test(inteira) || !/^\d{2}$/.test(fracao)) return null;

  const centavos = parseInt(inteira, 10) * 100 + parseInt(fracao, 10);
  if (!Number.isSafeInteger(centavos) || centavos <= 0) return null;
  return centavos;
}

// ---------------------------------------------------------------------------
// Tema e cores
// ---------------------------------------------------------------------------

function tokens() {
  const estilo = getComputedStyle(document.documentElement);
  const ler = (nome) => estilo.getPropertyValue(nome).trim();
  return {
    tinta: ler("--tinta"),
    tinta2: ler("--tinta-2"),
    fraca: ler("--tinta-fraca"),
    grade: ler("--grade"),
    eixo: ler("--eixo"),
    superficie: ler("--superficie"),
    series: Array.from({ length: MAX_SERIES }, (_, i) => ler(`--serie-${i + 1}`)),
  };
}

$("btTema").addEventListener("click", () => {
  const atual = document.documentElement.getAttribute("data-theme");
  const escuroAgora =
    atual === "dark" ||
    (!atual && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", escuroAgora ? "light" : "dark");
  desenhar();          // o escuro tem passos próprios, não é inversão
  renderizarLista();
});

// ---------------------------------------------------------------------------
// Autenticação
// ---------------------------------------------------------------------------

function mostrarErroLogin(mensagem) {
  const alvo = $("erroLogin");
  alvo.textContent = mensagem;
  alvo.classList.remove("oculto");
}

$("btEntrar").addEventListener("click", async () => {
  try {
    await signInWithEmailAndPassword(auth, $("email").value.trim(), $("senha").value);
  } catch (erro) { mostrarErroLogin(traduzir(erro)); }
});

$("btCriar").addEventListener("click", async () => {
  try {
    await createUserWithEmailAndPassword(auth, $("email").value.trim(), $("senha").value);
  } catch (erro) { mostrarErroLogin(traduzir(erro)); }
});

$("btGoogle").addEventListener("click", async () => {
  try {
    await signInWithPopup(auth, new GoogleAuthProvider());
  } catch (erro) { mostrarErroLogin(traduzir(erro)); }
});

$("btSair").addEventListener("click", () => signOut(auth));

function traduzir(erro) {
  const codigo = (erro && erro.code) || "";
  const mapa = {
    "auth/invalid-credential": "E-mail ou senha incorretos.",
    "auth/invalid-email": "E-mail inválido.",
    "auth/weak-password": "A senha precisa de ao menos 6 caracteres.",
    "auth/email-already-in-use": "Esse e-mail já tem conta. Use Entrar.",
    "auth/popup-closed-by-user": "Janela do Google fechada antes de concluir.",
    "auth/operation-not-allowed": "Provedor não habilitado no Firebase Console.",
  };
  return mapa[codigo] || `Falha ao autenticar (${codigo || erro})`;
}

onAuthStateChanged(auth, (usuario) => {
  uid = usuario ? usuario.uid : null;
  $("entrar").classList.toggle("oculto", !!usuario);
  $("app").classList.toggle("oculto", !usuario);
  if (usuario) {
    $("quem").textContent = usuario.email || usuario.displayName || "";
    observarProdutos();
    carregarCatalogo();
  } else {
    if (cancelarProdutos) cancelarProdutos();
    cancelarFontes.forEach((fn) => fn());
    cancelarFontes.clear();
    produtos = [];
    idSelecionado = null;
  }
});

// ---------------------------------------------------------------------------
// Formulário de cadastro
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Lojas
//
// Só entram aqui lojas em que EU verifiquei, na página de produto real, que o
// preço vem em <script type="application/ld+json"> por HTTP simples e que o
// User-Agent honesto do coletor não é bloqueado. Ampliar a lista exige repetir
// essa verificação — não é palpite.
// ---------------------------------------------------------------------------

const LOJAS = [
  { nome: "KaBuM",         dominios: ["kabum.com.br"] },
  { nome: "Terabyte Shop", dominios: ["terabyteshop.com.br"] },
  { nome: "Carrefour",     dominios: ["carrefour.com.br"] },
];
const LOJA_OUTRA = "__outra__";

/** Domínios confirmadamente incompatíveis, com o motivo verificado. */
const DOMINIOS_INCOMPATIVEIS = [
  { padrao: /(^|\.)amazon\.com\.br$/, motivo: "a Amazon não publica JSON-LD nas páginas de produto" },
  { padrao: /(^|\.)mercadolivre\.com\.br$/, motivo: "o Mercado Livre monta a página por JavaScript; o HTML não traz JSON-LD" },
  { padrao: /(^|\.)magazineluiza\.com\.br$/, motivo: "o Magazine Luiza bloqueia requisições automatizadas (HTTP 403)" },
  { padrao: /(^|\.)magalu\.com\.br$/, motivo: "o Magalu bloqueia requisições automatizadas (HTTP 403)" },
  // A Pichau responde de IP residencial mas recusa o datacenter onde o coletor
  // roda. Como o coletor SÓ roda de lá, para este sistema ela é inviável.
  { padrao: /(^|\.)pichau\.com\.br$/, motivo: "a Pichau recusa requisições do datacenter onde o coletor roda (HTTP 403)" },
];

function hostDaUrl(url) {
  try { return new URL(url).hostname.toLowerCase().replace(/^www\./, ""); }
  catch { return null; }
}

function motivoDeIncompatibilidade(url) {
  const host = hostDaUrl(url);
  if (!host) return null;
  const achado = DOMINIOS_INCOMPATIVEIS.find((d) => d.padrao.test(host));
  return achado ? achado.motivo : null;
}

function hostCombinaComLoja(url, loja) {
  const host = hostDaUrl(url);
  const definicao = LOJAS.find((l) => l.nome === loja);
  if (!host || !definicao) return true;   // "Outra loja": nada a comparar
  return definicao.dominios.some((d) => host === d || host.endsWith("." + d));
}

function adicionarParDeFonte({ loja = "", url = "", fonteId = "" } = {}) {
  const linha = document.createElement("div");
  linha.className = "par-fonte";
  // fonteId vazio = fonte nova; preenchido = fonte existente sendo editada
  linha.dataset.fonteId = fonteId;

  const conhecida = LOJAS.some((l) => l.nome === loja);
  const selecionada = loja ? (conhecida ? loja : LOJA_OUTRA) : "";
  const opcoes = LOJAS.map((l) =>
    `<option value="${esc(l.nome)}"${l.nome === selecionada ? " selected" : ""}>${esc(l.nome)}</option>`
  ).join("");

  linha.innerHTML = `
    <div class="celula-loja">
      <select class="loja-escolha">
        <option value=""${selecionada ? "" : " selected"}>Selecione a loja…</option>
        ${opcoes}
        <option value="${LOJA_OUTRA}"${selecionada === LOJA_OUTRA ? " selected" : ""}>Outra loja…</option>
      </select>
      <input class="loja-livre ${selecionada === LOJA_OUTRA ? "" : "oculto"}"
             placeholder="Nome da loja" value="${selecionada === LOJA_OUTRA ? esc(loja) : ""}">
    </div>
    <input class="url" placeholder="https://..." value="${esc(url)}">
    <button class="discreto remover" title="Remover">✕</button>`;

  const escolha = linha.querySelector(".loja-escolha");
  const livre = linha.querySelector(".loja-livre");
  escolha.addEventListener("change", () => {
    livre.classList.toggle("oculto", escolha.value !== LOJA_OUTRA);
    if (escolha.value === LOJA_OUTRA) livre.focus();
  });

  linha.querySelector(".remover").addEventListener("click", () => {
    if ($("pares").children.length > 1) linha.remove();
  });
  $("pares").appendChild(linha);
}

/** Loja informada nesta linha, ou "" se incompleta. */
function lojaDaLinha(linha) {
  const escolha = linha.querySelector(".loja-escolha").value;
  if (escolha === LOJA_OUTRA) return linha.querySelector(".loja-livre").value.trim();
  return escolha;
}

adicionarParDeFonte();
$("btMaisFonte").addEventListener("click", () => adicionarParDeFonte());

function erroForm(mensagem) {
  const alvo = $("erroForm");
  if (!mensagem) { alvo.classList.add("oculto"); return false; }
  alvo.textContent = mensagem;
  alvo.classList.remove("oculto");
  return false;
}

/** Lê e valida o formulário. Devolve os dados, ou null se algo está errado. */
function lerFormulario() {
  erroForm(null);
  const nome = $("nome").value.trim();
  if (!nome || nome.length > 200) {
    erroForm("Informe um nome de até 200 caracteres.");
    return null;
  }

  const alvoCentavos = paraCentavos($("alvo").value);
  if (alvoCentavos === null) {
    erroForm("Preço-alvo inválido. Use o formato 1.789,90 ou 1789.90.");
    return null;
  }
  const tolerancia = parseInt($("tolerancia").value, 10);
  if (!Number.isInteger(tolerancia) || tolerancia < 0 || tolerancia > 100) {
    erroForm("Tolerância precisa ser um inteiro entre 0 e 100.");
    return null;
  }

  const fontes = [];
  for (const linha of $("pares").children) {
    const loja = lojaDaLinha(linha);
    const url = linha.querySelector(".url").value.trim();
    if (!loja && !url) continue;
    if (!loja) {
      erroForm("Escolha a loja (ou informe o nome em “Outra loja”).");
      return null;
    }
    if (!/^https:\/\/.+/.test(url)) {
      erroForm(`URL inválida em “${loja}”: precisa começar com https://`);
      return null;
    }
    const incompativel = motivoDeIncompatibilidade(url);
    if (incompativel) {
      erroForm(`Essa loja não pode ser monitorada: ${incompativel}.`);
      return null;
    }
    if (!hostCombinaComLoja(url, loja)) {
      erroForm(
        `A URL não é de ${loja} (domínio: ${hostDaUrl(url)}). ` +
        `Confira a loja escolhida.`);
      return null;
    }
    fontes.push({ loja, url, fonteId: linha.dataset.fonteId || "" });
  }
  if (!fontes.length) {
    erroForm("Cadastre ao menos uma loja com URL.");
    return null;
  }
  return { nome, alvoCentavos, tolerancia, fontes };
}

/** Campos do produto que o cliente pode escrever. As rules exigem exatamente
 *  estes; `precoGatilhoCentavos` vai como o mínimo válido e o coletor corrige. */
function camposDoProduto({ nome, alvoCentavos, tolerancia }) {
  return {
    nome,
    precoAlvoCentavos: alvoCentavos,
    toleranciaPct: tolerancia,
    // O gatilho autoritativo é calculado pelo coletor (calcular_gatilho, em
    // alertas.py). Duplicar a fórmula aqui violaria o anti-padrão da seção 14.
    precoGatilhoCentavos: alvoCentavos,
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
  const produto = produtos.find((p) => p.id === produtoId);
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
    if (!mantidas.has(id)) {
      await apagarFonteComHistorico(produtoId, id);
    }
  }
}

$("btSalvar").addEventListener("click", async () => {
  const dados = lerFormulario();
  if (!dados) return;

  $("btSalvar").disabled = true;
  try {
    if (modoEdicao) {
      await salvarEdicao(modoEdicao, dados);
      idSelecionado = modoEdicao;
      cancelarEdicao();
    } else {
      idSelecionado = await criarProduto(dados);
      limparFormulario();
    }
  } catch (erro) {
    erroForm(`Não foi possível salvar: ${erro.message || erro}`);
  } finally {
    $("btSalvar").disabled = false;
  }
});

function limparFormulario() {
  $("nome").value = "";
  $("alvo").value = "";
  $("alvo").placeholder = "1.789,90";
  $("tituloForm").textContent = "Novo produto";
  $("tolerancia").value = "0";
  $("pares").innerHTML = "";
  adicionarParDeFonte();
  erroForm(null);
}

function iniciarEdicao(produtoId) {
  const produto = produtos.find((p) => p.id === produtoId);
  if (!produto) return;

  modoEdicao = produtoId;
  $("nome").value = produto.dados.nome || "";
  // reais na entrada, centavos no armazenamento
  $("alvo").value = formatarBRL(produto.dados.precoAlvoCentavos).replace("R$", "").trim();
  $("tolerancia").value = String(produto.dados.toleranciaPct ?? 0);
  $("pares").innerHTML = "";
  for (const fonte of produto.fontes) {
    adicionarParDeFonte({ loja: fonte.loja, url: fonte.url, fonteId: fonte.id });
  }
  if (!produto.fontes.length) adicionarParDeFonte();

  $("tituloForm").textContent = "Editar produto";
  $("btSalvar").textContent = "Salvar alterações";
  $("btCancelarEdicao").classList.remove("oculto");
  erroForm(null);
  $("nome").scrollIntoView({ behavior: "smooth", block: "center" });
}

function cancelarEdicao() {
  modoEdicao = null;
  $("tituloForm").textContent = "Novo produto";
  $("btSalvar").textContent = "Cadastrar produto";
  $("btCancelarEdicao").classList.add("oculto");
  limparFormulario();
}

$("btCancelarEdicao").addEventListener("click", cancelarEdicao);

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
  const produto = produtos.find((p) => p.id === produtoId);
  if (!produto) return;

  const quantasFontes = produto.fontes.length;
  const confirmado = confirm(
    `Excluir “${produto.dados.nome}”?\n\n` +
    `Isso apaga ${quantasFontes} fonte(s) e TODO o histórico de preços do ` +
    `produto. Não há como desfazer.\n\n` +
    `Para só parar de coletar sem perder o histórico, use “pausar coleta”.`
  );
  if (!confirmado) return;

  const base = `usuarios/${uid}/produtos/${produtoId}`;
  try {
    const lote = writeBatch(db);
    for (const colecao of ["fontes", "historico", "diario"]) {
      const docs = await getDocs(collection(db, `${base}/${colecao}`));
      docs.forEach((documento) => lote.delete(documento.ref));
    }
    lote.delete(doc(db, base));
    await lote.commit();

    if (modoEdicao === produtoId) cancelarEdicao();
  } catch (erro) {
    console.error("falha ao excluir o produto", erro);
    alert(`Não foi possível excluir: ${erro.message || erro}`);
  }
}

// ---------------------------------------------------------------------------
// Leitura em tempo real
// ---------------------------------------------------------------------------

function observarProdutos() {
  if (cancelarProdutos) cancelarProdutos();
  cancelarProdutos = onSnapshot(
    collection(db, `usuarios/${uid}/produtos`),
    (instantaneo) => {
      const vistos = new Set();
      instantaneo.forEach((documento) => {
        vistos.add(documento.id);
        const existente = produtos.find((p) => p.id === documento.id);
        if (existente) existente.dados = documento.data();
        else produtos.push({ id: documento.id, dados: documento.data(), fontes: [] });
        if (!cancelarFontes.has(documento.id)) observarFontes(documento.id);
      });
      produtos = produtos.filter((p) => vistos.has(p.id));
      if (!idSelecionado || !vistos.has(idSelecionado)) {
        idSelecionado = produtos.length ? produtos[0].id : null;
      }
      renderizarLista();
      renderizarCatalogo();
      agendarHistorico();
    },
    (erro) => console.error("falha ao observar produtos", erro),
  );
}

function observarFontes(produtoId) {
  const cancelar = onSnapshot(
    collection(db, `usuarios/${uid}/produtos/${produtoId}/fontes`),
    (instantaneo) => {
      const produto = produtos.find((p) => p.id === produtoId);
      if (!produto) return;
      // Ordem estável por id: a cor segue a fonte, não a posição na lista.
      produto.fontes = instantaneo.docs
        .map((d) => ({ id: d.id, ...d.data() }))
        .sort((a, b) => (a.id < b.id ? -1 : 1));
      renderizarLista();
      renderizarCatalogo();
      agendarHistorico();   // qualquer fonte afeta o gráfico agora
    },
    (erro) => console.error("falha ao observar fontes", erro),
  );
  cancelarFontes.set(produtoId, cancelar);
}

// ---------------------------------------------------------------------------
// Lista de produtos
// ---------------------------------------------------------------------------

/** Escapa texto que vai para innerHTML. Nome de produto e loja são digitados
 *  pelo usuário e não podem virar markup. */
function esc(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);
}

/** Versão curta da URL para exibir: sem esquema, sem `www.`, sem query string.
 *  A URL completa fica no href e no title. */
function encurtarUrl(url, limite = 44) {
  let texto = url;
  try {
    const partes = new URL(url);
    texto = partes.hostname.replace(/^www\./, "") + partes.pathname.replace(/\/$/, "");
  } catch {
    /* URL malformada: mostra o que veio, truncado */
  }
  return texto.length <= limite ? texto : texto.slice(0, limite - 1) + "…";
}

function menorPrecoAtual(produto) {
  const precos = produto.fontes
    .filter((f) => f.status === "ok" && !f.comErro && typeof f.ultimoPrecoCentavos === "number")
    .map((f) => f.ultimoPrecoCentavos);
  return precos.length ? Math.min(...precos) : null;
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

function explicar(motivo) {
  if (!motivo) return "não foi possível ler o preço";
  return EXPLICACAO_DO_ERRO[motivo] || motivo;
}

function seloDaFonte(fonte) {
  if (fonte.status === "pendente") {
    const tentando = (fonte.falhasSeguidas || 0) > 0
      ? ` (tentativa ${fonte.falhasSeguidas + 1}: ${esc(explicar(fonte.motivoInvalida))})`
      : "";
    return `<span class="selo pendente">⏳ validando fonte…</span>` +
           (tentando ? `<span class="motivo-leve">${tentando}</span>` : "");
  }
  if (fonte.status === "invalida") {
    return `<span class="selo invalida">✕ inválida</span>
            <span class="motivo">${esc(explicar(fonte.motivoInvalida))}</span>`;
  }
  if (fonte.comErro) {
    return `<span class="selo invalida">⚠ desativada após 5 falhas</span>
            <span class="motivo">${esc(explicar(fonte.motivoInvalida))}</span>`;
  }
  return `<span class="selo">✓ ok</span>`;
}

/** Uma fonte quebrada pode voltar para a fila de validação. */
const fonteQuebrada = (fonte) => fonte.status === "invalida" || fonte.comErro === true;

function renderizarLista() {
  const cores = tokens().series;
  const lista = $("lista");
  lista.innerHTML = "";
  $("semProdutos").classList.toggle("oculto", produtos.length > 0);

  for (const produto of produtos) {
    const menor = menorPrecoAtual(produto);
    const emAlerta = produto.dados.estado === "EM_ALERTA";
    const pausado = produto.dados.ativo === false;
    const cartao = document.createElement("div");
    cartao.className = pausado ? "produto pausado" : "produto";
    cartao.setAttribute("aria-selected", String(produto.id === idSelecionado));

    const fontesHtml = produto.fontes.map((fonte, indice) => `
      <div class="fonte">
        <span class="amostra" style="background:${cores[indice % MAX_SERIES]}"></span>
        <span class="loja-nome">${esc(fonte.loja)}</span>
        ${seloDaFonte(fonte)}
        <a class="endereco" href="${esc(fonte.url)}" target="_blank" rel="noopener noreferrer"
           title="${esc(fonte.url)}">${esc(encurtarUrl(fonte.url))}</a>
        ${fonteQuebrada(fonte) ? `
          <button class="discreto tentar-fonte" data-produto="${esc(produto.id)}"
                  data-fonte="${esc(fonte.id)}" title="Volta a fonte para a fila de validação">
            ↻ tentar de novo
          </button>
          <button class="discreto remover-fonte" data-produto="${esc(produto.id)}"
                  data-fonte="${esc(fonte.id)}">remover</button>` : ""}
      </div>`).join("");

    const seloEstado = pausado
      ? `<span class="selo pausa">⏸ pausado</span>`
      : emAlerta
        ? `<span class="selo alerta">🔻 em alerta</span>`
        : `<span class="selo">acima do alvo</span>`;

    cartao.innerHTML = `
      <div class="cabeca">
        <span class="nome" title="${esc(produto.dados.nome)}">${esc(produto.dados.nome)}</span>
        ${seloEstado}
        <span class="preco">${formatarBRL(menor)}</span>
      </div>
      <div class="meta">
        alvo ${formatarBRL(produto.dados.precoAlvoCentavos)}
        · tolerância ${produto.dados.toleranciaPct}%
        · dispara em ${formatarBRL(produto.dados.precoGatilhoCentavos)}
      </div>
      <div class="fontes">${fontesHtml}</div>
      <div class="acoes">
        <button class="discreto editar-produto" data-produto="${esc(produto.id)}">✎ editar</button>
        <button class="discreto alternar-ativo" data-produto="${esc(produto.id)}"
                data-ativo="${pausado ? "false" : "true"}">
          ${pausado ? "▶ retomar coleta" : "⏸ pausar coleta"}
        </button>
        <button class="discreto perigo excluir-produto" data-produto="${esc(produto.id)}">🗑 excluir</button>
      </div>`;

    cartao.addEventListener("click", (evento) => {
      if (evento.target.closest(".acoes, .remover-fonte, .tentar-fonte")) return;
      idSelecionado = produto.id;
      renderizarLista();
      desenhar();   // só muda o destaque; não precisa reler o Firestore
    });
    lista.appendChild(cartao);
  }

  lista.querySelectorAll(".editar-produto").forEach((botao) => {
    botao.addEventListener("click", () => iniciarEdicao(botao.dataset.produto));
  });

  lista.querySelectorAll(".excluir-produto").forEach((botao) => {
    botao.addEventListener("click", () => excluirProduto(botao.dataset.produto));
  });

  lista.querySelectorAll(".remover-fonte").forEach((botao) => {
    botao.addEventListener("click", async () => {
      const { produto, fonte } = botao.dataset;
      await apagarFonteComHistorico(produto, fonte);
    });
  });

  lista.querySelectorAll(".tentar-fonte").forEach((botao) => {
    botao.addEventListener("click", async () => {
      botao.disabled = true;
      const { produto, fonte } = botao.dataset;
      try {
        // As rules só aceitam esta transição exata: quebrada -> pendente,
        // zerando os contadores. Promover para 'ok' continua sendo do coletor.
        await updateDoc(doc(db, `usuarios/${uid}/produtos/${produto}/fontes/${fonte}`), {
          status: "pendente",
          motivoInvalida: null,
          falhasSeguidas: 0,
          comErro: false,
        });
      } catch (erro) {
        console.error("falha ao reenfileirar a fonte", erro);
        botao.disabled = false;
      }
    });
  });

  lista.querySelectorAll(".alternar-ativo").forEach((botao) => {
    botao.addEventListener("click", async () => {
      botao.disabled = true;
      try {
        // As rules permitem alterar só ['nome', 'precoAlvoCentavos',
        // 'toleranciaPct', 'precoGatilhoCentavos', 'ativo'] — 'ativo' está na
        // lista, e o documento resultante continua válido.
        await updateDoc(doc(db, `usuarios/${uid}/produtos/${botao.dataset.produto}`), {
          ativo: botao.dataset.ativo !== "true",
        });
      } catch (erro) {
        console.error("falha ao pausar/retomar", erro);
        botao.disabled = false;
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Catálogo
//
// Uma leitura por categoria: o documento de índice traz {sku: {n, u, p}} da
// categoria inteira. Ler item a item custaria uma leitura por produto.
//
// `p` é o preço de TABELA (vitrine), 10% a 31% acima do preço real da página
// do produto — medido em 2026-08-10. Ele nunca dispara alerta; serve para
// achar o produto. Ao acompanhar, o preço passa a vir da página.
// ---------------------------------------------------------------------------

const POR_PAGINA = 6;
let paginaCatalogo = 1;
let catalogo = [];              // [{loja, categoria, sku, nome, url, preco, tabela, disponivel}]
let categoriasDoCatalogo = [];  // [{loja, categoria, quantidade, atualizadoEm}]

async function carregarCatalogo() {
  try {
    catalogo = [];
    categoriasDoCatalogo = [];
    const lojas = await getDocs(collection(db, "catalogo"));

    for (const loja of lojas.docs) {
      const indices = await getDocs(collection(db, `catalogo/${loja.id}/indice`));
      for (const indice of indices.docs) {
        const dados = indice.data();
        categoriasDoCatalogo.push({
          loja: loja.id,
          categoria: indice.id,
          quantidade: dados.quantidade || 0,
          atualizadoEm: dados.atualizadoEm || null,
        });
        for (const [sku, i] of Object.entries(dados.itens || {})) {
          catalogo.push({
            loja: loja.id, categoria: indice.id, sku,
            nome: i.n || "", url: i.u || "",
            preco: i.p ?? null,          // preço que a vitrine apresenta
            tabela: i.t ?? null,         // preço "de" riscado, quando publicado
            disponivel: i.d ?? null,
          });
        }
      }
    }
  } catch (erro) {
    console.error("falha ao carregar o catálogo", erro);
  }
  paginaCatalogo = 1;
  montarFiltroDeCategoria();
  renderizarCatalogo();
}

function montarFiltroDeCategoria() {
  const alvo = $("categoriaCatalogo");
  const atual = alvo.value;
  alvo.innerHTML =
    `<option value="">todas as categorias</option>` +
    categoriasDoCatalogo
      .map((c) => `<option value="${esc(c.categoria)}">${esc(c.categoria)} (${c.quantidade})</option>`)
      .join("");
  if (atual) alvo.value = atual;
}

/** URLs que o usuário já acompanha, para não oferecer duas vezes. */
function urlsAcompanhadas() {
  const urls = new Set();
  for (const produto of produtos) {
    for (const fonte of produto.fontes) urls.add(fonte.url);
  }
  return urls;
}

function renderizarCatalogo() {
  const grade = $("gradeCatalogo");
  const categoria = $("categoriaCatalogo").value;
  const busca = $("buscaCatalogo").value.trim().toLowerCase();
  const ordem = $("ordemCatalogo").value;
  const seguidas = urlsAcompanhadas();

  let itens = catalogo.filter((i) => i.preco !== null || i.disponivel === false);
  if (categoria) itens = itens.filter((i) => i.categoria === categoria);
  if (busca) itens = itens.filter((i) => i.nome.toLowerCase().includes(busca));
  itens.sort((a, b) => {
    if (ordem === "nome") return a.nome.localeCompare(b.nome, "pt-BR");
    // esgotados vão para o fim, não para o topo com preço nulo
    if (a.preco === null) return 1;
    if (b.preco === null) return -1;
    return a.preco - b.preco;
  });

  const total = categoriasDoCatalogo.reduce((soma, c) => soma + c.quantidade, 0);
  $("catalogoVazio").classList.toggle("oculto", total > 0);

  // Paginação no cliente: o catálogo inteiro já veio numa leitura, então
  // paginar aqui não custa nenhuma leitura a mais — só evita despejar
  // centenas de cartões na tela de uma vez.
  const paginas = Math.max(1, Math.ceil(itens.length / POR_PAGINA));
  paginaCatalogo = Math.min(Math.max(1, paginaCatalogo), paginas);
  const inicio = (paginaCatalogo - 1) * POR_PAGINA;
  const visiveis = itens.slice(inicio, inicio + POR_PAGINA);

  $("resumoCatalogo").textContent = itens.length
    ? `· ${inicio + 1}–${inicio + visiveis.length} de ${itens.length}`
      + (itens.length === total ? "" : ` (${total} no catálogo)`)
    : total ? "· nenhum item com esse filtro" : "";

  $("paginacaoCatalogo").classList.toggle("oculto", itens.length <= POR_PAGINA);
  $("posicaoPagina").textContent = `página ${paginaCatalogo} de ${paginas}`;
  $("btAnterior").disabled = paginaCatalogo <= 1;
  $("btProxima").disabled = paginaCatalogo >= paginas;

  grade.innerHTML = visiveis.map((i) => {
    const jaSegue = seguidas.has(i.url);
    const esgotado = i.disponivel === false;

    // A loja que publica o preço "de" riscado está mostrando o preço de VENDA
    // no destaque. Quem publica só um valor (KaBuM) publica o de tabela — foi
    // medido, 10% a 31% acima da página do produto. O rótulo diz qual é qual.
    const linhaPreco = esgotado
      ? `<div class="tabela"><span class="dica">esgotado</span></div>`
      : i.tabela
        ? `<div class="tabela">${formatarBRL(i.preco)}
             <s class="dica">${formatarBRL(i.tabela)}</s></div>`
        : `<div class="tabela">${formatarBRL(i.preco)}
             <span class="dica">de tabela</span></div>`;

    return `
      <div class="item ${jaSegue ? "seguido" : ""} ${esgotado ? "esgotado" : ""}">
        <div class="titulo" title="${esc(i.nome)}">${esc(i.nome)}</div>
        ${linhaPreco}
        <div class="rodape">
          ${jaSegue
            ? `<span class="ja-segue">★ já acompanhado</span>`
            : esgotado
              ? ""
              : `<button class="discreto acompanhar" data-sku="${esc(i.sku)}">☆ acompanhar</button>`}
          <a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">abrir na loja ↗</a>
        </div>
      </div>`;
  }).join("");

  grade.querySelectorAll(".acompanhar").forEach((botao) => {
    botao.addEventListener("click", () => acompanharDoCatalogo(botao.dataset.sku));
  });
}

/** Favoritar = criar produto + fonte, que é o caminho já testado.
 *  Em vez de uma coleção de favoritos, o item pré-preenche o formulário: o
 *  usuário só decide o preço-alvo, que é a única informação que o catálogo
 *  não tem. */
function acompanharDoCatalogo(sku) {
  const item = catalogo.find((i) => i.sku === sku);
  if (!item) return;

  cancelarEdicao();
  $("nome").value = item.nome;
  $("tolerancia").value = "0";
  $("pares").innerHTML = "";
  const nomeDaLoja =
    (LOJAS.find((l) => l.dominios.some((d) => item.loja.endsWith(d))) || {}).nome || "";
  adicionarParDeFonte({ loja: nomeDaLoja, url: item.url });

  $("alvo").value = "";
  $("alvo").placeholder = `abaixo de ${formatarBRL(item.preco).replace("R$", "").trim()}`;
  $("tituloForm").textContent = "Acompanhar produto do catálogo";
  erroForm(null);
  $("alvo").scrollIntoView({ behavior: "smooth", block: "center" });
  $("alvo").focus();
}

["categoriaCatalogo", "buscaCatalogo", "ordemCatalogo"].forEach((id) => {
  $(id).addEventListener("input", () => {
    paginaCatalogo = 1;   // filtrar sempre volta ao começo
    renderizarCatalogo();
  });
});

document.querySelectorAll(".periodos button[data-escala]").forEach((botao) => {
  botao.addEventListener("click", () => {
    escala = botao.dataset.escala;
    document.querySelectorAll(".periodos button[data-escala]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b === botao)));
    desenhar();
    renderizarTabela();
  });
});

function irParaPagina(delta) {
  paginaCatalogo += delta;
  renderizarCatalogo();
  $("gradeCatalogo").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

$("btAnterior").addEventListener("click", () => irParaPagina(-1));
$("btProxima").addEventListener("click", () => irParaPagina(1));

// ---------------------------------------------------------------------------
// Histórico: 1d vem do bruto, os demais do rollup diário
// ---------------------------------------------------------------------------

const chaveMes = (d) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
const chaveAno = (d) => String(d.getUTCFullYear());
const chaveDia = (d) =>
  "d" + d.getUTCFullYear() +
  String(d.getUTCMonth() + 1).padStart(2, "0") +
  String(d.getUTCDate()).padStart(2, "0");

function ligarSeletorDePeriodo() {
  document.querySelectorAll(".periodos button").forEach((botao) => {
    botao.addEventListener("click", () => {
      periodo = botao.dataset.periodo;
      document.querySelectorAll(".periodos button").forEach((b) =>
        b.setAttribute("aria-pressed", String(b === botao)));
      agendarHistorico();
    });
  });
}
ligarSeletorDePeriodo();

async function lerBucket(caminho) {
  const instantaneo = await getDoc(doc(db, caminho));
  return instantaneo.exists() ? instantaneo.data() : null;
}

/** 1d: histórico bruto do mês, filtrado nas últimas 24h. */
async function serie1d(produtoId, fonte) {
  const agora = new Date();
  const corte = new Date(agora.getTime() - 24 * 3600 * 1000);
  const meses = new Set([chaveMes(agora), chaveMes(corte)]);  // cobre a virada
  const pontos = [];
  for (const mes of meses) {
    const bucket = await lerBucket(
      `usuarios/${uid}/produtos/${produtoId}/historico/${fonte.id}_${mes}`);
    for (const leitura of (bucket && bucket.leituras) || []) {
      if (leitura.p === null || leitura.p === undefined || leitura.s) continue;
      const quando = leitura.t && leitura.t.toDate ? leitura.t.toDate() : new Date(leitura.t);
      if (quando >= corte) pontos.push({ quando, centavos: leitura.p });
    }
  }
  pontos.sort((a, b) => a.quando - b.quando);
  return pontos;
}

/** 1s / 1m / 1a: rollup diário, usando o fechamento do dia. */
async function serieDiaria(produtoId, fonte, dias) {
  const agora = new Date();
  const anos = new Set();
  const chavesEsperadas = [];
  for (let i = dias - 1; i >= 0; i--) {
    const dia = new Date(agora.getTime() - i * 24 * 3600 * 1000);
    anos.add(chaveAno(dia));
    chavesEsperadas.push({ chave: chaveDia(dia), quando: dia });
  }

  const porChave = new Map();
  for (const ano of anos) {
    const bucket = await lerBucket(
      `usuarios/${uid}/produtos/${produtoId}/diario/${fonte.id}_${ano}`);
    for (const [chave, valores] of Object.entries((bucket && bucket.dias) || {})) {
      if (typeof valores.fech === "number") porChave.set(chave, valores.fech);
    }
  }

  return chavesEsperadas
    .filter(({ chave }) => porChave.has(chave))
    .map(({ chave, quando }) => ({ quando, centavos: porChave.get(chave) }));
}

const DIAS_POR_PERIODO = { "1s": 7, "1m": 30, "1a": 365 };

let temporizadorHistorico = null;

/** Coalesce recargas: cada produto e cada fonte tem seu próprio listener, e
 *  sem isso a entrada no app dispararia uma recarga completa por snapshot. */
function agendarHistorico() {
  clearTimeout(temporizadorHistorico);
  temporizadorHistorico = setTimeout(() => carregarHistorico(), 300);
}

async function carregarHistorico() {
  const rastreados = produtos.slice(0, MAX_SERIES);
  const excedente = produtos.length - rastreados.length;

  $("tituloGrafico").textContent =
    `Histórico — ${rastreados.length} produto(s) acompanhado(s)` +
    (excedente > 0 ? ` (${excedente} fora do gráfico: a paleta tem ${MAX_SERIES} cores)` : "");

  if (!rastreados.length) { dadosDoGrafico = null; desenhar(); return; }

  const cores = tokens().series;
  const eixoTempo = new Map();
  const porProduto = [];

  for (let indice = 0; indice < rastreados.length; indice++) {
    const produto = rastreados[indice];
    const fontes = produto.fontes.filter((f) => f.status === "ok");

    // Uma série por PRODUTO. O valor é o MENOR entre as fontes naquele
    // instante — a mesma regra que a máquina de estados usa para decidir
    // alerta, para o gráfico não contar uma história diferente da mensagem.
    const menorPorRotulo = new Map();
    for (const fonte of fontes) {
      const pontos = periodo === "1d"
        ? await serie1d(produto.id, fonte)
        : await serieDiaria(produto.id, fonte, DIAS_POR_PERIODO[periodo]);

      for (const ponto of pontos) {
        const rotulo = formatoRotulo(ponto.quando);
        if (!eixoTempo.has(rotulo)) eixoTempo.set(rotulo, ponto.quando);
        const atual = menorPorRotulo.get(rotulo);
        if (atual === undefined || ponto.centavos < atual) {
          menorPorRotulo.set(rotulo, ponto.centavos);
        }
      }
    }
    porProduto.push({
      id: produto.id,
      nome: produto.dados.nome,
      // cor pela posição estável do produto, nunca pelo rank do preço
      cor: cores[indice % MAX_SERIES],
      porRotulo: menorPorRotulo,
    });
  }

  const rotulos = [...eixoTempo.entries()].sort((a, b) => a[1] - b[1]).map(([r]) => r);

  dadosDoGrafico = {
    rotulos,
    series: porProduto.map((s) => ({
      id: s.id,
      nome: s.nome,
      cor: s.cor,
      valores: rotulos.map((r) => (s.porRotulo.has(r) ? s.porRotulo.get(r) : null)),
    })),
  };

  desenhar();
  renderizarTabela();
}

function formatoRotulo(quando) {
  return periodo === "1d"
    ? quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : quando.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

// ---------------------------------------------------------------------------
// Gráfico
// ---------------------------------------------------------------------------

/** Fio vertical de referência sob o ponto ativo. */
const pluginFioVertical = {
  id: "fioVertical",
  afterDatasetsDraw(gr, _args, opcoes) {
    const ativos = gr.tooltip && gr.tooltip.getActiveElements
      ? gr.tooltip.getActiveElements() : [];
    if (!ativos.length) return;
    const x = ativos[0].element.x;
    const { top, bottom } = gr.chartArea;
    const ctx = gr.ctx;
    ctx.save();
    ctx.lineWidth = 1;
    ctx.strokeStyle = opcoes.cor;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.restore();
  },
};

/** Rótulo só na ponta de cada série — nunca um número em cada ponto. */
const pluginRotuloDePonta = {
  id: "rotuloDePonta",
  afterDatasetsDraw(gr, _args, opcoes) {
    const ctx = gr.ctx;
    ctx.save();
    ctx.font = "600 11px system-ui, -apple-system, sans-serif";
    ctx.textBaseline = "middle";
    gr.data.datasets.forEach((conjunto, indice) => {
      const meta = gr.getDatasetMeta(indice);
      if (meta.hidden) return;
      let ultimo = null;
      let indiceDoUltimo = -1;
      for (let i = conjunto.data.length - 1; i >= 0; i--) {
        if (conjunto.data[i] !== null && meta.data[i]) {
          ultimo = meta.data[i];
          indiceDoUltimo = i;
          break;
        }
      }
      if (!ultimo) return;
      const texto = formatarValorDoEixo(conjunto.data[indiceDoUltimo]);
      const largura = ctx.measureText(texto).width;
      let x = ultimo.x + 8;
      if (x + largura > gr.chartArea.right) x = ultimo.x - largura - 8;
      // texto em tinta, nunca na cor da série: a identidade vem da legenda
      ctx.fillStyle = opcoes.cor;
      ctx.fillText(texto, x, ultimo.y);
    });
    ctx.restore();
  },
};

/**
 * Produtos de faixas de preço muito diferentes no mesmo eixo tornam os baratos
 * invisíveis. Indexar cada série ao próprio primeiro ponto (=100) põe todas na
 * mesma escala e mostra o que interessa quando se compara: quem caiu mais.
 *
 * Isto NÃO é o caminho do dinheiro — é um percentual derivado, só para desenho.
 * Os centavos continuam intactos em `dadosDoGrafico`.
 */
function valoresNaEscala(serie) {
  if (escala === "reais") return serie.valores;
  const base = serie.valores.find((v) => v !== null && v > 0);
  if (!base) return serie.valores.map(() => null);
  return serie.valores.map((v) => (v === null ? null : (v * 100) / base));
}

function formatarValorDoEixo(valor) {
  return escala === "reais"
    ? formatarBRL(valor)
    : `${valor >= 100 ? "+" : ""}${(valor - 100).toFixed(1)}%`;
}

function desenhar() {
  const t = tokens();
  const vazio = !dadosDoGrafico || !dadosDoGrafico.series.some((s) => s.valores.some((v) => v !== null));
  $("semDados").classList.toggle("oculto", !vazio);
  $("molduraGrafico").classList.toggle("oculto", vazio);

  if (grafico) { grafico.destroy(); grafico = null; }
  if (vazio) return;

  const denso = dadosDoGrafico.rotulos.length > 40;

  grafico = new Chart($("grafico"), {
    type: "line",
    data: {
      labels: dadosDoGrafico.rotulos,
      datasets: dadosDoGrafico.series.map((serie) => ({
        label: serie.nome,
        data: valoresNaEscala(serie),
        borderColor: serie.cor,
        backgroundColor: serie.cor,
        // destaque avaliado no DESENHO: clicar num cartão não pode exigir
        // uma nova leitura do Firestore só para engrossar uma linha
        borderWidth: serie.id === idSelecionado ? 3 : 2,
        pointRadius: denso ? 0 : 4,   // 8px de diâmetro quando visível
        pointHoverRadius: 5,
        pointBorderColor: t.superficie,
        pointBorderWidth: 2,          // anel de 2px na superfície
        tension: 0.15,
        spanGaps: true,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { right: 68, top: 8 } },   // espaço para o rótulo de ponta
      interaction: { mode: "index", intersect: false },
      plugins: {
        // legenda sempre presente com 2+ séries; com uma só, o título nomeia
        legend: {
          display: dadosDoGrafico.series.length >= 2,
          position: "top",
          align: "start",
          labels: { color: t.tinta2, boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 16 },
        },
        tooltip: {
          backgroundColor: t.superficie,
          borderColor: t.eixo,
          borderWidth: 1,
          titleColor: t.tinta,
          bodyColor: t.tinta2,
          padding: 10,
          displayColors: true,
          callbacks: {
            // o tooltip mostra sempre o valor em reais, mesmo na escala
            // indexada: o percentual diz o movimento, o real diz o preço
            label: (ctx) => {
              const centavos = dadosDoGrafico.series[ctx.datasetIndex].valores[ctx.dataIndex];
              const emReais = formatarBRL(centavos);
              return escala === "reais"
                ? ` ${ctx.dataset.label}: ${emReais}`
                : ` ${ctx.dataset.label}: ${formatarValorDoEixo(ctx.parsed.y)} (${emReais})`;
            },
          },
        },
        fioVertical: { cor: t.eixo },
        rotuloDePonta: { cor: t.tinta2 },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: t.eixo },
          ticks: {
            color: t.fraca, maxRotation: 0, autoSkip: true, maxTicksLimit: 8,
            font: { size: 11 },
          },
        },
        y: {
          grid: { color: t.grade, drawTicks: false },   // hairline sólida
          border: { display: false },
          ticks: {
            color: t.fraca, font: { size: 11 },
            callback: (valor) => formatarValorDoEixo(valor),
          },
        },
      },
    },
    plugins: [pluginFioVertical, pluginRotuloDePonta],
  });
}

// ---------------------------------------------------------------------------
// Tabela equivalente (gêmea do gráfico, exigida pela acessibilidade)
// ---------------------------------------------------------------------------

$("btTabela").addEventListener("click", () => {
  const botao = $("btTabela");
  const mostrando = botao.getAttribute("aria-pressed") === "true";
  botao.setAttribute("aria-pressed", String(!mostrando));
  botao.textContent = mostrando ? "Ver como tabela" : "Ver como gráfico";
  $("areaTabela").classList.toggle("oculto", mostrando);
  $("molduraGrafico").classList.toggle("oculto", !mostrando);
});

function renderizarTabela() {
  if (!dadosDoGrafico) { $("areaTabela").innerHTML = ""; return; }
  const cabecalho = dadosDoGrafico.series.map((s) => `<th class="num">${esc(s.nome)}</th>`).join("");
  const linhas = dadosDoGrafico.rotulos.map((rotulo, i) => `
    <tr>
      <td>${rotulo}</td>
      ${dadosDoGrafico.series.map((s) => `<td class="num">${formatarBRL(s.valores[i])}</td>`).join("")}
    </tr>`).join("");
  $("areaTabela").innerHTML =
    `<table><thead><tr><th>Quando</th>${cabecalho}</tr></thead><tbody>${linhas}</tbody></table>`;
}
