import Papa from "papaparse";

export const normalizeHeader = (value) => String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();

export const guessRole = (header) => {
  const value = normalizeHeader(header);
  if (/correo|email|e-mail/.test(value)) return "email";
  if (/dni|cedula|documento|identificacion|identidad|rnc/.test(value)) return "document_id";
  if (/telefono|tel\b|phone|movil|celular|casa|residencial|whatsapp/.test(value)) return "phone";
  if (/nombre|name|cliente|contacto/.test(value)) return "name";
  return "ignore";
};

export const cleanPhone = (value) => {
  const phone = String(value || "").replace(/[^\d+]/g, "");
  const digits = phone.replace(/\D/g, "");
  return digits.length >= 8 && digits.length <= 15 ? phone : "";
};

export const splitPhones = (value) => String(value || "").split(/[,;|\n]+/).map(cleanPhone).filter(Boolean);

export function contactsFromRows(rows, roles) {
  return rows.map((row, rowIndex) => {
    const contact = { id: `contact-${rowIndex + 1}`, name: "", phones: [], document_id: "", email: "" };
    row.forEach((cell, index) => {
      const role = roles[index];
      if (role === "phone") contact.phones.push(...splitPhones(cell));
      else if (role !== "ignore" && role) contact[role] = String(cell ?? "").trim();
    });
    contact.phones = [...new Set(contact.phones)];
    return contact;
  }).filter((contact) => contact.phones.length);
}

export function parseDelimitedText(text) {
  const parsed = Papa.parse(text, { skipEmptyLines: "greedy" });
  if (parsed.errors?.some((item) => item.type === "Quotes")) throw new Error("El archivo contiene comillas sin cerrar.");
  const matrix = parsed.data;
  const headers = (matrix[0] || []).map((value, index) => String(value || `Columna ${index + 1}`).trim());
  return { headers, rows: matrix.slice(1), roles: headers.map(guessRole), delimiter: parsed.meta.delimiter };
}
