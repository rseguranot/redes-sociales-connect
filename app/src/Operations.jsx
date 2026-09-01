import { useEffect, useMemo, useState } from "react";
import readXlsxFile from "read-excel-file/browser";
import {
  ArrowLeft,
  ArrowRight,
  ChartBar,
  Check,
  CheckCircle,
  CircleNotch,
  FilePdf,
  FileCsv,
  FileXls,
  FlowArrow,
  Info,
  Megaphone,
  NotePencil,
  Plus,
  ArrowCounterClockwise,
  Trash,
  UploadSimple,
  UsersThree,
  WhatsappLogo,
} from "@phosphor-icons/react";
import {
  createCampaign,
  deleteCampaign,
  getSegmentContacts,
  listCampaignTrash,
  listMetaFlows,
  listMetaTemplates,
  listResource,
  listSegments,
  saveSegment,
  restoreCampaign,
} from "./api";
import { exportExcelReport, exportPdfReport } from "./exporters";
import { getBrand, getRuntimeConfig } from "./runtimeConfig";
import { contactsFromRows, guessRole, parseDelimitedText, splitPhones } from "./segmentParser";

const BRAND = getBrand();
const RUNTIME = getRuntimeConfig();
const LOCALE = RUNTIME.locale || "es";

const CAMPAIGN_TYPES = [
  {
    id: "informative",
    title: "Informativa",
    description: "Envía una plantilla aprobada y finaliza el envío.",
    icon: Megaphone,
  },
  {
    id: "survey",
    title: "Encuesta con Flow",
    description: "Inicia un WhatsApp Flow y organiza las respuestas por campaña.",
    icon: FlowArrow,
  },
  {
    id: "conversation",
    title: "Conversacional",
    description: "Inicia el chat en el canal configurado y lleva las respuestas a Amazon Connect.",
    icon: WhatsappLogo,
  },
];

const ROLE_OPTIONS = [
  ["ignore", "No importar"],
  ["name", "Nombre"],
  ["phone", "Teléfono"],
  ["document_id", "DNI / cédula"],
  ["email", "Correo"],
];
const MAX_SEGMENT_CONTACTS = 1000;
const FIELD_LABELS = {
  name: "Nombre",
  phone: "Teléfono utilizado en el envío",
  document_id: "DNI / cédula",
  email: "Correo",
};

const formatDate = (value) => value ? new Date(Number(value) * 1000).toLocaleString(LOCALE) : "—";

