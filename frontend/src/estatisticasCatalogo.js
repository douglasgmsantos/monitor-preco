// Estatísticas de preço de um item do CATÁLOGO.
//
// A fonte é o campo `h` do item — janela rolante de 7 dias, dia → preço,
// escrita pela raspagem (ver `historico_do_item` em coletor/repositorio.py).
// Ela vem junto do documento que o catálogo já lê para listar, então tudo isto
// custa ZERO leitura extra do Firestore.
//
// Dias sem preço simplesmente não existem no mapa — item esgotado não grava
// ponto. Por isso tudo aqui conta os dias PRESENTES, nunca assume 7.

/** {media, menor, maior, dias} da janela, ou null quando não há histórico. */
export function estatisticasDaSemana(historico) {
  const valores = Object.values(historico || {}).filter(
    (v) => typeof v === "number" && v > 0);
  if (!valores.length) return null;

  const soma = valores.reduce((total, v) => total + v, 0);
  return {
    // Arredonda em vez de truncar: um centavo para baixo em toda média é um
    // viés sistemático, e o custo de acertar é zero.
    media: Math.round(soma / valores.length),
    menor: Math.min(...valores),
    maior: Math.max(...valores),
    dias: valores.length,
  };
}

/** O item está no menor preço já visto desde que entrou na vitrine?
 *
 *  `<=` e não `<`: empatar com a mínima É estar no menor preço. Exigir superar
 *  por um centavo esconderia justamente a melhor oferta.
 *
 *  Diferente do selo dos produtos acompanhados (`minima.js`), aqui NÃO há piso
 *  de dias. São coisas diferentes: lá o selo justifica uma compra e um recorde
 *  falso custa caro; aqui ele só ordena a vitrine, e o preço é o de tabela.
 *  Mesmo assim, um dia só de histórico não é recorde de nada — daí o mínimo de
 *  dois dias distintos abaixo.
 */
export function noMenorPrecoHistorico(item) {
  if (typeof item?.preco !== "number" || typeof item?.minHistorico !== "number") {
    return false;
  }
  if ((item.diasDeHistorico || 0) < 2) return false;
  return item.preco <= item.minHistorico;
}

/** Variação do preço atual contra a média da semana, em % inteiro. */
export function variacaoVsSemana(preco, estatisticas) {
  if (typeof preco !== "number" || !estatisticas || !estatisticas.media) return null;
  return Math.round(((preco - estatisticas.media) * 100) / estatisticas.media);
}
