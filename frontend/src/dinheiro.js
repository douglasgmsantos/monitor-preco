// Dinheiro trafega como INTEIRO DE CENTAVOS em todo o caminho. A única divisão
// por 100 do projeto está em `formatarBRL`, e existe só para exibir.

/** A ÚNICA divisão por 100 do projeto. Existe só para exibição.
 *
 *  Centavos ",00" são omitidos de propósito — o desenho da vitrine usa números
 *  grandes em monoespaçada ("R$ 24.190") e o ",00" só acrescenta ruído. Quando
 *  há centavos de verdade ("R$ 1.789,90"), eles aparecem.
 */
export function formatarBRL(centavos) {
  if (centavos === null || centavos === undefined) return "—";
  const inteiro = centavos % 100 === 0;
  return (centavos / 100).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: inteiro ? 0 : 2,
    maximumFractionDigits: inteiro ? 0 : 2,
  });
}

/**
 * Texto em reais -> inteiro de centavos, ou null se inválido.
 *
 * Espelha os passos 2 a 6 da seção 7.5 da spec. A fonte da verdade é
 * `normalizar_para_centavos` em coletor/parser.py; esta cópia existe porque a
 * seção 12 exige converter na entrada, antes de gravar no Firestore.
 */
export function paraCentavos(texto) {
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

/** Variação percentual contra a média, para o "-12% vs média" do cartão. */
export function variacaoPct(atual, media) {
  if (typeof atual !== "number" || typeof media !== "number" || media <= 0) return null;
  return Math.round(((atual - media) * 100) / media);
}
