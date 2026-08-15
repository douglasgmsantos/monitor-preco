// `npm test` (node --test).
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { LOJAS, motivoDeIncompatibilidade } from "./lojas.js";

describe("lista de lojas x lista de incompatíveis", () => {
  it("nenhuma loja suportada aparece como incompatível", () => {
    // A checagem de incompatibilidade roda ANTES da de loja suportada, então
    // uma loja nas duas listas é recusada no cadastro mesmo estando pronta —
    // com uma mensagem que afirma algo falso sobre ela.
    //
    // Aconteceu em 2026-08-15: o Mercado Livre entrou em LOJAS e ficou em
    // DOMINIOS_INCOMPATIVEIS, e o app dizia "monta a página por JavaScript"
    // para uma loja cujo JSON-LD tinha acabado de ser medido.
    for (const loja of LOJAS) {
      for (const dominio of loja.dominios) {
        const motivo = motivoDeIncompatibilidade(`https://www.${dominio}/produto/1`);
        assert.equal(
          motivo, null,
          `${loja.nome} está em LOJAS e em DOMINIOS_INCOMPATIVEIS ("${motivo}")`,
        );
      }
    }
  });

  it("domínio de fora continua recusado com motivo", () => {
    const motivo = motivoDeIncompatibilidade("https://www.americanas.com.br/p/1");
    assert.ok(motivo && motivo.length > 10);
  });
});