function SectionHeader({ eyebrow, title, description, action, actionLabel, actionIcon: ActionIcon = Plus, actions }) {
  return <div className="op-header">
    <div><span>{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
    {actions || (action && <button className="primary small" onClick={action}><ActionIcon />{actionLabel}</button>)}
  </div>;
}

function Loading({ children = "Actualizando datos…" }) {
  return <div className="op-loading"><CircleNotch className="spin" />{children}</div>;
}

function Empty({ icon: Icon = Info, title, description, action, actionLabel }) {
  return <div className="op-empty"><Icon weight="duotone" /><h3>{title}</h3><p>{description}</p>{action && <button className="primary small" onClick={action}><Plus />{actionLabel}</button>}</div>;
}

function Metric({ icon: Icon, label, value, note, tone = "green" }) {
  return <article className={`op-metric ${tone}`}><span><Icon weight="duotone" /></span><div><small>{label}</small><b>{value}</b><p>{note}</p></div></article>;
}

export function Dashboard({ refreshVersion, setActive, session }) {
  const [data, setData] = useState({ segments: [], campaigns: [], templates: [], flows: [] });
  const [status, setStatus] = useState("loading");
  const [exportState, setExportState] = useState("idle");
  const [exportError, setExportError] = useState("");
  useEffect(() => {
    let active = true;
    setStatus("loading");
    const allowed = session?.module_permissions || {};
    Promise.all([
      allowed.segments?.view === false ? Promise.resolve({ items: [] }) : listSegments(),
      allowed.campaigns?.view === false ? Promise.resolve({ items: [] }) : listResource("campaigns"),
      allowed.templates?.view === false ? Promise.resolve({ items: [] }) : listMetaTemplates(),
      allowed.surveys?.view === false ? Promise.resolve({ items: [] }) : listMetaFlows(),
    ])
      .then(([segments, campaigns, templates, flows]) => {
        if (!active) return;
        setData({
          segments: segments?.items || [], campaigns: campaigns?.items || [],
          templates: templates?.items || [], flows: flows?.items || [],
        });
        setStatus("ready");
      })
      .catch(() => active && setStatus("error"));
    return () => { active = false; };
  }, [refreshVersion, session]);
  const contacts = data.segments.reduce((sum, item) => sum + Number(item.contact_count || 0), 0);
  const recipients = data.campaigns.reduce((sum, item) => sum + Number(item.recipient_count || 0), 0);
  const delivered = data.campaigns.reduce((sum, item) => sum + Number(item.delivered_count || 0), 0);
  const responses = data.campaigns.reduce((sum, item) => sum + Number(item.response_count || 0), 0);
  const dashboardMetrics = [
    { label: "Contactos en segmentos", value: contacts }, { label: "Segmentos", value: data.segments.length },
    { label: "Campañas", value: data.campaigns.length }, { label: "Destinatarios", value: recipients },
    { label: "Entregados", value: delivered }, { label: "Respuestas de Flow", value: responses },
  ];
  const segmentColumns = [
    { key: "name", header: "Segmento", width: 28 }, { key: "contact_count", header: "Contactos", width: 14 },
    { key: "phone_count", header: "Teléfonos", width: 14 }, { key: "source", header: "Origen", width: 14 },
    { key: "updated", header: "Actualización", width: 22, type: "date" },
  ];
  const segmentRows = data.segments.map((item) => ({ ...item, updated: item.updated_at ? new Date(Number(item.updated_at) * 1000) : "" }));
  const campaignColumns = [
    { key: "name", header: "Campaña", width: 30 }, { key: "campaign_type", header: "Tipo", width: 18 },
    { key: "segment_name", header: "Segmento", width: 26 }, { key: "template_name", header: "Plantilla", width: 30 },
    { key: "recipient_count", header: "Destinatarios", width: 14 }, { key: "delivered_count", header: "Entregados", width: 14 },
    { key: "read_count", header: "Leídos", width: 12 }, { key: "response_count", header: "Respuestas", width: 12 },
    { key: "created", header: "Creación", width: 22, type: "date" },
  ];
  const campaignRows = data.campaigns.map((item) => ({ ...item, created: item.created_at ? new Date(Number(item.created_at) * 1000) : "" }));
  async function exportDashboard(format) {
    setExportState(format); setExportError("");
    const report = { filename: `${BRAND.name}-dashboard-${new Date().toISOString().slice(0, 10)}`, title: `${BRAND.name} · Dashboard`, subtitle: "Segmentos, campañas y resultados de canales sociales", metrics: dashboardMetrics };
    try {
      if (format === "excel") await exportExcelReport({ ...report, sheets: [{ name: "Segmentos", columns: segmentColumns, rows: segmentRows }, { name: "Campañas", columns: campaignColumns, rows: campaignRows }] });
      else await exportPdfReport({ ...report, sections: [{ title: "Campañas", columns: campaignColumns, rows: campaignRows }, { title: "Segmentos", columns: segmentColumns, rows: segmentRows }] });
    } catch { setExportError("No fue posible generar el reporte. Inténtalo nuevamente."); }
    finally { setExportState("idle"); }
  }
  return <main className="module-page op-page">
    <SectionHeader eyebrow="OPERACIÓN" title="Dashboard" description="Estado real de segmentos, campañas y respuestas de los canales sociales configurados." actions={<div className="op-export-actions"><button disabled={exportState !== "idle"} onClick={() => exportDashboard("excel")}><FileXls />Excel</button><button disabled={exportState !== "idle"} onClick={() => exportDashboard("pdf")}><FilePdf />PDF</button></div>} />
    {status === "loading" && <Loading>Consolidando la operación…</Loading>}
    {status === "error" && <div className="op-error">No fue posible consolidar el dashboard después de varios intentos. Usa Actualizar datos en la barra superior.</div>}
    {exportError && <div className="op-error">{exportError}</div>}
    {status === "ready" && <>
      <div className="op-dashboard-metrics">
        <Metric icon={UsersThree} label="Contactos en segmentos" value={contacts} note={`${data.segments.length} segmento${data.segments.length === 1 ? "" : "s"} guardado${data.segments.length === 1 ? "" : "s"}`} />
        <Metric icon={Megaphone} label="Campañas" value={data.campaigns.length} note={`${recipients} destinatario${recipients === 1 ? "" : "s"} procesado${recipients === 1 ? "" : "s"}`} tone="blue" />
        <Metric icon={CheckCircle} label="Entrega confirmada" value={recipients ? `${Math.round((delivered / recipients) * 100)}%` : "—"} note={`${delivered} entrega${delivered === 1 ? "" : "s"} confirmada${delivered === 1 ? "" : "s"}`} tone="navy" />
        <Metric icon={ChartBar} label="Respuestas de Flow" value={responses} note={recipients ? `${Math.round((responses / recipients) * 100)}% sobre destinatarios` : "Sin campañas enviadas"} tone="amber" />
      </div>
      <div className="op-dashboard-grid">
        <section className="op-panel"><header><div><h2>Actividad reciente</h2><p>Últimas campañas registradas</p></div><button onClick={() => setActive("campaigns")}>Ver campañas <ArrowRight /></button></header>
          {data.campaigns.length ? <div className="op-activity">{data.campaigns.slice(0, 5).map((campaign) => <article key={campaign.id}><span className="op-activity-icon"><Megaphone /></span><div><b>{campaign.name}</b><small>{campaign.segment_name || "Sin segmento asociado"} · {formatDate(campaign.created_at)}</small></div><strong>{campaign.recipient_count || 0}</strong></article>)}</div>
            : <Empty icon={Megaphone} title="Aún no hay campañas" description="Crea un segmento y úsalo para preparar el primer envío." action={() => setActive("segments")} actionLabel="Crear segmento" />}
        </section>
        <section className="op-panel"><header><div><h2>Recursos disponibles</h2><p>Contenido sincronizado con Meta</p></div></header>
          <div className="op-resource-list"><button onClick={() => setActive("templates")}><NotePencil /><span><b>{data.templates.length} plantillas</b><small>Aprobadas para iniciar envíos</small></span><ArrowRight /></button><button onClick={() => setActive("surveys")}><FlowArrow /><span><b>{data.flows.length} Flows</b><small>Publicados y borradores en Meta</small></span><ArrowRight /></button><button onClick={() => setActive("responses")}><ChartBar /><span><b>{responses} respuestas</b><small>Organizadas por campaña y Flow</small></span><ArrowRight /></button></div>
        </section>
      </div>
    </>}
  </main>;
}

export function Segments({ refreshVersion, onCreateCampaign, permissions = {}, canCreateCampaign = true }) {
  const [segments, setSegments] = useState([]);
  const [status, setStatus] = useState("loading");
  const [mode, setMode] = useState("list");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState("file");
  const [fileName, setFileName] = useState("");
  const [delimiter, setDelimiter] = useState("");
  const [headers, setHeaders] = useState([]);
  const [rows, setRows] = useState([]);
  const [roles, setRoles] = useState([]);
  const [manual, setManual] = useState([{ name: "", phones: "", document_id: "", email: "" }]);
  const [createdSegment, setCreatedSegment] = useState(null);
  const [saveState, setSaveState] = useState("idle");
  const [error, setError] = useState("");
  const [exportingId, setExportingId] = useState("");
  const canCreateManual = permissions.create !== false;
  const canImport = permissions.import !== false;
  const canCreateAny = canCreateManual || canImport;
  const load = () => {
    setStatus("loading");
    return listSegments().then((result) => { setSegments(result?.items || []); setStatus("ready"); }).catch(() => setStatus("error"));
  };
  useEffect(() => { load(); }, [refreshVersion]);
  const importedContacts = useMemo(() => contactsFromRows(rows, roles), [rows, roles]);
  const manualContacts = useMemo(() => manual.map((item, index) => ({
    id: `contact-${index + 1}`, name: item.name.trim(), phones: splitPhones(item.phones),
    document_id: item.document_id.trim(), email: item.email.trim(),
  })).filter((item) => item.phones.length), [manual]);
  const contacts = source === "file" ? importedContacts : manualContacts;
  const startCreate = () => { setSource(canImport ? "file" : "manual"); setMode("create"); };
  const reset = () => { setName(""); setDescription(""); setSource("file"); setFileName(""); setDelimiter(""); setHeaders([]); setRows([]); setRoles([]); setManual([{ name: "", phones: "", document_id: "", email: "" }]); setCreatedSegment(null); setSaveState("idle"); setError(""); };
  async function parseFile(file) {
    if (!file) return;
    setError(""); setFileName(file.name);
    try {
      let matrix;
      if (/\.xlsx$/i.test(file.name)) {
        matrix = await readXlsxFile(file);
        setDelimiter("Hoja de Excel");
      } else {
        const parsed = parseDelimitedText(await file.text());
        matrix = [parsed.headers, ...parsed.rows];
        setDelimiter(parsed.delimiter === "\t" ? "Tabulación" : `Separador ${parsed.delimiter}`);
      }
      const nextHeaders = (matrix[0] || []).map((value, index) => String(value || `Columna ${index + 1}`).trim());
      setHeaders(nextHeaders); setRows(matrix.slice(1)); setRoles(nextHeaders.map(guessRole));
    } catch (requestError) {
      setHeaders([]); setRows([]); setRoles([]); setError(requestError.message || "No fue posible leer el archivo.");
    }
  }
  async function save() {
    if (!name.trim() || !contacts.length || contacts.length > MAX_SEGMENT_CONTACTS) return;
    setSaveState("saving"); setError("");
    try {
      if ((source === "file" && !canImport) || (source === "manual" && !canCreateManual)) return;
      const saved = await saveSegment({ name: name.trim(), description: description.trim(), source, contacts });
      await load(); reset(); setCreatedSegment(saved); setMode("success");
    } catch (requestError) { setError(requestError.message || "No fue posible guardar el segmento."); setSaveState("error"); }
  }
  async function exportContacts(segment, format) {
    setExportingId(`${segment.id}:${format}`); setError("");
    try {
      const result = await getSegmentContacts(segment.id);
      const contacts = result?.contacts || [];
      const columns = [
        { key: "name", header: "Nombre", width: 28 }, { key: "phones_text", header: "Teléfonos", width: 28, type: "text" },
        { key: "document_id", header: "DNI / cédula", width: 20, type: "text" }, { key: "email", header: "Correo", width: 30 },
      ];
      const rows = contacts.map((contact) => ({ ...contact, phones_text: (contact.phones || []).join(", ") }));
      const report = { filename: `${BRAND.name}-contactos-${segment.name}`, title: `Contactos · ${segment.name}`, subtitle: segment.description || `Segmento de clientes de ${BRAND.name}`, metrics: [{ label: "Contactos", value: contacts.length }, { label: "Teléfonos", value: new Set(contacts.flatMap((item) => item.phones || [])).size }] };
      if (format === "excel") await exportExcelReport({ ...report, sheets: [{ name: "Contactos", columns, rows }] });
      else await exportPdfReport({ ...report, sections: [{ title: "Contactos del segmento", columns, rows }] });
    } catch (requestError) { setError(requestError.message || "No fue posible descargar los contactos."); }
    finally { setExportingId(""); }
  }
  if (mode === "success" && createdSegment) return <main className="module-page op-page"><section className="op-success">
    <CheckCircle weight="fill" /><span>SEGMENTO CREADO</span><h1>{createdSegment.name}</h1>
    <p>La audiencia quedó guardada y seleccionada para preparar una nueva campaña.</p>
    <dl><div><dt>Contactos</dt><dd>{createdSegment.contact_count || 0}</dd></div><div><dt>Teléfonos</dt><dd>{createdSegment.phone_count || 0}</dd></div><div><dt>Siguiente paso</dt><dd>Elegir el tipo de campaña</dd></div></dl>
    <div><button className="secondary" onClick={() => { reset(); setMode("list"); }}>Volver a segmentos</button>{canCreateCampaign && <button className="primary" onClick={() => onCreateCampaign(createdSegment.id)}>Iniciar campaña <ArrowRight /></button>}</div>
  </section></main>;
  if (mode === "create") return <main className="module-page op-page">
    <button className="op-back" onClick={() => { reset(); setMode("list"); }}><ArrowLeft />Volver a segmentos</button>
    <SectionHeader eyebrow="SEGMENTACIÓN" title="Crear segmento de clientes" description="Importa una lista o registra contactos manualmente. Revisa la detección antes de guardar." />
    <div className="op-form-layout"><section className="op-form-panel">
      <label>Nombre del segmento<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Ej.: Clientes activos agosto" /></label>
      <label>Descripción <small>Opcional</small><textarea rows="2" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe a quiénes agrupa este segmento" /></label>
      <div className="op-source-tabs">{canImport && <button className={source === "file" ? "active" : ""} onClick={() => setSource("file")}><UploadSimple />Importar archivo</button>}{canCreateManual && <button className={source === "manual" ? "active" : ""} onClick={() => setSource("manual")}><NotePencil />Escribir contactos</button>}</div>
      {source === "file" ? <>
        <label className="op-upload"><input type="file" accept=".csv,.txt,.xlsx,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => parseFile(event.target.files?.[0])} /><span><FileCsv /><FileXls /><b>{fileName || "Selecciona un CSV o Excel"}</b><small>Detectamos coma, punto y coma, barra vertical, tabulación y columnas de Excel.</small></span></label>
        {headers.length > 0 && <><div className="op-import-summary"><b>{rows.length} filas leídas</b><span>{delimiter}</span><strong>{contacts.length} contactos con teléfono válido</strong></div><div className="op-mapping"><header><div><h3>Asignación de columnas</h3><p>Confirma qué representa cada columna detectada.</p></div></header><div>{headers.map((header, index) => <label key={`${header}-${index}`}><span>{header}<small>{String(rows[0]?.[index] ?? "Sin muestra").slice(0, 38)}</small></span><select value={roles[index]} onChange={(event) => setRoles(roles.map((role, roleIndex) => roleIndex === index ? event.target.value : role))}>{ROLE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>)}</div></div></>}
      </> : <div className="op-manual-list">{manual.map((item, index) => <article key={index}><header><b>Contacto {index + 1}</b>{manual.length > 1 && <button onClick={() => setManual(manual.filter((_, itemIndex) => itemIndex !== index))}>Quitar</button>}</header><div><label>Nombre<input value={item.name} onChange={(event) => setManual(manual.map((row, itemIndex) => itemIndex === index ? { ...row, name: event.target.value } : row))} /></label><label>Teléfono(s)<input value={item.phones} onChange={(event) => setManual(manual.map((row, itemIndex) => itemIndex === index ? { ...row, phones: event.target.value } : row))} placeholder="Separados por coma, ; o |" /></label><label>DNI / cédula<input value={item.document_id} onChange={(event) => setManual(manual.map((row, itemIndex) => itemIndex === index ? { ...row, document_id: event.target.value } : row))} /></label><label>Correo<input type="email" value={item.email} onChange={(event) => setManual(manual.map((row, itemIndex) => itemIndex === index ? { ...row, email: event.target.value } : row))} /></label></div></article>)}<button className="op-add-row" onClick={() => setManual([...manual, { name: "", phones: "", document_id: "", email: "" }])}><Plus />Agregar otro contacto</button></div>}
      {contacts.length > MAX_SEGMENT_CONTACTS && <div className="op-error">El archivo contiene {contacts.length} contactos válidos. Divide la lista en segmentos de hasta {MAX_SEGMENT_CONTACTS} contactos.</div>}
      {error && <div className="op-error">{error}</div>}
      <footer className="op-form-actions"><button className="secondary" onClick={() => { reset(); setMode("list"); }}>Cancelar</button><button className="primary" disabled={!name.trim() || !contacts.length || contacts.length > MAX_SEGMENT_CONTACTS || saveState === "saving"} onClick={save}>{saveState === "saving" ? <CircleNotch className="spin" /> : <Check />}{saveState === "saving" ? "Guardando" : `Guardar segmento (${contacts.length})`}</button></footer>
    </section><aside className="op-guidance"><UsersThree weight="duotone" /><h3>Qué guardaremos</h3><dl><div><dt>Contactos válidos</dt><dd>{contacts.length}</dd></div><div><dt>Teléfonos únicos</dt><dd>{new Set(contacts.flatMap((item) => item.phones)).size}</dd></div><div><dt>Columnas reconocidas</dt><dd>{roles.filter((role) => role !== "ignore").length}</dd></div></dl><p>Los teléfonos se conservan por contacto. Una campaña puede usar el principal o todos los números disponibles. Máximo {MAX_SEGMENT_CONTACTS} contactos por segmento.</p></aside></div>
  </main>;
  return <main className="module-page op-page"><SectionHeader eyebrow="AUDIENCIAS" title="Segmentos de clientes" description="Listas reutilizables para seleccionar destinatarios al crear una campaña." action={canCreateAny ? startCreate : null} actionLabel="Nuevo segmento" />
    {status === "loading" && <Loading>Cargando segmentos…</Loading>}
    {status === "error" && <div className="op-error">No fue posible cargar los segmentos después de varios intentos. Usa Actualizar datos.</div>}
    {error && <div className="op-error">{error}</div>}
    {status === "ready" && segments.length > 0 && <div className="op-table"><table><thead><tr><th>Segmento</th><th>Contactos</th><th>Teléfonos</th><th>Origen</th><th>Actualización</th><th>Descargar contactos</th><th></th></tr></thead><tbody>{segments.map((segment) => <tr key={segment.id}><td><b>{segment.name}</b><small>{segment.description || "Sin descripción"}</small></td><td>{segment.contact_count || 0}</td><td>{segment.phone_count || 0}</td><td><span className="op-badge">{segment.source === "file" ? "Archivo" : "Manual"}</span></td><td>{formatDate(segment.updated_at)}</td><td><div className="segment-export-actions"><button disabled={Boolean(exportingId)} onClick={() => exportContacts(segment, "excel")}><FileXls />Excel</button><button disabled={Boolean(exportingId)} onClick={() => exportContacts(segment, "pdf")}><FilePdf />PDF</button></div></td><td>{canCreateCampaign && <button onClick={() => onCreateCampaign(segment.id)}>Crear campaña <ArrowRight /></button>}</td></tr>)}</tbody></table></div>}
    {status === "ready" && !segments.length && <Empty icon={UsersThree} title="Crea tu primer segmento" description={canCreateAny ? "Importa un CSV o Excel, o registra los contactos manualmente." : "Tu perfil puede consultar segmentos, pero no crear ni importar nuevos."} action={canCreateAny ? startCreate : null} actionLabel="Nuevo segmento" />}
  </main>;
}

function CampaignStepper({ step }) {
  return <div className="op-stepper">{["Tipo", "Segmento", "Plantilla", "Revisar"].map((label, index) => <div className={step >= index + 1 ? "active" : ""} key={label}><span>{step > index + 1 ? <Check /> : index + 1}</span><b>{label}</b>{index < 3 && <i />}</div>)}</div>;
}

export function Campaigns({ refreshVersion, initialSegmentId = "", clearInitialSegment, permissions = {}, modulePermissions = {}, onViewResults }) {
  const [view, setView] = useState(initialSegmentId ? "create" : "list");
  const [campaigns, setCampaigns] = useState([]);
  const [segments, setSegments] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [flows, setFlows] = useState([]);
  const [status, setStatus] = useState("loading");
  const [step, setStep] = useState(1);
  const [type, setType] = useState("informative");
  const [segmentId, setSegmentId] = useState(initialSegmentId);
  const [phoneStrategy, setPhoneStrategy] = useState("primary");
  const [templateId, setTemplateId] = useState("");
  const [variableMappings, setVariableMappings] = useState({});
  const [name, setName] = useState("");
  const [submitState, setSubmitState] = useState("idle");
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteState, setDeleteState] = useState("idle");
  const canCreate = permissions.create !== false;
  const canSend = permissions.send !== false;
  const canDelete = permissions.delete === true;
  const canViewResponses = modulePermissions.responses?.view !== false;
  const load = () => {
    setStatus("loading");
    return Promise.all([
      listResource("campaigns"),
      modulePermissions.segments?.view === false ? Promise.resolve({ items: [] }) : listSegments(),
      canCreate ? listMetaTemplates() : Promise.resolve({ items: [] }),
      canCreate ? listMetaFlows() : Promise.resolve({ items: [] }),
    ])
      .then(([campaignResult, segmentResult, templateResult, flowResult]) => {
        setCampaigns(campaignResult?.items || []); setSegments(segmentResult?.items || []);
        setTemplates(templateResult?.items || []); setFlows(flowResult?.items || []); setStatus("ready");
      }).catch(() => setStatus("error"));
  };
  useEffect(() => { load(); }, [refreshVersion]);
  useEffect(() => { if (initialSegmentId) { setSegmentId(initialSegmentId); setStep(1); setTemplateId(""); setVariableMappings({}); setView("create"); } }, [initialSegmentId]);
  const selectedSegment = segments.find((item) => item.id === segmentId);
  const availableTemplates = templates.filter((template) => type === "survey" ? template.flow_ids?.length : type === "informative" ? !template.flow_ids?.length : true);
  const selectedTemplate = templates.find((item) => item.id === templateId);
  const linkedFlows = (selectedTemplate?.flow_ids || []).map((id) => flows.find((flow) => flow.id === id)).filter(Boolean);
  const recipients = Number(phoneStrategy === "all" ? selectedSegment?.phone_count : selectedSegment?.contact_count) || 0;
  const availableFields = selectedSegment?.available_fields || ["phone"];
  const mappingReady = (selectedTemplate?.variables || []).every((number) => variableMappings[number]);
  const mappedRecipientCount = (selectedTemplate?.variables || []).length
    ? Math.min(...(selectedTemplate.variables || []).map((number) => Number(selectedSegment?.field_counts?.[variableMappings[number]] || 0)))
    : recipients;
  const reset = () => { setView("list"); setStep(1); setType("informative"); setSegmentId(""); setPhoneStrategy("primary"); setTemplateId(""); setVariableMappings({}); setName(""); setSubmitState("idle"); setError(""); clearInitialSegment?.(); };
  function chooseTemplate(template) {
    setTemplateId(template.id);
    const preferred = ["name", "phone", "document_id", "email"].filter((field) => availableFields.includes(field));
    setVariableMappings(Object.fromEntries((template.variables || []).map((number, index) => [number, preferred[index] || availableFields[0] || "phone"])));
  }
  async function submit() {
    if (!selectedSegment || !selectedTemplate) return;
    const campaignId = `camp-${Date.now()}`;
    setSubmitState("sending"); setError("");
    try {
      await createCampaign({
        campaign_id: campaignId, name: name.trim() || `${CAMPAIGN_TYPES.find((item) => item.id === type)?.title} · ${selectedSegment.name}`,
        campaign_type: type, segment_id: selectedSegment.id, segment_name: selectedSegment.name, phone_strategy: phoneStrategy,
        template: { name: selectedTemplate.name, language: { code: selectedTemplate.language }, ...(selectedTemplate.flow_ids?.length ? { components: [{ type: "button", sub_type: "flow", index: "0", parameters: [{ type: "action", action: { flow_token: campaignId } }] }] } : {}) },
        flow_ids: selectedTemplate.flow_ids || [], flow_names: linkedFlows.map((flow) => flow.name), variable_mappings: variableMappings,
      });
      await load(); setSubmitState("sent");
    } catch (requestError) { setError(requestError.message || "No fue posible crear la campaña."); setSubmitState("error"); }
  }
  async function confirmDelete() {
    if (!deleteTarget || deleteConfirmation.trim() !== deleteTarget.name) return;
    setDeleteState("deleting"); setError("");
    try {
      await deleteCampaign(deleteTarget.id, deleteConfirmation.trim());
      setDeleteTarget(null); setDeleteConfirmation(""); setDeleteState("idle");
      await load();
    } catch (requestError) {
      setDeleteState("error"); setError(requestError.message || "No fue posible mover la campaña a la papelera.");
    }
  }
  if (view === "create") {
    if (submitState === "sent") return <main className="module-page op-page"><section className="op-success"><CheckCircle weight="fill" /><span>CAMPAÑA REGISTRADA</span><h1>Campaña enviada a procesamiento</h1><p>El estado de entrega y las respuestas se actualizarán desde el canal configurado.</p><dl><div><dt>Segmento</dt><dd>{selectedSegment?.name}</dd></div><div><dt>Destinatarios</dt><dd>{recipients}</dd></div><div><dt>Plantilla</dt><dd>{selectedTemplate?.name}</dd></div></dl><button className="primary" onClick={reset}>Volver a campañas</button></section></main>;
    return <main className="module-page op-page"><button className="op-back" onClick={reset}><ArrowLeft />Volver a campañas</button><SectionHeader eyebrow="NUEVA CAMPAÑA" title="Configurar campaña" description="Selecciona la audiencia y el contenido aprobado antes de confirmar el envío." /><CampaignStepper step={step} />
      {status === "loading" && <Loading>Cargando segmentos y plantillas…</Loading>}
      {status === "error" && <div className="op-error">No fue posible preparar la campaña después de varios intentos. Usa Actualizar datos.</div>}
      {status === "ready" && <section className="op-campaign-card">
        {step === 1 && <><div className="op-step-title"><span>1</span><div><h2>¿Qué tipo de campaña necesitas?</h2><p>Esta selección filtra las plantillas compatibles.</p></div></div><div className="op-type-grid">{CAMPAIGN_TYPES.map(({ id, title, description, icon: Icon }) => <button className={type === id ? "selected" : ""} key={id} onClick={() => { setType(id); setTemplateId(""); setVariableMappings({}); }}><span><Icon weight="duotone" /></span><b>{title}</b><p>{description}</p>{type === id && <CheckCircle weight="fill" />}</button>)}</div></>}
        {step === 2 && <><div className="op-step-title"><span>2</span><div><h2>Selecciona el segmento</h2><p>La audiencia debe estar guardada antes de iniciar una campaña.</p></div></div>{segments.length ? <><div className="op-segment-grid">{segments.map((segment) => <button className={segmentId === segment.id ? "selected" : ""} key={segment.id} onClick={() => setSegmentId(segment.id)}><UsersThree /><div><b>{segment.name}</b><small>{segment.contact_count || 0} contactos · {segment.phone_count || 0} teléfonos</small></div>{segmentId === segment.id && <CheckCircle weight="fill" />}</button>)}</div>{selectedSegment && <label className="op-strategy">Teléfonos a utilizar<select value={phoneStrategy} onChange={(event) => setPhoneStrategy(event.target.value)}><option value="primary">Teléfono principal de cada contacto</option><option value="all">Todos los teléfonos únicos del segmento</option></select><small>Estimado: {recipients} destinatarios únicos.</small></label>}</> : <Empty icon={UsersThree} title="No hay segmentos disponibles" description="Guarda un segmento antes de continuar con la campaña." />}</>}
        {step === 3 && <><div className="op-step-title"><span>3</span><div><h2>Selecciona la plantilla aprobada</h2><p>{type === "survey" ? "Solo aparecen plantillas vinculadas a un WhatsApp Flow." : type === "informative" ? "Solo aparecen plantillas informativas sin Flow." : "La plantilla iniciará la conversación antes de que el cliente responda."}</p></div></div><div className="op-template-grid">{availableTemplates.map((template) => <button className={templateId === template.id ? "selected" : ""} key={template.id} onClick={() => chooseTemplate(template)}><header><b>{template.name}</b><span>{template.language}</span></header><p>{template.body || "Sin vista previa de contenido"}</p><footer>{template.flow_ids?.length ? <span><FlowArrow />Incluye Flow</span> : <span><Megaphone />Mensaje de plantilla</span>}{templateId === template.id && <CheckCircle weight="fill" />}</footer></button>)}</div>{!availableTemplates.length && <Empty icon={NotePencil} title="No hay plantillas compatibles" description="Revisa el tipo de campaña o crea y aprueba la plantilla correspondiente en Meta." />}{linkedFlows.length > 0 && <div className="op-note"><FlowArrow /><span>Esta campaña iniciará: <b>{linkedFlows.map((flow) => flow.name).join(", ")}</b>.</span></div>}{selectedTemplate?.variables?.length > 0 && <section className="op-variable-mapping"><header><div><h3>Datos dinámicos de la plantilla</h3><p>Vincula cada variable de Meta con una columna detectada en el segmento.</p></div><span>{mappedRecipientCount} contactos con datos disponibles</span></header><div className="op-variable-grid">{selectedTemplate.variables.map((number) => <label key={number}><span>Variable {`{{${number}}}`}</span><select value={variableMappings[number] || ""} onChange={(event) => setVariableMappings({ ...variableMappings, [number]: event.target.value })}><option value="">Selecciona un dato</option>{availableFields.map((field) => <option value={field} key={field}>{FIELD_LABELS[field] || field}</option>)}</select></label>)}</div><div className="op-dynamic-preview"><small>Vista de campos</small><p>{String(selectedTemplate.body || "").replace(/\{\{(\d+)\}\}/g, (_match, number) => variableMappings[number] ? `{${FIELD_LABELS[variableMappings[number]]}}` : `{{${number}}}`)}</p></div></section>}</>}
        {step === 4 && <><div className="op-step-title"><span>4</span><div><h2>Revisa y confirma</h2><p>No se enviará ningún dato que no aparezca en este resumen.</p></div></div><label className="op-campaign-name">Nombre de la campaña <small>Opcional</small><input value={name} onChange={(event) => setName(event.target.value)} placeholder={`${CAMPAIGN_TYPES.find((item) => item.id === type)?.title} · ${selectedSegment?.name || "segmento"}`} /></label><dl className="op-review"><div><dt>Tipo</dt><dd>{CAMPAIGN_TYPES.find((item) => item.id === type)?.title}</dd></div><div><dt>Segmento</dt><dd>{selectedSegment?.name}</dd></div><div><dt>Destinatarios</dt><dd>{selectedTemplate?.variables?.length ? mappedRecipientCount : recipients}</dd></div><div><dt>Plantilla</dt><dd>{selectedTemplate?.name}</dd></div>{Object.keys(variableMappings).length > 0 && <div><dt>Datos dinámicos</dt><dd>{Object.entries(variableMappings).map(([number, field]) => `{{${number}}} = ${FIELD_LABELS[field] || field}`).join(" · ")}</dd></div>}{linkedFlows.length > 0 && <div><dt>Flow</dt><dd>{linkedFlows.map((flow) => flow.name).join(", ")}</dd></div>}</dl>{!canSend && <div className="op-note"><Info /><span>Puedes preparar y revisar la campaña, pero tu perfil no tiene permiso para enviarla.</span></div>}{error && <div className="op-error">{error}</div>}</>}
        <footer className="op-wizard-actions">{step > 1 ? <button className="secondary" onClick={() => setStep(step - 1)}><ArrowLeft />Atrás</button> : <span />}{step < 4 ? <button className="primary" disabled={(step === 2 && !selectedSegment) || (step === 3 && (!selectedTemplate || !mappingReady || mappedRecipientCount < 1))} onClick={() => setStep(step + 1)}>Continuar <ArrowRight /></button> : <button className="primary" disabled={!canSend || submitState === "sending" || !selectedSegment || !selectedTemplate || !mappingReady || mappedRecipientCount < 1} onClick={submit}>{submitState === "sending" ? <CircleNotch className="spin" /> : <Megaphone />}{submitState === "sending" ? "Procesando" : "Crear y enviar campaña"}</button>}</footer>
      </section>}
    </main>;
  }
  return <main className="module-page op-page"><SectionHeader eyebrow="DIFUSIÓN" title="Campañas" description="Envía plantillas aprobadas a segmentos guardados y sigue sus resultados." action={canCreate ? () => setView("create") : null} actionLabel="Nueva campaña" />
    {status === "loading" && <Loading>Cargando campañas…</Loading>}{status === "error" && <div className="op-error">No fue posible cargar las campañas después de varios intentos. Usa Actualizar datos.</div>}
    {status === "ready" && campaigns.length > 0 && <><div className="op-dashboard-metrics compact"><Metric icon={Megaphone} label="Campañas" value={campaigns.length} note="Registradas" /><Metric icon={CheckCircle} label="Destinatarios" value={campaigns.reduce((sum, item) => sum + Number(item.recipient_count || 0), 0)} note="Incluidos en envíos" tone="blue" /><Metric icon={ChartBar} label="Respuestas" value={campaigns.reduce((sum, item) => sum + Number(item.response_count || 0), 0)} note="Formularios recibidos" tone="amber" /></div><div className="op-table"><table><thead><tr><th>Campaña</th><th>Tipo</th><th>Segmento</th><th>Plantilla</th><th>Destinatarios</th><th>Entregados</th><th>Respuestas</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{campaigns.map((campaign) => <tr key={campaign.id}><td><b>{campaign.name}</b><small>{formatDate(campaign.created_at)}</small></td><td>{CAMPAIGN_TYPES.find((item) => item.id === campaign.campaign_type)?.title || "Campaña"}</td><td>{campaign.segment_name || "—"}</td><td>{campaign.template_name || "—"}</td><td>{campaign.recipient_count || 0}</td><td>{campaign.delivered_count || 0}</td><td>{campaign.response_count || 0}</td><td><span className={`op-badge ${campaign.status_tone || "blue"}`}>{campaign.status_label || "Procesando envíos"}</span></td><td><div className="op-row-actions">{canViewResponses && <button onClick={() => onViewResults?.(campaign.id)}><ChartBar />Ver resultados</button>}{canDelete && <button className="danger" onClick={() => { setDeleteTarget(campaign); setDeleteConfirmation(""); setDeleteState("idle"); }}><Trash />Borrar</button>}</div></td></tr>)}</tbody></table></div></>}
    {status === "ready" && !campaigns.length && <Empty icon={Megaphone} title="Aún no hay campañas" description={canCreate ? (segments.length ? "Selecciona un tipo, un segmento y una plantilla aprobada para comenzar." : "Primero crea un segmento de clientes y luego prepara la campaña.") : "Tu perfil puede consultar campañas, pero no preparar nuevas."} action={canCreate ? () => setView("create") : null} actionLabel="Nueva campaña" />}
    {deleteTarget && <div className="overlay"><section className="modal op-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-campaign-title"><header><div><span>ELIMINACIÓN RECUPERABLE</span><h2 id="delete-campaign-title">Mover campaña a la papelera</h2></div><button aria-label="Cerrar" onClick={() => setDeleteTarget(null)}>×</button></header><p>La campaña, sus entregas y sus respuestas dejarán de aparecer en las vistas normales. Un Developer podrá restaurarlas desde la papelera.</p><div className="op-delete-summary"><b>{deleteTarget.name}</b><span>{deleteTarget.recipient_count || 0} destinatarios · {deleteTarget.response_count || 0} respuestas</span></div><label>Escribe el nombre de la campaña para confirmar<input autoFocus value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} placeholder={deleteTarget.name} /></label>{deleteState === "error" && <div className="op-error">{error}</div>}<footer><button onClick={() => setDeleteTarget(null)}>Cancelar</button><button className="danger-button" disabled={deleteState === "deleting" || deleteConfirmation.trim() !== deleteTarget.name} onClick={confirmDelete}>{deleteState === "deleting" ? <CircleNotch className="spin" /> : <Trash />}{deleteState === "deleting" ? "Moviendo…" : "Mover a papelera"}</button></footer></section></div>}
  </main>;
}

