import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { exportExcelReport, exportPdfReport } from "../src/exporters.js";

test("generates non-empty XLSX and PDF report downloads", async () => {
  const downloads = [];
  const originalDocument = globalThis.document;
  const originalWindow = globalThis.window;
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  globalThis.document = {
    body: { appendChild() {} },
    createElement: () => ({ click() {}, remove() {}, href: "", download: "" }),
  };
  globalThis.window = {
    setTimeout: (callback) => callback(),
    atob: globalThis.atob,
    btoa: globalThis.btoa,
    Blob: globalThis.Blob,
    __SOCIAL_HUB_CONFIG__: {
      businessName: "Empresa Ejemplo",
      locale: "es-MX",
    },
  };
  URL.createObjectURL = (blob) => { downloads.push(blob); return "blob:test"; };
  URL.revokeObjectURL = () => {};
  const definition = {
    title: "Reporte de prueba",
    metrics: [{ label: "Respuestas", value: 1 }],
  };
  const section = {
    name: "Respuestas", title: "Preguntas y respuestas",
    columns: [{ key: "customer", header: "Cliente", width: 24 }, { key: "answer", header: "Respuesta", width: 30 }],
    rows: [{ customer: "Ana", answer: "Motor, Eléctrico" }],
  };
  try {
    const excel = await exportExcelReport({ ...definition, sheets: [section] });
    const pdf = await exportPdfReport({ ...definition, sections: [section] });
    const { default: ExcelJS } = await import("exceljs");
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(await excel.blob.arrayBuffer());
    assert.equal(workbook.creator, "Empresa Ejemplo");
    assert.equal(workbook.company, "Empresa Ejemplo");
    assert.equal(excel.filename, "Empresa-Ejemplo-reporte.xlsx");
    assert.equal(pdf.filename, "Empresa-Ejemplo-reporte.pdf");
    if (process.env.WRITE_QA_EXPORTS) {
      await fs.mkdir(process.env.WRITE_QA_EXPORTS, { recursive: true });
      await fs.writeFile(`${process.env.WRITE_QA_EXPORTS}/${excel.filename}`, new Uint8Array(await excel.blob.arrayBuffer()));
      await fs.writeFile(`${process.env.WRITE_QA_EXPORTS}/${pdf.filename}`, new Uint8Array(await pdf.blob.arrayBuffer()));
    }
  } finally {
    globalThis.document = originalDocument; globalThis.window = originalWindow;
    URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke;
  }
  assert.equal(downloads.length, 2);
  assert.equal(downloads[0].type, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  assert.ok(downloads[0].size > 5000);
  assert.equal(downloads[1].type, "application/pdf");
  assert.ok(downloads[1].size > 1000);
});
