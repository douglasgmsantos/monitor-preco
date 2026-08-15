// Catálogo (vitrine de descoberta). Uma leitura por categoria: o documento de
// índice traz {sku: {n, u, p, ...}} da categoria inteira. Ler item a item
// custaria uma leitura por produto.
//
// `p` é o preço de TABELA (vitrine), 10% a 31% acima do preço real da página
// do produto — medido em 2026-08-10. Ele nunca dispara alerta; serve para
// achar o produto. Ao acompanhar, o preço passa a vir da página.
import { ref } from "vue";
import { collection, getDocs } from "firebase/firestore";
import { db } from "../firebase.js";

const catalogo = ref([]);
const categorias = ref([]);
const carregado = ref(false);

async function carregarCatalogo() {
  try {
    const itens = [];
    const listaCategorias = [];
    const lojas = await getDocs(collection(db, "catalogo"));

    for (const loja of lojas.docs) {
      const indices = await getDocs(collection(db, `catalogo/${loja.id}/indice`));
      for (const indice of indices.docs) {
        const dados = indice.data();
        listaCategorias.push({
          loja: loja.id,
          categoria: indice.id,
          quantidade: dados.quantidade || 0,
          atualizadoEm: dados.atualizadoEm || null,
        });
        for (const [sku, i] of Object.entries(dados.itens || {})) {
          itens.push({
            loja: loja.id, categoria: indice.id, sku,
            nome: i.n || "", url: i.u || "",
            imagem: i.img || null,
            preco: i.p ?? null,          // preço que a vitrine apresenta
            tabela: i.t ?? null,         // preço "de" riscado, quando publicado
            disponivel: i.d ?? null,
            // Janela de 7 dias (dia -> preço) e mínima histórica, gravadas pela
            // raspagem dentro do próprio item. Vêm de graça: o documento já é
            // lido para listar. Ver coletor/repositorio.py::historico_do_item.
            historico: i.h || {},
            minHistorico: i.min ?? null,
            diaDoMinimo: i.minD || null,
            diasDeHistorico: Object.keys(i.h || {}).length,
          });
        }
      }
    }
    catalogo.value = itens;
    categorias.value = listaCategorias;
  } catch (erro) {
    console.error("falha ao carregar o catálogo", erro);
  } finally {
    carregado.value = true;
  }
}

/** Imagem do catálogo para um produto acompanhado, casada pela URL da fonte.
 *  Produto criado à mão não tem imagem — as rules não guardam esse campo — mas
 *  quando alguma fonte aponta para um item da vitrine, a imagem vem de graça. */
export function imagemPorUrl(urls) {
  for (const url of urls) {
    const item = catalogo.value.find((i) => i.url === url && i.imagem);
    if (item) return item.imagem;
  }
  return null;
}

export function useCatalogo() {
  return { catalogo, categorias, carregado, carregarCatalogo, imagemPorUrl };
}