export function CampaignTrash({ refreshVersion }) {
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("loading");
  const [restoringId, setRestoringId] = useState("");
  const load = () => {
    setStatus("loading");
    return listCampaignTrash().then((result) => { setItems(result?.items || []); setStatus("ready"); }).catch(() => setStatus("error"));
  };
  useEffect(() => { load(); }, [refreshVersion]);
  async function restore(item) {
    setRestoringId(item.id);
    try { await restoreCampaign(item.id); await load(); }
    catch { setStatus("error"); }
    finally { setRestoringId(""); }
  }
  return <main className="module-page op-page"><SectionHeader eyebrow="SOLO DEVELOPERS" title="Papelera de reciclaje" description="Recupera campañas eliminadas junto con sus entregas y respuestas. No hay eliminación permanente desde esta pantalla." action={load} actionLabel="Actualizar" actionIcon={ArrowCounterClockwise} />
    {status === "loading" && <Loading>Cargando papelera…</Loading>}
    {status === "error" && <div className="op-error">No fue posible cargar o restaurar los elementos. Inténtalo nuevamente.</div>}
    {status === "ready" && items.length > 0 && <div className="op-table"><table><thead><tr><th>Campaña</th><th>Tipo</th><th>Segmento</th><th>Destinatarios</th><th>Respuestas</th><th>Eliminada</th><th>Eliminada por</th><th>Acción</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><b>{item.name}</b><small>{item.template_name || "Sin plantilla"}</small></td><td>{CAMPAIGN_TYPES.find((type) => type.id === item.campaign_type)?.title || "Campaña"}</td><td>{item.segment_name || "—"}</td><td>{item.recipient_count || 0}</td><td>{item.response_count || 0}</td><td>{formatDate(item.deleted_at)}</td><td>{item.deleted_by_name || "Developer"}</td><td><button disabled={restoringId === item.id} onClick={() => restore(item)}>{restoringId === item.id ? <CircleNotch className="spin" /> : <ArrowCounterClockwise />}{restoringId === item.id ? "Restaurando…" : "Restaurar"}</button></td></tr>)}</tbody></table></div>}
    {status === "ready" && !items.length && <Empty icon={Trash} title="La papelera está vacía" description="Las campañas que se eliminen de forma recuperable aparecerán aquí solo para Developers." />}
  </main>;
}
