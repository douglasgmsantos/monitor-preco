/** "Verificado há 12 minutos" — tempo relativo honesto, em pt-BR.
 *
 *  O dado NUNCA é ao vivo (o coletor roda em janelas de horas), então mostrar
 *  quando foi a última leitura é informação, não decoração.
 */
export function haQuantoTempo(instante) {
  if (!instante) return null;
  const quando = instante.toDate ? instante.toDate() : new Date(instante);
  if (isNaN(quando)) return null;

  const segundos = Math.max(0, Math.floor((Date.now() - quando.getTime()) / 1000));
  if (segundos < 60) return "agora mesmo";
  const minutos = Math.floor(segundos / 60);
  if (minutos < 60) return `há ${minutos} minuto${minutos > 1 ? "s" : ""}`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `há ${horas} hora${horas > 1 ? "s" : ""}`;
  const dias = Math.floor(horas / 24);
  return `há ${dias} dia${dias > 1 ? "s" : ""}`;
}

export const chaveMes = (d) =>
  `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
export const chaveAno = (d) => String(d.getUTCFullYear());
export const chaveDia = (d) =>
  "d" + d.getUTCFullYear() +
  String(d.getUTCMonth() + 1).padStart(2, "0") +
  String(d.getUTCDate()).padStart(2, "0");
