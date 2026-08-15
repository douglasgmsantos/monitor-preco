// "É barato?" — a pergunta que o valor máximo não responde.
//
// O máximo é um número que o usuário chutou; a mínima é fato medido. Dizer
// "R$ 4.899 (limite R$ 6.000)" não ajuda ninguém a decidir. Dizer "R$ 4.899,
// menor preço em 30 dias" ajuda.
//
// Espelha `MinimaHistorica` em coletor/repositorio.py, incluindo o piso de
// dias. Um teste mantém os dois números iguais — se a tela afirmasse recorde
// com menos história que o Telegram, o usuário veria o selo e nunca receberia
// a mensagem correspondente, e concluiria que o alerta está quebrado.

// Com menos que isto, "menor preço já visto" é quase sempre verdade e não
// informa nada: o produto acabou de entrar. Dizer mesmo assim treina o usuário
// a ignorar o selo — o pior desfecho para um sinal que existe para justificar
// uma compra.
export const DIAS_PARA_AFIRMAR = 7;

/** Como exibir a relação entre o preço de agora e a mínima da janela.
 *
 *  Devolve `null` quando não há o que dizer — e a ausência é deliberada: um
 *  selo "não é o menor preço" em todo cartão seria ruído em cima de ruído.
 */
export function selo(precoAtual, resumo, dias = 30) {
  if (!resumo || typeof precoAtual !== "number") return null;

  const minimo = resumo.minimo;
  const observados = resumo.diasObservados || 0;
  if (typeof minimo !== "number") return null;

  if (observados < DIAS_PARA_AFIRMAR) {
    // Mostra o dado, sem a afirmação. O usuário vê que o histórico é curto em
    // vez de receber um recorde inventado.
    return {
      tipo: "raso",
      texto: `menor visto: ${formatar(minimo)}`,
      detalhe: `só ${observados} dia(s) de histórico — pouco para chamar de recorde`,
    };
  }

  if (precoAtual <= minimo) {
    return {
      tipo: "recorde",
      texto: `Menor preço em ${dias} dias`,
      detalhe: `nenhum preço abaixo de ${formatar(minimo)} nos últimos ${observados} dia(s)`,
    };
  }

  // Quanto acima da mínima. Inteiro: "13% acima da mínima" decide uma compra;
  // "12,7%" não decide melhor e ocupa mais espaço.
  const acima = Math.round(((precoAtual - minimo) * 100) / minimo);
  if (acima <= 0) return null;
  return {
    tipo: "acima",
    texto: `${acima}% acima da mínima`,
    detalhe: `mínima de ${dias} dias: ${formatar(minimo)} (${observados} dia(s) observados)`,
  };
}

function formatar(centavos) {
  return (centavos / 100).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
    minimumFractionDigits: centavos % 100 === 0 ? 0 : 2,
    maximumFractionDigits: centavos % 100 === 0 ? 0 : 2,
  });
}
