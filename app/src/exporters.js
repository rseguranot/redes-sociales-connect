import { getBrand, getRuntimeConfig } from "./runtimeConfig.js";

const NAVY = "0B2038";
const GREEN = "079455";
const LIGHT = "EAF5F0";

export function safeExportName(value, fallback = "reporte") {
  const cleaned = String(value || fallback).normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 90);
  return cleaned || fallback;
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { blob, filename };
}

function excelValue(value) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date || typeof value === "number" || typeof value === "boolean") return value;
  return String(value);
}

export async function exportExcelReport({ filename, title, subtitle = "", metrics = [], sheets = [] }) {
  const { default: ExcelJS } = await import("exceljs");
  const brand = getBrand();
  const reportSubtitle = subtitle || brand.name;
  const workbook = new ExcelJS.Workbook();
  workbook.creator = brand.name;
  workbook.company = brand.name;
  workbook.created = new Date();
  const summary = workbook.addWorksheet("Resumen", { views: [{ showGridLines: false }] });
  summary.mergeCells("A1:D1"); summary.getCell("A1").value = title;
  summary.getCell("A1").font = { bold: true, size: 20, color: { argb: "FFFFFFFF" } };
  summary.getCell("A1").fill = { type: "pattern", pattern: "solid", fgColor: { argb: `FF${NAVY}` } };
  summary.getCell("A1").alignment = { vertical: "middle" }; summary.getRow(1).height = 34;
  summary.mergeCells("A2:D2"); summary.getCell("A2").value = reportSubtitle;
  summary.getCell("A2").font = { color: { argb: "FF657180" }, italic: true };
  summary.getCell("A4").value = "Generado"; summary.getCell("B4").value = new Date(); summary.getCell("B4").numFmt = "yyyy-mm-dd hh:mm";
  metrics.forEach((metric, index) => {
    const row = 6 + index;
    summary.getCell(row, 1).value = metric.label;
    summary.getCell(row, 2).value = excelValue(metric.value);
    summary.getCell(row, 1).font = { bold: true, color: { argb: `FF${NAVY}` } };
    summary.getCell(row, 2).font = { bold: true, size: 14, color: { argb: `FF${GREEN}` } };
    summary.getCell(row, 1).fill = summary.getCell(row, 2).fill = { type: "pattern", pattern: "solid", fgColor: { argb: `FF${LIGHT}` } };
  });
  summary.columns = [{ width: 30 }, { width: 24 }, { width: 20 }, { width: 20 }];

  sheets.forEach((definition) => {
    const sheet = workbook.addWorksheet(String(definition.name || "Datos").slice(0, 31), { views: [{ state: "frozen", ySplit: 1, showGridLines: false }] });
    const columns = definition.columns || [];
    sheet.columns = columns.map((column) => ({ header: column.header, key: column.key, width: Math.min(Math.max(column.width || 18, 10), 45) }));
    (definition.rows || []).forEach((row) => sheet.addRow(Object.fromEntries(columns.map((column) => [column.key, excelValue(row[column.key])]))));
    const header = sheet.getRow(1);
    header.height = 28; header.font = { bold: true, color: { argb: "FFFFFFFF" } };
    header.fill = { type: "pattern", pattern: "solid", fgColor: { argb: `FF${NAVY}` } };
    header.alignment = { vertical: "middle", wrapText: true };
    sheet.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: Math.max(columns.length, 1) } };
    sheet.eachRow((row, rowNumber) => {
      if (rowNumber > 1) {
        row.alignment = { vertical: "top", wrapText: true };
        if (rowNumber % 2 === 0) row.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFF7F9FB" } };
      }
    });
    columns.forEach((column, index) => {
      if (column.type === "date") sheet.getColumn(index + 1).numFmt = "yyyy-mm-dd hh:mm";
      if (column.type === "text") sheet.getColumn(index + 1).numFmt = "@";
    });
  });
  const buffer = await workbook.xlsx.writeBuffer();
  return download(new Blob([buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), `${safeExportName(filename || `${brand.name}-reporte`)}.xlsx`);
}

export async function exportPdfReport({ filename, title, subtitle = "", metrics = [], sections = [] }) {
  const [{ jsPDF }, { autoTable }] = await Promise.all([import("jspdf"), import("jspdf-autotable")]);
  const brand = getBrand();
  const locale = getRuntimeConfig().locale || "es";
  const widest = Math.max(0, ...sections.map((section) => section.columns?.length || 0));
  const doc = new jsPDF({ orientation: widest > 5 ? "landscape" : "portrait", unit: "pt", format: "a4" });
  const pageWidth = doc.internal.pageSize.getWidth();
  doc.setFillColor(11, 32, 56); doc.rect(0, 0, pageWidth, 68, "F");
  doc.setTextColor(255, 255, 255); doc.setFont("helvetica", "bold"); doc.setFontSize(18); doc.text(title, 40, 32);
  doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.text(subtitle || brand.name, 40, 50);
  let y = 92;
  if (metrics.length) {
    const cardWidth = Math.min(150, (pageWidth - 80 - (metrics.length - 1) * 10) / metrics.length);
    metrics.forEach((metric, index) => {
      const x = 40 + index * (cardWidth + 10);
      doc.setFillColor(234, 245, 240); doc.roundedRect(x, y, cardWidth, 48, 4, 4, "F");
      doc.setTextColor(89, 103, 116); doc.setFontSize(8); doc.text(String(metric.label), x + 9, y + 15);
      doc.setTextColor(7, 148, 85); doc.setFont("helvetica", "bold"); doc.setFontSize(15); doc.text(String(metric.value ?? ""), x + 9, y + 36);
      doc.setFont("helvetica", "normal");
    });
    y += 68;
  }
  sections.forEach((section, index) => {
    if (index > 0 && y > doc.internal.pageSize.getHeight() - 140) { doc.addPage(); y = 45; }
    doc.setTextColor(11, 32, 56); doc.setFont("helvetica", "bold"); doc.setFontSize(12); doc.text(section.title || "Detalle", 40, y);
    autoTable(doc, {
      startY: y + 10,
      head: [(section.columns || []).map((column) => column.header)],
      body: (section.rows || []).map((row) => (section.columns || []).map((column) => row[column.key] instanceof Date
        ? row[column.key].toLocaleString(locale) : String(row[column.key] ?? ""))),
      theme: "striped",
      margin: { left: 40, right: 40 },
      styles: { font: "helvetica", fontSize: 7.5, cellPadding: 5, overflow: "linebreak", textColor: [35, 51, 65] },
      headStyles: { fillColor: [11, 32, 56], textColor: [255, 255, 255], fontStyle: "bold" },
      alternateRowStyles: { fillColor: [247, 249, 251] },
      didDrawPage: () => {
        const height = doc.internal.pageSize.getHeight();
        doc.setFont("helvetica", "normal"); doc.setFontSize(7); doc.setTextColor(110, 120, 130);
        doc.text(`${brand.name} · ${new Date().toLocaleString(locale)}`, 40, height - 20);
        doc.text(`Página ${doc.getNumberOfPages()}`, pageWidth - 75, height - 20);
      },
    });
    y = doc.lastAutoTable.finalY + 28;
  });
  return download(doc.output("blob"), `${safeExportName(filename || `${brand.name}-reporte`)}.pdf`);
}
