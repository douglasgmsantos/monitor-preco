// Busca por TERMOS, não por substring.
//
// O problema que isto resolve: "ddr5 16gb" não é substring de "Memória Ram
// Adata Xpg Lancer Blade Ddr5 16gb 6000mhz" — entre "Ddr5" e "16gb" o nome real
// pode ter qualquer coisa, e a ordem que o usuário digita não é a da loja.
// Buscar a frase inteira devolvia 0 itens para um catálogo que tinha o produto.
//
// A regra é E, não OU: todo termo digitado precisa aparecer. Com OU, "ddr5
// 16gb" traria todo SSD de 16gb e toda placa-mãe DDR5 — mais barulho que a
// busca vazia, que é o oposto de refinar.
//
// Acento é ignorado dos dois lados: as lojas escrevem "Memória", e ninguém
// digita acento em campo de busca.

/** "Memória RAM" -> "memoria ram". NFD separa a letra do acento; o range
 *  ̀-ͯ é o bloco de diacríticos combinantes. */
export function normalizar(texto) {
  return (texto || "")
    .toString()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/** "ddr5+16gb" ou "ddr5 16gb" -> ["ddr5", "16gb"].
 *
 *  O `+` entra porque é como se escreve busca combinada em site de busca, e
 *  aparece colado sem espaço. Vírgula e ponto-e-vírgula pela mesma razão. */
export function termosDe(consulta) {
  return normalizar(consulta)
    .split(/[\s+,;]+/)
    .filter(Boolean);
}

/** True quando TODOS os termos aparecem em ALGUM dos campos.
 *
 *  Os campos são testados juntos, não um a um: "kabum ddr5" precisa casar com
 *  a loja num campo e o modelo no outro. Exigir todos os termos no mesmo campo
 *  quebraria essa combinação, que é justamente a busca mais útil.
 */
export function casaTermos(consulta, ...campos) {
  const termos = termosDe(consulta);
  if (!termos.length) return true;
  const alvo = campos.map(normalizar).join(" ");
  return termos.every((termo) => alvo.includes(termo));
}
