// `npm test` (node --test).
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import {
  estatisticasDaSemana, noMenorPrecoHistorico, variacaoVsSemana,
} from "./estatisticasCatalogo.js";

describe("estatisticasDaSemana", () => {
  it("calcula média, menor e maior da janela", () => {
    const s = estatisticasDaSemana({ d20260810: 100_00, d20260811: 200_00, d20260812: 300_00 });
    assert.equal(s.media, 200_00);
    assert.equal(s.menor, 100_00);
    assert.equal(s.maior, 300_00);
    assert.equal(s.dias, 3);
  });

  it("conta os dias PRESENTES, não assume 7", () => {
    // Item esgotado não grava ponto. Dividir por 7 quando só há 3 dias daria
    // uma média artificialmente baixa e um "abaixo da média" falso.
    const s = estatisticasDaSemana({ d20260810: 90_00, d20260811: 90_00, d20260812: 90_00 });
    assert.equal(s.media, 90_00);
  });

  it("devolve null sem histórico, em vez de zeros", () => {
    // Zero seria exibido como R$ 0,00 e pareceria uma pechincha.
    assert.equal(estatisticasDaSemana({}), null);
    assert.equal(estatisticasDaSemana(null), null);
    assert.equal(estatisticasDaSemana({ d20260810: 0 }), null);
  });

  it("arredonda a média em vez de truncar", () => {
    const s = estatisticasDaSemana({ a: 100, b: 101 });
    assert.equal(s.media, 101);   // 100,5 -> 101, não 100
  });
});

describe("noMenorPrecoHistorico", () => {
  const item = (preco, min, dias) => ({
    preco, minHistorico: min, diasDeHistorico: dias,
  });

  it("empatar com a mínima conta como menor preço", () => {
    assert.equal(noMenorPrecoHistorico(item(100_00, 100_00, 5)), true);
    assert.equal(noMenorPrecoHistorico(item(100_01, 100_00, 5)), false);
  });

  it("um dia só de histórico não é recorde de nada", () => {
    assert.equal(noMenorPrecoHistorico(item(100_00, 100_00, 1)), false);
  });

  it("item sem preço ou sem mínima não recebe selo", () => {
    assert.equal(noMenorPrecoHistorico(item(null, 100_00, 5)), false);
    assert.equal(noMenorPrecoHistorico(item(100_00, null, 5)), false);
    assert.equal(noMenorPrecoHistorico(undefined), false);
  });
});

describe("variacaoVsSemana", () => {
  it("dá o percentual inteiro contra a média", () => {
    assert.equal(variacaoVsSemana(110_00, { media: 100_00 }), 10);
    assert.equal(variacaoVsSemana(90_00, { media: 100_00 }), -10);
  });

  it("some quando não há média", () => {
    assert.equal(variacaoVsSemana(100_00, null), null);
    assert.equal(variacaoVsSemana(100_00, { media: 0 }), null);
  });
});
