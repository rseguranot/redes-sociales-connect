const COMPONENT_TYPES = {
  text: "TextInput",
  radio: "RadioButtonsGroup",
  checkbox: "CheckboxGroup",
  dropdown: "Dropdown",
};

export function safeFlowKey(value, fallback = "campo") {
  const normalized = String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  return normalized || fallback;
}

export function normalizeFlowQuestions(questions = []) {
  const used = new Set();
  return questions.map((question, index) => {
    const base = safeFlowKey(question.key || question.label, `pregunta_${index + 1}`);
    let key = base;
    let suffix = 2;
    while (used.has(key)) key = `${base}_${suffix++}`;
    used.add(key);
    const type = COMPONENT_TYPES[question.type] ? question.type : "text";
    const options = (question.options || []).map((item) => String(item).trim()).filter(Boolean);
    return { ...question, key, type, label: String(question.label || "").trim(), options };
  });
}

export function validateFlowDraft({ name, questions }) {
  const errors = [];
  if (!String(name || "").trim()) errors.push("Escribe el nombre del Flow.");
  const normalized = normalizeFlowQuestions(questions);
  if (!normalized.length) errors.push("Agrega al menos una pregunta.");
  normalized.forEach((question, index) => {
    if (!question.label) errors.push(`La pregunta ${index + 1} necesita un texto.`);
    if (question.type !== "text" && question.options.length < 2) {
      errors.push(`La pregunta ${index + 1} necesita al menos dos opciones.`);
    }
  });
  return errors;
}

export function buildFlowJson({ name, questions, buttonLabel = "Enviar" }) {
  const normalized = normalizeFlowQuestions(questions);
  const children = normalized.map((question) => {
    const component = {
      type: COMPONENT_TYPES[question.type],
      name: question.key,
      label: question.label,
      required: question.required !== false,
    };
    if (question.type === "text") component["input-type"] = "text";
    else component["data-source"] = question.options.map((title, index) => ({ id: `${index}_${safeFlowKey(title, "opcion")}`, title }));
    return component;
  });
  children.push({
    type: "Footer",
    label: String(buttonLabel || "Enviar").trim().slice(0, 30) || "Enviar",
    "on-click-action": {
      name: "complete",
      payload: Object.fromEntries(normalized.map((question) => [question.key, `\${form.${question.key}}`])),
    },
  });
  return {
    version: "7.1",
    screens: [{
      id: "FORMULARIO",
      title: String(name || "Formulario").trim().slice(0, 80) || "Formulario",
      terminal: true,
      success: true,
      data: {},
      layout: { type: "SingleColumnLayout", children: [{ type: "Form", name: "formulario", children }] },
    }],
  };
}

export function templateVariables(text) {
  return [...new Set([...String(text || "").matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)].map((match) => match[1]))];
}
