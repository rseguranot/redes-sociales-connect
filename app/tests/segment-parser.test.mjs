import test from "node:test";
import assert from "node:assert/strict";
import { contactsFromRows, guessRole, parseDelimitedText } from "../src/segmentParser.js";

test("detects pipe delimiter and maps common customer columns", () => {
  const result = parseDelimitedText("nombre|celular|telefono casa|cedula|correo\nPersona Ejemplo|+1 202 555 0101|202-555-0102|DOC-001|persona@example.test");
  assert.equal(result.delimiter, "|");
  assert.deepEqual(result.roles, ["name", "phone", "phone", "document_id", "email"]);
  const contacts = contactsFromRows(result.rows, result.roles);
  assert.equal(contacts.length, 1);
  assert.deepEqual(contacts[0].phones, ["+12025550101", "2025550102"]);
});

test("detects semicolon delimiter and multiple phones in one column", () => {
  const result = parseDelimitedText("Cliente;Teléfono;DNI\nPersona Ejemplo;2025550103,2025550104;DOC-002");
  assert.equal(result.delimiter, ";");
  assert.deepEqual(contactsFromRows(result.rows, result.roles)[0].phones, ["2025550103", "2025550104"]);
});

test("recognizes accents and residential phone aliases", () => {
  assert.equal(guessRole("Cédula"), "document_id");
  assert.equal(guessRole("Móvil"), "phone");
  assert.equal(guessRole("Residencial"), "phone");
});
