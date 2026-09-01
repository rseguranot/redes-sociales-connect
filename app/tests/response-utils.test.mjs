import test from "node:test";
import assert from "node:assert/strict";
import { flowAnswerValue, flowQuestionLabel, flowResponseMatrix } from "../src/responseUtils.js";

test("turns Flow technical fields into readable questions", () => {
  assert.equal(flowQuestionLabel("screen_0_tipo_repuesto"), "Tipo de repuesto");
  assert.equal(flowQuestionLabel("screen_2_preferencia_contacto"), "Preferencia de contacto");
});

test("turns Flow option arrays into readable answers", () => {
  assert.equal(flowAnswerValue('["0_Motor","3_Eléctrico"]'), "Motor, Eléctrico");
  assert.equal(flowAnswerValue("0_Precio"), "Precio");
});

test("builds a dynamic question matrix across responses", () => {
  const result = flowResponseMatrix([
    { id: "1", answers: [{ field: "screen_0_tipo", value: "0_Motor" }] },
    { id: "2", answers: [{ field: "screen_1_prioridad", value: "1_Precio" }] },
  ]);
  assert.deepEqual(result.questions.map((item) => item.label), ["Tipo", "Prioridad"]);
  assert.equal(result.records[0].answers.screen_0_tipo, "Motor");
});
