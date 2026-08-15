// Roda com `npm test` (node --test, embutido no Node 18+ — sem dependência nova).
//
// Os casos vieram de uma busca real que falhou: "ddr5+16gb" devolvia 0 itens
// num catálogo com 104 memórias DDR5 de 16 GB, porque a busca era substring da
// frase inteira. Medido contra os 3.538 itens de produção em 2026-08-15.
import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { casaTermos, normalizar, termosDe } from "./busca.js";

const NOME = "Memória Ram Adata Xpg Lancer Blade Ddr5 16gb 6000mhz Cl30";

describe("normalizar", () => {
  it("tira acento e caixa", () => {
    assert.equal(normalizar("Memória RAM"), "memoria ram");
  });

  it("aguenta nulo e número sem estourar", () => {
    assert.equal(normalizar(null), "");
    assert.equal(normalizar(undefined), "");
    assert.equal(normalizar(16), "16");
  });
});

describe("termosDe", () => {
  it("separa por espaço, + , e ;", () => {
    assert.deepEqual(termosDe("ddr5+16gb"), ["ddr5", "16gb"]);
    assert.deepEqual(termosDe("ddr5 16gb"), ["ddr5", "16gb"]);
    assert.deepEqual(termosDe("ddr5, 16gb; 6000mhz"), ["ddr5", "16gb", "6000mhz"]);
  });

  it("descarta separador sobrando em vez de gerar termo vazio", () => {
    // Um termo "" casaria com tudo e a busca deixaria de filtrar.
    assert.deepEqual(termosDe("  ddr5   16gb  "), ["ddr5", "16gb"]);
    assert.deepEqual(termosDe("+++"), []);
  });
});

describe("casaTermos", () => {
  it("acha o produto com os termos em qualquer ordem", () => {
    assert.equal(casaTermos("ddr5+16gb", NOME), true);
    assert.equal(casaTermos("ddr5 16gb", NOME), true);
    assert.equal(casaTermos("16gb ddr5", NOME), true);
  });

  it("é E, não OU", () => {
    // Com OU, "ddr5 32gb" traria toda memória DDR5 do catálogo — 369 itens —
    // e a busca ficaria mais ruidosa do que não buscar nada.
    assert.equal(casaTermos("ddr5 32gb", NOME), false);
    assert.equal(casaTermos("ddr4 16gb", NOME), false);
  });

  it("ignora acento nos dois lados", () => {
    assert.equal(casaTermos("memoria", NOME), true);
    assert.equal(casaTermos("MEMÓRIA", NOME), true);
  });

  it("combina termos entre campos diferentes", () => {
    // "kabum 9070" casa a loja num campo e o modelo no outro. Exigir todos os
    // termos no MESMO campo mataria a busca mais útil de quem segue vários.
    assert.equal(casaTermos("kabum 9070", "RX 9070 XT", "KaBuM"), true);
    assert.equal(casaTermos("amazon 9070", "RX 9070 XT", "KaBuM"), false);
  });

  it("busca vazia não filtra nada", () => {
    assert.equal(casaTermos("", NOME), true);
    assert.equal(casaTermos("   ", NOME), true);
  });

  it("não estoura com campo ausente", () => {
    assert.equal(casaTermos("ddr5", null, undefined, NOME), true);
  });
});
