// ---------------------------------------------------------------------------
// Lojas
//
// Só entram aqui lojas em que foi VERIFICADO, na página de produto real, que o
// preço vem em <script type="application/ld+json"> por HTTP simples e que o
// User-Agent honesto do coletor não é bloqueado. Ampliar a lista exige repetir
// essa verificação — não é palpite. (Portado de publico/app.js.)
// ---------------------------------------------------------------------------

export const LOJAS = [
  { nome: "KaBuM",         dominios: ["kabum.com.br"] },
  { nome: "Terabyte Shop", dominios: ["terabyteshop.com.br"] },
  { nome: "Carrefour",     dominios: ["carrefour.com.br"] },
];

export const LOJA_OUTRA = "__outra__";

/** Domínios confirmadamente incompatíveis, com o motivo verificado. */
export const DOMINIOS_INCOMPATIVEIS = [
  { padrao: /(^|\.)amazon\.com\.br$/, motivo: "a Amazon não publica JSON-LD nas páginas de produto" },
  { padrao: /(^|\.)mercadolivre\.com\.br$/, motivo: "o Mercado Livre monta a página por JavaScript; o HTML não traz JSON-LD" },
  { padrao: /(^|\.)magazineluiza\.com\.br$/, motivo: "o Magazine Luiza bloqueia requisições automatizadas (HTTP 403)" },
  { padrao: /(^|\.)magalu\.com\.br$/, motivo: "o Magalu bloqueia requisições automatizadas (HTTP 403)" },
  // A Pichau responde de IP residencial mas recusa o datacenter onde o coletor
  // roda. Como o coletor SÓ roda de lá, para este sistema ela é inviável.
  { padrao: /(^|\.)pichau\.com\.br$/, motivo: "a Pichau recusa requisições do datacenter onde o coletor roda (HTTP 403)" },
  { padrao: /(^|\.)americanas\.com\.br$/, motivo: "a Americanas monta a página por JavaScript; o HTML não traz preço nem produto" },
  { padrao: /(^|\.)submarino\.com\.br$/, motivo: "mesma plataforma da Americanas: página montada por JavaScript" },
  { padrao: /(^|\.)shoptime\.com\.br$/, motivo: "mesma plataforma da Americanas: página montada por JavaScript" },
];

export function hostDaUrl(url) {
  try { return new URL(url).hostname.toLowerCase().replace(/^www\./, ""); }
  catch { return null; }
}

export function motivoDeIncompatibilidade(url) {
  const host = hostDaUrl(url);
  if (!host) return null;
  const achado = DOMINIOS_INCOMPATIVEIS.find((d) => d.padrao.test(host));
  return achado ? achado.motivo : null;
}

export function hostCombinaComLoja(url, loja) {
  const host = hostDaUrl(url);
  const definicao = LOJAS.find((l) => l.nome === loja);
  if (!host || !definicao) return true;   // "Outra loja": nada a comparar
  return definicao.dominios.some((d) => host === d || host.endsWith("." + d));
}

export function nomeDaLojaPorHost(host) {
  if (!host) return "";
  const achado = LOJAS.find((l) => l.dominios.some((d) => host === d || host.endsWith("." + d)));
  return achado ? achado.nome : "";
}

/** Versão curta da URL para exibir: sem esquema, sem `www.`, sem query string.
 *  A URL completa fica no href e no title. */
export function encurtarUrl(url, limite = 34) {
  let texto = url;
  try {
    const partes = new URL(url);
    texto = partes.hostname.replace(/^www\./, "") + partes.pathname.replace(/\/$/, "");
  } catch {
    /* URL malformada: mostra o que veio, truncado */
  }
  return texto.length <= limite ? texto : texto.slice(0, limite - 1) + "…";
}

/** Sigla de 3 letras para o "logotipo" da fonte (AMZ, KBM…), como no desenho.
 *  Lojas conhecidas têm sigla fixa; as demais ganham uma heurística estável. */
const SIGLAS = {
  "KaBuM": "KBM",
  "Terabyte Shop": "TRB",
  "Carrefour": "CRF",
};

export function siglaDaLoja(nome) {
  if (SIGLAS[nome]) return SIGLAS[nome];
  const limpo = String(nome || "").replace(/[^a-zA-Z]/g, "");
  if (!limpo) return "LJA";
  const consoantes = limpo.slice(1).replace(/[aeiouAEIOU]/g, "");
  return (limpo[0] + (consoantes || limpo.slice(1))).slice(0, 3).toUpperCase();
}
