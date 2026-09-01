import { getRuntimeConfig } from "./runtimeConfig.js";

const LOCALE = getRuntimeConfig().locale || "es";
const SCREEN_PREFIX = /^(?:screen|page)[_-]?\d+[_-]+/i;
const OPTION_PREFIX = /^\d+[_-]+/;
const ACCENTS = { telefono: "teléfono", numero: "número", cedula: "cédula", electrico: "eléctrico", seleccion: "selección" };
const NEEDS_DE = new Set(["tipo", "prioridad", "preferencia", "motivo", "medio", "canal", "fecha", "numero"]);

function cleanWords(value) {
  return String(value ?? "")
    .replace(OPTION_PREFIX, "")
    .replace(/([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function flowQuestionLabel(field) {
  const raw = cleanWords(String(field || "").replace(SCREEN_PREFIX, ""));
  const words = raw.split(" ").filter(Boolean).map((word) => ACCENTS[word.toLocaleLowerCase(LOCALE)] || word);
  if (words.length > 1 && NEEDS_DE.has(words[0].toLocaleLowerCase(LOCALE)) && words[1].toLocaleLowerCase(LOCALE) !== "de") words.splice(1, 0, "de");
  const cleaned = words.join(" ");
  return cleaned ? cleaned.charAt(0).toLocaleUpperCase(LOCALE) + cleaned.slice(1) : "Respuesta";
}

export function flowAnswerValue(value) {
  let parsed = value;
  if (typeof parsed === "string") {
    const trimmed = parsed.trim();
    if ((trimmed.startsWith("[") && trimmed.endsWith("]")) || (trimmed.startsWith("{") && trimmed.endsWith("}"))) {
      try { parsed = JSON.parse(trimmed); } catch { parsed = trimmed; }
    }
  }
  if (Array.isArray(parsed)) return parsed.map(flowAnswerValue).filter(Boolean).join(", ");
  if (parsed && typeof parsed === "object") return Object.values(parsed).map(flowAnswerValue).filter(Boolean).join(" · ");
  if (parsed === true) return "Sí";
  if (parsed === false) return "No";
  return cleanWords(parsed);
}

export function normalizedFlowAnswers(row) {
  return (row?.answers || []).map((answer) => ({
    field: String(answer?.field || "respuesta"),
    question: flowQuestionLabel(answer?.field),
    value: flowAnswerValue(answer?.value),
  }));
}

export function flowQuestions(rows) {
  const questions = new Map();
  rows.forEach((row) => normalizedFlowAnswers(row).forEach((answer) => {
    if (!questions.has(answer.field)) questions.set(answer.field, answer.question);
  }));
  return [...questions].map(([field, label]) => ({ field, label }));
}

export function flowResponseMatrix(rows) {
  const questions = flowQuestions(rows);
  const records = rows.map((row) => {
    const answers = Object.fromEntries(normalizedFlowAnswers(row).map((answer) => [answer.field, answer.value]));
    return { row, answers };
  });
  return { questions, records };
}
