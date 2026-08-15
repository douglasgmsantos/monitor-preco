// ---------------------------------------------------------------------------
// Lojas
//
// LISTA FECHADA: o cadastro só aceita estas quatro. Não existe mais "Outra
// loja" — a opção de texto livre deixava o usuário cadastrar uma URL que o
// coletor não sabe ler, e o resultado era uma fonte que falhava cinco vezes e
// morria. Recusar na entrada é mais honesto que aceitar e desistir depois.
//
// Espelho de `coletor/lojas.py`, que é a fonte de verdade. Mudou lá, muda aqui.
// A diferença entre as duas: o front recusa ANTES de gravar, o coletor recusa
// DEPOIS de buscar. As duas checagens existem porque as rules do Firestore não
// sabem validar domínio.
//
// Medido em 2026-08-12 contra os templates em `coletor/templates/`:
//   KaBuM, Terabyte, Pichau  →  JSON-LD (schema.org), caminho preferido
//   Amazon                   →  sem JSON-LD; seletores de DOM, e exige
//                               cabeçalhos de navegador na busca
// ---------------------------------------------------------------------------

export const LOJAS = [
  { nome: "KaBuM",         dominios: ["kabum.com.br"] },
  { nome: "Terabyte Shop", dominios: ["terabyteshop.com.br"] },
  { nome: "Pichau",        dominios: ["pichau.com.br"] },
  { nome: "Amazon",        dominios: ["amazon.com.br"] },
  // Entrou em 2026-08-15. Só pelo caminho de captura: busca direta é
  // redirecionada para /gz/account-verification. Ver coletor/lojas.py.
  { nome: "Mercado Livre", dominios: ["mercadolivre.com.br", "mercadolibre.com"] },
];

/** Domínios confirmadamente incompatíveis, com o motivo verificado.
 *
 *  Com a lista fechada, `hostCombinaComLoja` já recusaria qualquer domínio de
 *  fora. Esta tabela sobrevive pela MENSAGEM: colar uma URL da Americanas e ler
 *  "monta a página por JavaScript" ensina algo; ler "a URL não é de KaBuM" não.
 */
export const DOMINIOS_INCOMPATIVEIS = [
  // MERCADO LIVRE SAIU DAQUI em 2026-08-15, quando entrou em LOJAS.
  //
  // O motivo antigo dizia "monta a página por JavaScript", e isso estava
  // ERRADO: o HTML servido traz `ld+json` com Product e price (medido no
  // template — 5549.9 BRL, InStock). O que existe é bloqueio anti-bot por IP,
  // que redireciona o fetch direto para /gz/account-verification. Coisa
  // diferente, e resolvida pelo caminho de captura do n8n.
  //
  // A outra metade ("a API oficial não devolve preço") continua verdadeira,
  // mas virou irrelevante: não usamos a API.
  { padrao: /(^|\.)magazineluiza\.com\.br$/, motivo: "o Magazine Luiza bloqueia requisições automatizadas (HTTP 403)" },
  { padrao: /(^|\.)magalu\.com\.br$/, motivo: "o Magalu bloqueia requisições automatizadas (HTTP 403)" },
  { padrao: /(^|\.)americanas\.com\.br$/, motivo: "a Americanas monta a página por JavaScript; o HTML não traz preço nem produto" },
  { padrao: /(^|\.)submarino\.com\.br$/, motivo: "mesma plataforma da Americanas: página montada por JavaScript" },
  { padrao: /(^|\.)shoptime\.com\.br$/, motivo: "mesma plataforma da Americanas: página montada por JavaScript" },
  { padrao: /(^|\.)carrefour\.com\.br$/, motivo: "o Carrefour saiu da lista: publica JSON-LD, mas nunca foi confirmado a partir do datacenter onde o coletor roda" },
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
  // Sem definição a loja não está na lista fechada: recusa, não libera. Antes
  // esta linha devolvia `true` para acomodar "Outra loja"; com a lista fechada,
  // manter o `true` seria deixar a porta que a lista fechada veio fechar.
  if (!definicao) return false;
  if (!host) return false;
  return definicao.dominios.some((d) => host === d || host.endsWith("." + d));
}

/** A loja da lista fechada que atende esta URL, ou "" se nenhuma.
 *  O domínio determina a loja sem ambiguidade, então dá para preencher o campo
 *  sozinho quando o usuário cola a URL primeiro. */
export function lojaSugeridaPelaUrl(url) {
  return nomeDaLojaPorHost(hostDaUrl(url));
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
  "Pichau": "PCH",
  "Amazon": "AMZ",
  // Fontes gravadas antes da lista fechada continuam no banco e precisam de
  // sigla para renderizar.
  "Carrefour": "CRF",
};

export function siglaDaLoja(nome) {
  if (SIGLAS[nome]) return SIGLAS[nome];
  const limpo = String(nome || "").replace(/[^a-zA-Z]/g, "");
  if (!limpo) return "LJA";
  const consoantes = limpo.slice(1).replace(/[aeiouAEIOU]/g, "");
  return (limpo[0] + (consoantes || limpo.slice(1))).slice(0, 3).toUpperCase();
}
