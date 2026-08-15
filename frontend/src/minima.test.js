// `npm test` (node --test).
//
// O que se protege aqui não é a aritmética do mínimo — é a HONESTIDADE do selo
// e o fato de tela e Telegram dizerem a mesma coisa. Se o cartão anunciar
// recorde com menos história do que o coletor exige, o usuário vê o selo, não
// recebe a mensagem, e conclui que o alerta está quebrado.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { DIAS_PARA_AFIRMAR, selo } from "./minima.js";

const resumo = (minimo, diasObservados) => ({ minimo, diasObservados });

describe("selo da mínima", () => {
  it("anuncia recorde quando o preço empata com a mínima", () => {
    // `<=`, não `<`: empatar É o menor preço visto. Exigir superar por um
    // centavo esconderia justamente a melhor oferta disponível.
    const s = selo(100_000, resumo(100_000, 30));
    assert.equal(s.tipo, "recorde");
    assert.match(s.texto, /Menor preço em 30 dias/);
  });

  it("não anuncia recorde com histórico raso", () => {
    const s = selo(100_000, resumo(100_000, 2));
    assert.equal(s.tipo, "raso");
    assert.doesNotMatch(s.texto, /Menor preço em/);
  });

  it("mostra o quanto está acima da mínima, em inteiro", () => {
    const s = selo(113_000, resumo(100_000, 30));
    assert.equal(s.tipo, "acima");
    assert.match(s.texto, /^13% acima da mínima$/);
  });

  it("some quando não há mínima ou não há preço", () => {
    assert.equal(selo(100_000, resumo(null, 30)), null);
    assert.equal(selo(null, resumo(100_000, 30)), null);
    assert.equal(selo(100_000, null), null);
  });

  it("some quando está acima por menos de 1%", () => {
    // "0% acima da mínima" é uma linha que não informa nada e ocupa espaço.
    assert.equal(selo(100_100, resumo(100_000, 30)), null);
  });
});

describe("acordo com o coletor", () => {
  it("usa o mesmo piso de dias que coletor/repositorio.py", () => {
    // Duplicação consciente: não há como o Vue importar Python. O teste é a
    // costura — se alguém mudar um lado, ele quebra em vez de a tela e o
    // Telegram passarem a discordar em silêncio.
    const py = readFileSync(
      new URL("../../coletor/repositorio.py", import.meta.url), "utf8");
    const achado = py.match(/DIAS_PARA_AFIRMAR_MINIMA\s*=\s*(\d+)/);
    assert.ok(achado, "DIAS_PARA_AFIRMAR_MINIMA sumiu de repositorio.py");
    assert.equal(Number(achado[1]), DIAS_PARA_AFIRMAR);
  });

  it("usa a mesma janela de dias", () => {
    const py = readFileSync(
      new URL("../../coletor/repositorio.py", import.meta.url), "utf8");
    const achado = py.match(/DIAS_DA_MINIMA\s*=\s*(\d+)/);
    assert.ok(achado, "DIAS_DA_MINIMA sumiu de repositorio.py");
    // A janela do front vem do padrão de `selo(...)`; o texto prova o valor.
    assert.match(selo(100_000, resumo(100_000, 30)).texto,
                 new RegExp(`${achado[1]} dias`));
  });
});
