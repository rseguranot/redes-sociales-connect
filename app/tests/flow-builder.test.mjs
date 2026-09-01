import test from "node:test";
import assert from "node:assert/strict";
import { buildFlowJson, normalizeFlowQuestions, templateVariables, validateFlowDraft } from "../src/flowBuilder.js";

test("builds a terminal WhatsApp Flow screen with readable fields", () => {
  const result = buildFlowJson({
    name: "Encuesta servicio",
    questions: [
      { label: "¿Cómo califica el servicio?", type: "radio", required: true, options: ["Excelente", "Regular"] },
      { label: "Comentario adicional", type: "text", required: false, options: [] },
    ],
  });
  assert.equal(result.version, "7.1");
  assert.equal(result.screens[0].id, "FORMULARIO");
  assert.equal(result.screens[0].terminal, true);
  const children = result.screens[0].layout.children[0].children;
  assert.equal(children[0].type, "RadioButtonsGroup");
  assert.deepEqual(children[0]["data-source"].map((option) => option.title), ["Excelente", "Regular"]);
  assert.equal(children.at(-1)["on-click-action"].payload.como_califica_el_servicio, "${form.como_califica_el_servicio}");
});

test("normalizes duplicate question keys and validates choice options", () => {
  const questions = normalizeFlowQuestions([
    { label: "Prioridad", type: "text" }, { label: "Prioridad", type: "text" },
  ]);
  assert.deepEqual(questions.map((item) => item.key), ["prioridad", "prioridad_2"]);
  assert.match(validateFlowDraft({ name: "Prueba", questions: [{ label: "Nivel", type: "radio", options: ["Uno"] }] })[0], /dos opciones/);
});

test("extracts unique named template variables", () => {
  assert.deepEqual(templateVariables("Hola {{nombre}}, te atiende {{agente}}. {{nombre}}"), ["nombre", "agente"]);
});
