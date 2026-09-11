export function historyText(value = "") {
  let text = String(value);
  try {
    const parsed = JSON.parse(text)?.whatsapp_outbound;
    if (parsed?.interactive) {
      const item = parsed.interactive;
      const options = (item.action?.sections || []).flatMap(section => section.rows || [])
        .map(row => row.title);
      text = [item.header?.text, item.body?.text, ...options.map(option => `• ${option}`)].filter(Boolean).join("\n");
    }
  } catch { /* Plain text is the normal case. Render as text, never HTML. */ }
  return text.replace(/^\s*\[plantilla\]\s*\n/i, "")
    .replace(/^\s*\[opcion\]\s*/gim, "• ")
    .replace(/^\s*\[(?:informacion|pregunta)\]\s*/gim, "");
}

export const collectedLabels = {
  social_collected_name: "Nombre declarado", social_collected_phone: "Teléfono declarado",
  social_service: "Servicio", social_document_type: "Tipo de documento", social_document_number: "Documento",
  social_case_number: "Caso", social_invoice_number: "Factura", social_request_detail: "Detalle",
  social_incident_location: "Lugar", social_incident_date: "Fecha del incidente",
  social_incident_area: "Área", social_request_priority: "Prioridad",
};
