import { useEffect, useMemo, useState } from "react";
import {
  AddressBook,
  ArrowLeft,
  ArrowClockwise,
  CaretDown,
  ChartBar,
  Check,
  CheckCircle,
  CircleNotch,
  DeviceMobile,
  DownloadSimple,
  Eye,
  FilePdf,
  FileText,
  FileXls,
  FlowArrow,
  GearSix,
  House,
  MagnifyingGlass,
  Megaphone,
  NotePencil,
  Paperclip,
  PaperPlaneTilt,
  Plus,
  ShieldCheck,
  Trash,
  UsersThree,
  WhatsappLogo,
  X,
} from "@phosphor-icons/react";
import {
  createCampaign,
  createMetaTemplate,
  listAccessProfiles,
  listCampaignResponses,
  listMetaFlows,
  listMetaTemplates,
  listManagedMetaTemplates,
  listModulePermissions,
  listResource,
  manageMetaFlow,
  saveResource,
  sendQuote,
  updateAccessProfile,
  updateModulePermissions,
  uploadMedia,
} from "./api";
import { getBrand, getRuntimeConfig } from "./runtimeConfig";
import { Campaigns as OperationsCampaigns, CampaignTrash, Dashboard, Segments } from "./Operations";
import { exportExcelReport, exportPdfReport } from "./exporters";
import { flowResponseMatrix } from "./responseUtils";
import { buildFlowJson, normalizeFlowQuestions, templateVariables, validateFlowDraft } from "./flowBuilder";

const BRAND = getBrand();
const RUNTIME = getRuntimeConfig();
const LOCALE = RUNTIME.locale || "es";
const DEFAULT_CHANNEL_LABEL = RUNTIME.defaultChannelLabel || "Canal social";

const NAV = [
  ["dashboard", "Dashboard", House, "OPERACIÓN"],
  ["segments", "Segmentos", AddressBook, "OPERACIÓN"],
  ["campaigns", "Campañas", Megaphone, "OPERACIÓN"],
  ["responses", "Respuestas", ChartBar, "OPERACIÓN"],
  ["templates", "Plantillas", NotePencil, "CONTENIDO"],
  ["surveys", "Flows de WhatsApp", FlowArrow, "CONTENIDO"],
  ["quotes", "Cotizaciones", FileText, "HERRAMIENTAS"],
];
const Pill = ({ children, tone = "green" }) => (
  <span className={`pill ${tone}`}>{children}</span>
);

function Sidebar({ active, setActive, mode, session }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img src={BRAND.logoUrl} alt={`Logo de ${BRAND.name}`} />
        <div>
          {!BRAND.logoIncludesName && <b>{BRAND.name.toUpperCase()}</b>}
          <span>{BRAND.tagline}</span>
        </div>
      </div>
      <nav>
        {["OPERACIÓN", "CONTENIDO", "HERRAMIENTAS"].map((group) => <div className="nav-group" key={group}>
          <strong>{group}</strong>
          {NAV.filter(([id, , , itemGroup]) => itemGroup === group && session?.module_permissions?.[id]?.view !== false).map(([id, label, Icon]) => <button key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)}><Icon size={20} /><span>{label}</span></button>)}
        </div>)}
      </nav>
      <div className="side-bottom">
        {session?.role === "developer" && <button className={active === "trash" ? "active" : ""} onClick={() => setActive("trash")}>
          <Trash size={21} />
          Papelera de reciclaje
        </button>}
        <button
          className={active === "settings" ? "active" : ""}
          onClick={() => setActive("settings")}
        >
          <GearSix size={21} />
          Configuración
        </button>
        <div className="connect-state">
          <i />
          <div>
            <b>
              {mode === "connect" ? "Amazon Connect" : "Vista de demostración"}
            </b>
            <span>{mode === "connect" ? "Sesión conectada" : "Vista local"}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
function Topbar({ agent, mode, session, refreshing, onRefresh }) {
  const initials = agent.name
    .split(/\s+/)
    .slice(0, 2)
    .map((x) => x[0])
    .join("");
  return (
    <header className="topbar">
      <div>
        <DeviceMobile weight="fill" /> {DEFAULT_CHANNEL_LABEL} <i />{" "}
        {mode === "connect" ? "Sincronizado con Connect" : "Vista local"}
      </div>
      <section>
        <button className="global-refresh" onClick={onRefresh} disabled={refreshing} title="Volver a consultar los datos de esta pantalla"><ArrowClockwise className={refreshing ? "spin" : ""} />Actualizar datos</button>
        <span className="avatar">{initials}</span>
        <div>
          <b>{agent.name}</b>
          <small>{session?.role_label || "Agente"}</small>
        </div>
        <CaretDown />
      </section>
    </header>
  );
}
function Stepper({ step, setStep, maxStep = 3 }) {
  return (
    <div className="stepper">
      {["Cliente", "Contenido", "Revisar y enviar"].map((x, i) => (
        <div className={step >= i + 1 ? "on" : ""} key={x}>
          <button disabled={i + 1 > maxStep} onClick={() => setStep(i + 1)}>
            {step > i + 1 ? <Check /> : i + 1}
          </button>
          <span>{x}</span>
          {i < 2 && <i />}
        </div>
      ))}
    </div>
  );
}
function renderTemplate(template, values) {
  if (!template) return "";
  return template.body.replace(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*|\d+)\s*\}\}/g, (_match, variable) => String(values[variable] || "").trim() || `{{${variable}}}`);
}
function formatWhatsAppInline(text, keyPrefix = "wa") {
  const match = /(\*([^*\n]+)\*|_([^_\n]+)_|~([^~\n]+)~)/.exec(text);
  if (!match) return text;
  const before = text.slice(0, match.index);
  const after = text.slice(match.index + match[0].length);
  const content = match[2] ?? match[3] ?? match[4] ?? "";
  const formatted = match[2] !== undefined
    ? <strong key={`${keyPrefix}-strong`}>{formatWhatsAppInline(content, `${keyPrefix}-strong-inner`)}</strong>
    : match[3] !== undefined
      ? <em key={`${keyPrefix}-em`}>{formatWhatsAppInline(content, `${keyPrefix}-em-inner`)}</em>
      : <s key={`${keyPrefix}-strike`}>{formatWhatsAppInline(content, `${keyPrefix}-strike-inner`)}</s>;
  return [before, formatted, formatWhatsAppInline(after, `${keyPrefix}-rest`)];
}
function WhatsAppText({ text }) {
  const lines = String(text || "").split("\n");
  return <span className="wa-formatted">{lines.flatMap((line, index) => [
    formatWhatsAppInline(line, `line-${index}`),
    ...(index < lines.length - 1 ? [<br key={`break-${index}`} />] : []),
  ])}</span>;
}
function metaTemplatePayload(template, values, flowToken = "") {
  const parameters = (template.variables || []).map((variable) => ({
    type: "text",
    text: String(values[variable] || "").trim(),
    ...(!/^\d+$/.test(String(variable)) ? { parameter_name: String(variable) } : {}),
  }));
  const payload = {
    name: template.name,
    language: { code: template.language },
    ...(parameters.length ? { components: [{ type: "body", parameters }] } : {}),
  };
  if (template.flow_ids?.length) {
    payload.components = [...(payload.components || []), { type: "button", sub_type: "flow", index: "0", parameters: [{ type: "action", action: { flow_token: flowToken } }] }];
  }
  return payload;
}
const DEFAULT_QUOTE_TEMPLATE_NAME = "envio_cotizacion_solicitada";
function quoteVariableLabel(template, variable) {
  const key = String(variable);
  if (key === "nombre" || (template?.name === DEFAULT_QUOTE_TEMPLATE_NAME && key === "1")) return "Nombre del cliente";
  if (key === "nombre_agente" || (template?.name === DEFAULT_QUOTE_TEMPLATE_NAME && key === "2")) return "Nombre del agente";
  return `Variable {{${key}}}`;
}
function quoteTemplateValues(template, customerName, agentName) {
  if (!template) return {};
  const clientFirstName = String(customerName || "").trim().split(/\s+/)[0] || "";
  return Object.fromEntries((template.variables || []).map((variable) => {
    const key = String(variable);
    if (key === "nombre" || (template.name === DEFAULT_QUOTE_TEMPLATE_NAME && key === "1")) return [key, clientFirstName];
    if (key === "nombre_agente" || (template.name === DEFAULT_QUOTE_TEMPLATE_NAME && key === "2")) return [key, String(agentName || "").trim()];
    return [key, ""];
  }));
}
function campaignTemplatePayload(template, campaignId) {
  const payload = { name: template.name, language: { code: template.language } };
  if (template.flow_ids?.length) {
    payload.components = [{ type: "button", sub_type: "flow", index: "0", parameters: [{ type: "action", action: { flow_token: campaignId } }] }];
  }
  return payload;
}
function Preview({ recipientLabel, message, attachment, sentAt, template, templateValues = {} }) {
  const fileSize = attachment ? `${Math.ceil(attachment.size / 1024)} KB` : "";
  return (
    <section className="preview">
      <header>
        <b>Vista previa del mensaje de WhatsApp</b>
        <span>
          <DeviceMobile /> Vista de teléfono
        </span>
      </header>
      <div className="phone">
        <div className="phone-head">
          <ArrowLeft />
          <span className="avatar">{BRAND.name.slice(0, 2).toUpperCase()}</span>
          <div>
            <b>{BRAND.name}</b>
            <small>Cuenta comercial</small>
          </div>
          <WhatsappLogo weight="fill" />
        </div>
        <div className="phone-body">
          <div className="preview-recipient">Vista del destinatario: {recipientLabel || "por seleccionar"}</div>
          {template && <article className="bubble outbound template-bubble">{template.header && <b className="template-header"><WhatsAppText text={template.header} /></b>}<p><WhatsAppText text={renderTemplate(template, templateValues)} /></p>{template.footer && <small className="template-footer"><WhatsAppText text={template.footer} /></small>}{sentAt && <time>{sentAt} ✓✓</time>}</article>}
          {attachment ? <article className="file-bubble outbound">
            <FilePdf weight="fill" />
            <div>
              <b>{attachment.name}</b>
              <span>PDF{fileSize ? ` · ${fileSize}` : ""}</span>
              {message.trim() && <p>{message}</p>}
            </div>
            {sentAt && <time>{sentAt} ✓✓</time>}
          </article> : message.trim() ? <article className="bubble outbound"><p>{message}</p>{sentAt && <time>{sentAt} ✓✓</time>}</article> : <div className="preview-empty">El mensaje aparecerá aquí cuando agregues contenido y un documento.</div>}
        </div>
      </div>
      <p>
        La vista previa no agrega firma, hora, estado de entrega ni documento hasta que existan en el envío.
      </p>
    </section>
  );
}
function Quotes({ contact, agent, permissions = {} }) {
  const activeContact = contact?.phone ? contact : null;
  const [step, setStep] = useState(1);
  const [tpl, setTpl] = useState(null);
  const [attachment, setAttachment] = useState(null);
  const [recipientMode, setRecipientMode] = useState(activeContact ? "active" : "manual");
  const [recipientName, setRecipientName] = useState("");
  const [recipientText, setRecipientText] = useState("");
  const [recipientFileName, setRecipientFileName] = useState("");
  const [message, setMessage] = useState("");
  const [metaTemplates, setMetaTemplates] = useState([]);
  const [templateValues, setTemplateValues] = useState({});
  const [templatesStatus, setTemplatesStatus] = useState("loading");
  const [state, setState] = useState("idle");
  const [sentAt, setSentAt] = useState("");
  const canSend = permissions.send !== false;
  useEffect(() => {
    listMetaTemplates()
      .then((response) => {
        const items = response?.items || [];
        const defaultTemplate = items.find((item) => item.name === DEFAULT_QUOTE_TEMPLATE_NAME && String(item.category).toUpperCase() === "UTILITY");
        setMetaTemplates(items);
        if (defaultTemplate) {
          setTpl(defaultTemplate);
          setTemplateValues(quoteTemplateValues(defaultTemplate, activeContact?.name, agent.name));
        }
        setTemplatesStatus("ready");
      })
      .catch(() => setTemplatesStatus("error"));
  }, []);
  const recipients = useMemo(() => {
    if (recipientMode === "active") return activeContact?.phone ? [activeContact.phone] : [];
    return recipientText.split(/[\r\n,;]/).map((value) => value.replace(/[^\d+]/g, "").trim())
      .filter((value) => value.replace(/\D/g, "").length >= 8)
      .filter((value, index, rows) => rows.indexOf(value) === index).slice(0, 100);
  }, [activeContact?.phone, recipientMode, recipientText]);
  const recipientLabel = recipientMode === "active" ? activeContact?.name || "Contacto activo"
    : recipientMode === "manual" ? recipientName.trim() || recipients[0] || "Destinatario por seleccionar"
      : recipients.length ? `${recipients.length} destinatarios` : "Destinatarios por seleccionar";
  const templateReady = !tpl || (tpl.variables || []).every((number) => Boolean(templateValues[number]?.trim()));
  const readyForReview = recipients.length > 0 && Boolean(attachment) && templateReady && (Boolean(tpl) || Boolean(message.trim()));
  const applyTemplate = (template) => {
    setTpl(template);
    const customerName = recipientMode === "active" ? activeContact?.name : recipientName;
    setTemplateValues(quoteTemplateValues(template, customerName, agent.name));
  };
  useEffect(() => {
    if (!tpl) return;
    const customerName = recipientMode === "active" ? activeContact?.name : recipientName;
    const defaults = quoteTemplateValues(tpl, customerName, agent.name);
    setTemplateValues((current) => Object.fromEntries((tpl.variables || []).map((variable) => {
      const key = String(variable);
      return [key, String(current[key] || "").trim() ? current[key] : defaults[key]];
    })));
  }, [tpl?.id, recipientMode, activeContact?.name, recipientName, agent.name]);
  async function loadRecipients(file) {
    if (!file) return;
    setRecipientMode("list"); setRecipientText(await file.text()); setRecipientFileName(file.name);
  }
  async function send() {
    if (!readyForReview) return setState("error");
    setState("sending");
    try {
      const s3Key = await uploadMedia(attachment);
      const campaignId = `quote-${Date.now()}`;
      const payload = { agent_name: agent.name, contact_id: activeContact?.contactId || "", campaign_id: campaignId, media: { type: "document", s3_key: s3Key, filename: attachment.name, ...(message.trim() ? { caption: message.trim() } : {}) }, ...(tpl?.source === "meta" ? { template: metaTemplatePayload(tpl, templateValues, campaignId) } : {}) };
      if (recipients.length === 1) await sendQuote({ ...payload, to: recipients[0] });
      else await sendQuote({ ...payload, recipients: recipients.map((to) => ({ to })) });
      setSentAt(new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" }).format(new Date()));
      setState(`sent:${recipients.length}`);
    } catch { setState("error"); }
  }
  function startNewQuote() {
    const defaultTemplate = metaTemplates.find((item) => item.name === DEFAULT_QUOTE_TEMPLATE_NAME && String(item.category).toUpperCase() === "UTILITY") || null;
    setStep(1); setTpl(defaultTemplate); setAttachment(null); setRecipientMode(activeContact ? "active" : "manual");
    setRecipientName(""); setRecipientText(""); setRecipientFileName(""); setMessage(""); setTemplateValues(quoteTemplateValues(defaultTemplate, activeContact?.name, agent.name)); setSentAt(""); setState("idle");
  }
  if (state.startsWith("sent:")) return <div className="quote-page"><Stepper step={3} setStep={setStep} maxStep={3} /><section className="quote-success">
    <CheckCircle weight="fill" /><span>ENVÍO CONFIRMADO</span><h1>{Number(state.split(":")[1]) === 1 ? "Cotización enviada" : "Cotizaciones enviadas"}</h1>
    <p>{tpl ? "La plantilla y la cotización quedaron encoladas en ese orden para WhatsApp." : "El envío quedó registrado y se procesará por WhatsApp. El estado de entrega se actualizará cuando el canal lo confirme."}</p>
    <dl><div><dt>Destinatario</dt><dd>{recipientLabel}</dd></div><div><dt>{tpl ? "Plantilla inicial" : "Documento"}</dt><dd>{tpl?.name || attachment?.name}</dd></div><div><dt>Enviado por</dt><dd>{agent.name}</dd></div></dl>
    <div><button className="secondary" onClick={startNewQuote}>Crear otra cotización</button><button className="primary" onClick={() => setState(`${state}:preview`)}>Ver vista del envío</button></div>
    {state.endsWith(":preview") && <Preview recipientLabel={recipientLabel} message={message} attachment={attachment} template={tpl} templateValues={templateValues} sentAt={sentAt} />}
  </section></div>;
  const title = step === 1 ? "Selecciona el destinatario" : step === 2 ? "Prepara el contenido" : "Revisar y enviar cotización por WhatsApp";
  const description = step === 1 ? "Elige un contacto activo o escribe uno o varios destinatarios." : step === 2 ? "Escribe el mensaje y adjunta el PDF que deseas enviar." : "Verifica la información que se enviará y confirma el envío.";
  const maxStep = readyForReview ? 3 : recipients.length ? 2 : 1;
  return <div className="quote-page"><Stepper step={step} setStep={setStep} maxStep={maxStep} /><div className="quote-grid"><section className="review">
    {step > 1 && <button className="back" onClick={() => setStep(step - 1)}><ArrowLeft /> Volver al paso anterior</button>}
    <h1>{title}</h1><p className="subtitle">{description}</p><div className="review-list">
      {step === 1 && <Review icon={UsersThree} title="Cliente destinatario" action={recipientMode === "active" ? "Cambiar" : activeContact ? "Usar contacto activo" : ""} actionClick={() => setRecipientMode(recipientMode === "active" ? "manual" : "active")}>
        {recipientMode === "active" ? <div className="person"><span className="avatar">{activeContact?.initials || "SC"}</span><div><b>{activeContact?.name}</b>{(activeContact?.role || activeContact?.company) && <small>{[activeContact.role, activeContact.company].filter(Boolean).join(" · ")}</small>}<small className="wa"><WhatsappLogo weight="fill" /> {activeContact?.phone}</small></div></div> : <div className="recipient-editor"><div className="recipient-modes">{activeContact && <button onClick={() => setRecipientMode("active")}>Contacto activo</button>}<button className={recipientMode === "manual" ? "selected" : ""} onClick={() => setRecipientMode("manual")}>Un destinatario</button><button className={recipientMode === "list" ? "selected" : ""} onClick={() => setRecipientMode("list")}>Varios</button></div>{recipientMode === "manual" && <input value={recipientName} onChange={(event) => setRecipientName(event.target.value)} placeholder="Nombre del destinatario (opcional)" />}<textarea rows={recipientMode === "manual" ? 2 : 4} value={recipientText} onChange={(event) => { setRecipientText(event.target.value); setRecipientFileName(""); }} placeholder={recipientMode === "manual" ? "Ej.: +1 202 555 0148" : "Pega teléfonos separados por coma o una línea por destinatario"} /><label className="recipient-file"><input type="file" accept=".csv,.txt,text/csv,text/plain" onChange={(event) => loadRecipients(event.target.files?.[0])} />Cargar CSV o TXT</label><small>{recipientFileName ? `${recipientFileName} · ` : ""}{recipients.length} destinatario{recipients.length === 1 ? "" : "s"} válido{recipients.length === 1 ? "" : "s"}</small></div>}
      </Review>}
      {step === 2 && <><Review icon={NotePencil} title="Plantilla de inicio" action="Restablecer" actionClick={() => applyTemplate(metaTemplates.find((item) => item.name === DEFAULT_QUOTE_TEMPLATE_NAME && String(item.category).toUpperCase() === "UTILITY") || null)}><select value={tpl?.id || ""} onChange={(event) => applyTemplate(metaTemplates.find((item) => item.id === event.target.value) || null)}><option value="">Sin plantilla de inicio</option>{metaTemplates.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.language}</option>)}</select>{templatesStatus === "loading" && <small>Cargando plantillas aprobadas de Meta…</small>}{templatesStatus === "error" && <small className="auth-error">No fue posible cargar las plantillas de Meta después de varios intentos. Usa el botón general Actualizar.</small>}{tpl && <><small>{tpl.name === DEFAULT_QUOTE_TEMPLATE_NAME ? "Plantilla predeterminada para cotizaciones. Completa los dos nombres para continuar." : "Se enviará primero esta plantilla aprobada para iniciar la conversación."}</small>{(tpl.variables || []).map((variable) => <label className="template-variable" key={variable}>{quoteVariableLabel(tpl, variable)}<input required value={templateValues[variable] || ""} onChange={(event) => setTemplateValues({ ...templateValues, [variable]: event.target.value })} onBlur={() => setTemplateValues((current) => ({ ...current, [variable]: String(current[variable] || "").trim() }))} placeholder={quoteVariableLabel(tpl, variable)} /></label>)}</>}<textarea className="quote-message" rows="4" value={message} onChange={(event) => setMessage(event.target.value)} placeholder={tpl ? "Mensaje adicional para acompañar el PDF (opcional)" : "Escribe el mensaje que acompañará el PDF"} aria-label="Mensaje que acompañará la cotización" /><small>{tpl ? "La plantilla se enviará primero y luego el PDF. Este mensaje adicional es opcional." : "Escribe un mensaje para enviarlo junto con el PDF."}</small></Review><Review icon={Paperclip} title="Documento adjunto"><div className="document"><FilePdf weight="fill" /><div><input type="file" accept="application/pdf" onChange={(event) => setAttachment(event.target.files?.[0] || null)} /><small>{attachment ? `PDF · ${Math.ceil(attachment.size / 1024)} KB` : "Selecciona el PDF que deseas enviar"}</small></div></div></Review></>}
      {step === 3 && <><Review icon={UsersThree} title="Destinatario" action="Editar" actionClick={() => setStep(1)}><div className="person"><div><b>{recipientLabel}</b><small>{recipients.length === 1 ? recipients[0] : `${recipients.length} teléfonos seleccionados`}</small></div></div></Review>{tpl && <Review icon={NotePencil} title="Plantilla de inicio" action="Editar" actionClick={() => setStep(2)}><p className="review-message"><b>{tpl.name}</b>{"\n"}{tpl.header && <><WhatsAppText text={tpl.header} />{"\n"}</>}<WhatsAppText text={renderTemplate(tpl, templateValues)} />{tpl.footer && <>{"\n"}<WhatsAppText text={tpl.footer} /></>}</p></Review>}{message.trim() && <Review icon={NotePencil} title="Mensaje adicional" action="Editar" actionClick={() => setStep(2)}><p className="review-message">{message}</p></Review>}<Review icon={Paperclip} title="Documento adjunto" action="Editar" actionClick={() => setStep(2)}><div className="document"><FilePdf weight="fill" /><div><b>{attachment?.name}</b><small>PDF · {attachment ? `${Math.ceil(attachment.size / 1024)} KB` : ""}</small></div></div></Review><Review icon={FlowArrow} title="Ruta de entrega"><div className="route"><WhatsappLogo weight="fill" /><div><b>WhatsApp</b><small>{tpl ? "Plantilla → cotización" : "Entrega directa al destinatario"}</small></div></div></Review></>}
    </div><div className="send-row"><span />{step < 3 ? <button className="primary" onClick={() => setStep(step + 1)} disabled={step === 1 ? !recipients.length : !readyForReview}>{step === 1 ? "Continuar a contenido" : "Revisar envío"}</button> : <button className="primary" onClick={send} disabled={!canSend || state === "sending" || !readyForReview}>{state === "sending" ? <CircleNotch className="spin" /> : <PaperPlaneTilt weight="fill" />}{state === "sending" ? "Enviando" : state === "error" ? "Reintentar envío" : "Confirmar y enviar"}</button>}{!canSend && <small className="auth-error">Tu perfil puede preparar la cotización, pero no enviarla.</small>}{state === "error" && <small className="auth-error">Selecciona destinatario y PDF, y completa todas las variables obligatorias de la plantilla.</small>}</div>
  </section><Preview recipientLabel={recipientLabel} message={message} attachment={attachment} template={tpl} templateValues={templateValues} /></div></div>;
}
function Review({ icon: Icon, title, action, actionClick, children }) {
  return (
    <article>
      <span className="review-icon">
        <Icon weight="duotone" />
      </span>
      <div>
        <strong>{title}</strong>
        {children}
      </div>
      {action && <button onClick={actionClick}>{action}</button>}
    </article>
  );
}
function Header({ eyebrow, title, desc, action, label }) {
  const ActionIcon = label === "Actualizar" ? ArrowClockwise : Plus;
  return (
    <div className="page-header">
      <div>
        <span>{eyebrow}</span>
        <h1>{title}</h1>
        <p>{desc}</p>
      </div>
      {action && (
        <button className="primary small" onClick={action}>
          <ActionIcon /> {label}
        </button>
      )}
    </div>
  );
}
function Toolbar({ text }) {
  return (
    <div className="toolbar">
      <label>
        <MagnifyingGlass />
        <input placeholder={text} />
      </label>
      <button>
        Últimos 30 días <CaretDown />
      </button>
      <button>
        <DownloadSimple /> Exportar
      </button>
    </div>
  );
}
function Templates() {
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("loading");
  const [syncedAt, setSyncedAt] = useState(0);
  const loadTemplates = () => {
    setStatus(items.length ? "refreshing" : "loading");
    return listMetaTemplates()
      .then((result) => {
        setItems(result?.items || []);
        setSyncedAt(Number(result?.synced_at || 0));
        setStatus(result?.stale ? "stale" : "ready");
      })
      .catch(() => setStatus(items.length ? "stale" : "error"));
  };
  useEffect(() => { loadTemplates(); }, []);
  return (
    <Page>
      <Header
        eyebrow={`${String(RUNTIME.providerName || "Proveedor").toUpperCase()} · PLANTILLAS`}
        title="Plantillas de mensajes"
        desc={`Catálogo de plantillas aprobadas para ${BRAND.name}. La creación y aprobación se administra en ${RUNTIME.providerName}.`}
        action={loadTemplates}
        label="Actualizar"
      />
      {status === "loading" && <div className="flow-loading"><CircleNotch className="spin" /> Consultando plantillas aprobadas de Meta…</div>}
      {status === "refreshing" && <div className="flow-loading"><CircleNotch className="spin" /> Actualizando el catálogo sin ocultar los datos disponibles…</div>}
      {status === "stale" && <div className="info flow-info"><ArrowClockwise /><span>{RUNTIME.providerName} no respondió temporalmente. Se conserva el último catálogo sincronizado{syncedAt ? ` el ${new Intl.DateTimeFormat(LOCALE, { dateStyle: "short", timeStyle: "short" }).format(new Date(syncedAt * 1000))}` : ""}.</span></div>}
      {status === "error" && <div className="flow-loading">El catálogo todavía no está disponible. La aplicación volverá a consultarlo al actualizar los datos.</div>}
      {["ready", "stale", "refreshing"].includes(status) && <div className="cards">
        {items.map((x) => (
          <article className="template-card" key={x.id}>
            <header>
              <span>
                <NotePencil />
              </span>
              <Pill tone={x.status === "Aprobada" ? "green" : "amber"}>
                {x.status}
              </Pill>
            </header>
            <h3>{x.name}</h3>
            <p>{x.body}</p>
            <div className="tags">
              <span>{x.category}</span>
              <span>{x.language}</span>
              {x.flow_ids?.length ? <span>Inicia WhatsApp Flow</span> : null}
            </div>
            <footer>
              <small>Administrada y aprobada en Meta</small>
            </footer>
          </article>
        ))}
      </div>
      }
      {["ready", "stale"].includes(status) && !items.length && <div className="flow-loading">No hay plantillas aprobadas disponibles para este número.</div>}
    </Page>
  );
}
function Modal({ item, close, save }) {
  const [v, setV] = useState(item);
  return (
    <div className="overlay">
      <div className="modal">
        <header>
          <div>
            <span>EDITOR DE WHATSAPP</span>
            <h2>{item.id ? "Editar plantilla" : "Crear plantilla"}</h2>
          </div>
          <button onClick={close}>
            <X />
          </button>
        </header>
        <label>
          Nombre
          <input
            value={v.name}
            onChange={(e) => setV({ ...v, name: e.target.value })}
          />
        </label>
        <label>
          Categoría
          <select
            value={v.category}
            onChange={(e) => setV({ ...v, category: e.target.value })}
          >
            <option>Utilidad</option>
            <option>Marketing</option>
          </select>
        </label>
        <label>
          Contenido
          <textarea
            rows="8"
            value={v.body}
            onChange={(e) => setV({ ...v, body: e.target.value })}
          />
        </label>
        <footer>
          <button onClick={close}>Cancelar</button>
          <button className="primary small" onClick={() => save(v)}>
            Guardar plantilla
          </button>
        </footer>
      </div>
    </div>
  );
}
function LegacyCampaigns() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("loading");
  const loadCampaigns = () => {
    setStatus("loading");
    return listResource("campaigns")
      .then((result) => {
        setItems(result?.items || []);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  };
  useEffect(() => { loadCampaigns(); }, []);
  return (
    <Page>
      <Header
        eyebrow="DIFUSIÓN"
        title="Campañas"
        desc="Envía plantillas aprobadas, controla la entrega y asigna el flujo de respuesta."
        action={() => setOpen(true)}
        label="Nueva campaña"
      />
      <div className="catalog-actions"><button onClick={loadCampaigns} disabled={status === "loading"}><ArrowClockwise className={status === "loading" ? "spin" : ""} /> Actualizar</button></div>
      <Metrics items={items} />
      {status === "error" && <div className="auth-error">No fue posible consultar las campañas. Pulsa Actualizar para intentarlo nuevamente.</div>}
      {status === "loading" && <div className="flow-loading"><CircleNotch className="spin" /> Consultando campañas…</div>}
      {status === "ready" && <Table
        heads={[
          "Campaña",
          "Plantilla",
          "Destinatarios",
          "Entregados",
          "Respuestas",
          "Estado",
          "",
        ]}
      >
        {items.map((x) => (
          <tr key={x.id}>
            <td>
              <b>{x.name}</b>
              <small>{x.created_at ? new Date(Number(x.created_at) * 1000).toLocaleString(LOCALE) : "—"}</small>
            </td>
            <td>{x.template_name || "—"}{x.flow_ids?.length ? <small>Incluye WhatsApp Flow</small> : null}</td>
            <td>{x.recipient_count || 0}</td>
            <td>{x.delivered_count || 0}</td>
            <td>{x.response_count || 0}</td>
            <td>
              <Pill tone={x.status === "QUEUED" ? "green" : "blue"}>
                {x.status === "QUEUED" ? "Enviada" : x.status || "Procesando"}
              </Pill>
            </td>
            <td>
              <Eye />
            </td>
          </tr>
        ))}
      </Table>
      }
      {status === "ready" && !items.length && <div className="flow-loading">Todavía no hay campañas enviadas. Crea la primera seleccionando destinatarios y una plantilla aprobada.</div>}
      {open && <Drawer close={() => setOpen(false)} onCreated={loadCampaigns} />}
    </Page>
  );
}
function Metrics({ items = [] }) {
  const recipients = items.reduce((sum, item) => sum + Number(item.recipient_count || 0), 0);
  const delivered = items.reduce((sum, item) => sum + Number(item.delivered_count || 0), 0);
  const responseCount = items.reduce((sum, item) => sum + Number(item.response_count || 0), 0);
  return (
    <div className="metrics">
      <Metric label="Destinatarios" value={recipients} note={`${items.length} campaña${items.length === 1 ? "" : "s"}`} />
      <Metric label="Entregados" value={delivered} note={recipients ? `${Math.round((delivered / recipients) * 100)}% de entrega` : "Sin envíos todavía"} />
      <Metric label="Respuestas de Flow" value={responseCount} note={recipients ? `${Math.round((responseCount / recipients) * 100)}% de respuesta` : "Sin respuestas todavía"} />
    </div>
  );
}
function Metric(p) {
  return (
    <article>
      <span>{p.label}</span>
      <b>{p.value}</b>
      <small>{p.note}</small>
    </article>
  );
}
function Drawer({ close, onCreated }) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [recipients, setRecipients] = useState("");
  const [templates, setTemplates] = useState([]);
  const [flows, setFlows] = useState([]);
  const [templateId, setTemplateId] = useState("");
  const [status, setStatus] = useState("loading");
  const [submitState, setSubmitState] = useState("idle");
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([listMetaTemplates(), listMetaFlows()])
      .then(([templateResult, flowResult]) => {
        setTemplates(templateResult?.items || []);
        setFlows(flowResult?.items || []);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);
  const selectedTemplate = templates.find((item) => item.id === templateId);
  const recipientRows = recipients.split(/\r?\n|,/).map((value) => value.replace(/[^\d+]/g, "").trim())
    .filter((value) => value.replace(/\D/g, "").length >= 8).slice(0, 100);
  const linkedFlows = (selectedTemplate?.flow_ids || []).map((id) => flows.find((flow) => flow.id === id)).filter(Boolean);
  async function submit() {
    const campaignId = `camp-${Date.now()}`;
    if (!selectedTemplate || !recipientRows.length) return;
    setSubmitState("sending");
    setError("");
    try {
      await createCampaign({
        campaign_id: campaignId,
        name: name.trim() || `Campaña ${selectedTemplate.name}`,
        type: "template",
        template: campaignTemplatePayload(selectedTemplate, campaignId),
        flow_ids: selectedTemplate.flow_ids || [],
        flow_names: linkedFlows.map((flow) => flow.name),
        recipients: recipientRows.map((phone) => ({ phone })),
      });
      await onCreated?.();
      close();
    } catch (requestError) {
      setError(requestError.message || "No fue posible crear la campaña.");
      setSubmitState("error");
    }
  }
  return (
    <div className="overlay right">
      <aside className="drawer">
        <header>
          <div>
            <span>NUEVA CAMPAÑA</span>
            <h2>{step === 1 ? "Selecciona los destinatarios" : "Selecciona la plantilla"}</h2>
          </div>
          <button onClick={close}>
            <X />
          </button>
        </header>
        {step === 1 ? (
          <>
            <label>
              Nombre de campaña <small>Opcional</small>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ej.: Encuesta clientes agosto" />
            </label>
            <label>
              Lista de números
              <textarea
                rows="7"
                value={recipients}
                onChange={(e) => setRecipients(e.target.value)}
                placeholder="Pega teléfonos, uno por línea o separados por coma"
              />
              <small>{recipientRows.length} destinatario{recipientRows.length === 1 ? "" : "s"} válido{recipientRows.length === 1 ? "" : "s"}</small>
            </label>
          </>
        ) : (
          <>
            <label>
              Plantilla aprobada de Meta
              <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} disabled={status !== "ready"}>
                <option value="">Selecciona una plantilla</option>
                {templates.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.language}{item.flow_ids?.length ? " · Flow" : ""}</option>)}
              </select>
            </label>
            {status === "loading" && <div className="info"><CircleNotch className="spin" /> Cargando plantillas y Flows de Meta…</div>}
            {status === "error" && <div className="info">No fue posible cargar el catálogo de Meta. Actualiza la pantalla e inténtalo de nuevo.</div>}
            {selectedTemplate && <div className="info"><FlowArrow /> {linkedFlows.length ? <>Esta plantilla inicia: <b>{linkedFlows.map((flow) => flow.name).join(", ")}</b>.</> : "Esta plantilla no tiene un Flow asociado."}</div>}
            {error && <div className="auth-error">{error}</div>}
          </>
        )}
        <footer>
          <button onClick={step === 1 ? close : () => setStep(1)}>
            {step === 1 ? "Cancelar" : "Atrás"}
          </button>
          <button
            className="primary small"
            disabled={submitState === "sending" || (step === 1 ? !recipientRows.length : !selectedTemplate)}
            onClick={step === 1 ? () => setStep(2) : submit}
          >
            {step === 1 ? "Elegir plantilla" : submitState === "sending" ? "Enviando…" : "Crear campaña"}
          </button>
        </footer>
      </aside>
    </div>
  );
}
function LegacySurvey() {
  const seed = {
    id: "survey-new",
    name: "Nueva encuesta",
    status: "Borrador",
    questions: [
      { id: 1, text: "¿Cómo calificarías tu experiencia?", type: "Botones", opts: ["Excelente", "Buena", "Regular"] },
      { id: 2, text: "¿Qué podemos mejorar?", type: "Texto libre", opts: [] },
    ],
  };
  const [items, setItems] = useState([seed]),
    [activeId, setActiveId] = useState(seed.id),
    [sel, setSel] = useState(1),
    [saveState, setSaveState] = useState("idle");
  useEffect(() => {
    listResource("surveys")
      .then((result) => {
        if (!result?.items?.length) return;
        setItems(result.items);
        setActiveId(result.items[0].id);
        setSel(result.items[0].questions?.[0]?.id);
      })
      .catch(() => {});
  }, []);
  const survey = items.find((item) => item.id === activeId) || items[0];
  const qs = survey.questions || [];
  const q = qs.find((x) => x.id === sel);
  const update = (o) =>
    setItems((current) => current.map((item) => item.id === activeId ? { ...item, questions: qs.map((x) => x.id === sel ? { ...x, ...o } : x) } : item));
  function updateSurvey(values) {
    setItems((current) => current.map((item) => item.id === activeId ? { ...item, ...values } : item));
  }
  function createSurvey() {
    const id = `survey-${Date.now()}`;
    const next = { ...seed, id, name: "Nueva encuesta", questions: seed.questions.map((question) => ({ ...question })) };
    setItems((current) => [next, ...current]);
    setActiveId(id);
    setSel(1);
    setSaveState("idle");
  }
  async function saveSurvey() {
    setSaveState("saving");
    try {
      const saved = await saveResource("surveys", { ...survey, status: survey.status || "Borrador" });
      setItems((current) => current.map((item) => item.id === activeId ? saved : item));
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }
  return (
    <Page>
      <Header
        eyebrow="AUTOMATIZACIÓN"
        title="Diseñador de encuestas"
        desc="Construye la conversación por pasos y conecta cada respuesta con Amazon Connect."
        action={() => {
          let id = Date.now();
          updateSurvey({ questions: [
            ...qs,
            {
              id,
              text: "Nueva pregunta",
              type: "Botones",
              opts: ["Opción 1", "Opción 2"],
            },
          ] });
          setSel(id);
        }}
        label="Agregar pregunta"
      />
      <div className="survey-manager">
        <label>
          Encuesta activa
          <select value={activeId} onChange={(event) => { const id = event.target.value; setActiveId(id); setSel(items.find((item) => item.id === id)?.questions?.[0]?.id); setSaveState("idle"); }}>
            {items.map((item) => <option key={item.id} value={item.id}>{item.name || "Sin nombre"}</option>)}
          </select>
        </label>
        <button className="primary small" onClick={createSurvey}><Plus /> Nueva encuesta</button>
      </div>
      <div className="builder">
        <aside>
          <b>Flujo de la encuesta</b>
          <div className="flow start">
            <WhatsappLogo weight="fill" /> Inicio por WhatsApp
          </div>
          {qs.map((x, i) => (
            <button
              className={sel === x.id ? "active" : ""}
              onClick={() => setSel(x.id)}
              key={x.id}
            >
              <span>{i + 1}</span>
              <div>
                <b>{x.text}</b>
                <small>{x.type}</small>
              </div>
            </button>
          ))}
          <div className="flow">
            <CheckCircle weight="fill" /> Finalizar y guardar
          </div>
        </aside>
        <section>
          <span>ENCUESTA Y PREGUNTA SELECCIONADA</span>
          <label>
            Nombre de la encuesta
            <input value={survey.name || ""} onChange={(event) => updateSurvey({ name: event.target.value })} placeholder="Ej.: Satisfacción postventa" />
          </label>
          {q && <>
          <label>
            Texto
            <input
              value={q.text}
              onChange={(e) => update({ text: e.target.value })}
            />
          </label>
          <label>
            Tipo
            <select
              value={q.type}
              onChange={(e) => update({ type: e.target.value })}
            >
              <option>Botones</option>
              <option>Lista</option>
              <option>Texto libre</option>
              <option>Ubicación</option>
            </select>
          </label>
          {q.type !== "Texto libre" && (
            <label>
              Opciones
              <textarea
                rows="5"
                value={q.opts.join("\n")}
                onChange={(e) => update({ opts: e.target.value.split("\n") })}
              />
            </label>
          )}
          <label>
            Al responder
            <select>
              <option>Continuar a la siguiente pregunta</option>
              <option>Iniciar flujo de Connect</option>
              <option>Transferir a un agente</option>
            </select>
          </label>
          <button
            className="primary small"
            onClick={saveSurvey}
            disabled={saveState === "saving"}
          >
            <Check /> {saveState === "saving" ? "Guardando..." : saveState === "saved" ? "Encuesta guardada" : "Guardar encuesta"}
          </button>
          {saveState === "error" && <small className="auth-error">No se pudo guardar la encuesta.</small>}
          </>}
        </section>
        <section className="survey-preview">
          <b>Vista previa</b>
          <div>
            <header>
              <WhatsappLogo weight="fill" /> {BRAND.name}
            </header>
            <p>{q?.text}</p>
            {q?.opts.map((x) => (
              <button key={x}>{x}</button>
            ))}
          </div>
        </section>
      </div>
    </Page>
  );
}
const FLOW_CATEGORIES = [
  ["SURVEY", "Encuesta"], ["LEAD_GENERATION", "Captación de clientes"],
  ["CUSTOMER_SUPPORT", "Atención al cliente"], ["APPOINTMENT_BOOKING", "Citas"],
  ["CONTACT_US", "Contacto"], ["SIGN_UP", "Registro"], ["SIGN_IN", "Inicio de sesión"], ["OTHER", "Otro"],
];
const emptyQuestion = () => ({ id: crypto.randomUUID(), label: "", key: "", type: "text", required: true, options: [] });
const emptyFlowDraft = () => ({ name: "", category: "SURVEY", buttonLabel: "Enviar", questions: [emptyQuestion()] });
const emptyTemplateDraft = () => ({ name: "", language: RUNTIME.defaultTemplateLanguage || "es", category: "UTILITY", body: "", footer: "", buttonText: "Abrir formulario", flowId: "", flowName: "", screen: "FORMULARIO", examples: {} });

function FlowStepper({ step }) {
  return <div className="op-stepper flow-stepper">{["Información", "Formulario", "Revisar"].map((label, index) => <div className={step >= index + 1 ? "active" : ""} key={label}><span>{step > index + 1 ? <Check /> : index + 1}</span>{label}{index < 2 && <i />}</div>)}</div>;
}

function metaErrorMessage(error) {
  const code = String(error?.message || "");
  const known = {
    invalid_flow_name: "El nombre solo puede contener letras, números, espacios, guiones, puntos y guion bajo.",
    flow_screens_required: "El formulario necesita al menos una pantalla.",
    publish_confirmation_required: "Confirma que deseas publicar el Flow.",
    template_variable_examples_required: "Completa un ejemplo para cada variable de la plantilla.",
    invalid_template_name: "El nombre de la plantilla debe estar en minúsculas y usar guion bajo.",
  };
  return known[code] || code || "No fue posible completar la operación en Meta.";
}

function Survey({ permissions, templatePermissions }) {
  const [flows, setFlows] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [status, setStatus] = useState("loading");
  const [mode, setMode] = useState("catalog");
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState(emptyFlowDraft);
  const [templateDraft, setTemplateDraft] = useState(emptyTemplateDraft);
  const [operation, setOperation] = useState("idle");
  const [error, setError] = useState("");
  const [flowResult, setFlowResult] = useState(null);
  const [templateResult, setTemplateResult] = useState(null);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const canManageFlows = permissions?.manage !== false;
  const canManageTemplates = templatePermissions?.manage !== false;
  const loadCatalog = () => {
    setStatus("loading");
    return Promise.all([listMetaFlows(), canManageTemplates ? listManagedMetaTemplates() : listMetaTemplates()])
      .then(([flowResult, templateResult]) => {
        setFlows(flowResult?.items || []);
        setTemplates(templateResult?.items || []);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  };
  useEffect(() => { loadCatalog(); }, []);

  function startFlow() {
    setDraft(emptyFlowDraft()); setFlowResult(null); setError(""); setStep(1); setMode("flow");
  }
  function startTemplate(flow = null) {
    setTemplateDraft({ ...emptyTemplateDraft(), flowId: flow?.id || "", flowName: flow?.name || "" });
    setTemplateResult(null); setError(""); setMode("template");
  }
  function updateQuestion(id, patch) {
    setDraft((current) => ({ ...current, questions: current.questions.map((question) => question.id === id ? { ...question, ...patch } : question) }));
  }
  function goNext() {
    setError("");
    if (step === 1 && !draft.name.trim()) return setError("Escribe el nombre del Flow para continuar.");
    if (step === 2) {
      const validation = validateFlowDraft(draft);
      if (validation.length) return setError(validation.join(" "));
    }
    setStep((value) => Math.min(3, value + 1));
  }
  async function saveFlow() {
    const validation = validateFlowDraft(draft);
    if (validation.length) { setError(validation.join(" ")); return; }
    setOperation("saving"); setError("");
    try {
      const flowJson = buildFlowJson(draft);
      const result = await manageMetaFlow(flowResult?.id
        ? { action: "update_json", flow_id: flowResult.id, flow_json: flowJson }
        : { action: "create", name: draft.name.trim(), categories: [draft.category], flow_json: flowJson });
      setFlowResult((current) => ({ ...current, ...result, name: draft.name.trim(), json: flowJson }));
      setOperation("saved");
    } catch (nextError) { setError(metaErrorMessage(nextError)); setOperation("idle"); }
  }
  async function publishFlow() {
    if (!flowResult?.id || !confirmPublish) return;
    setOperation("publishing"); setError("");
    try {
      const result = await manageMetaFlow({ action: "publish", flow_id: flowResult.id, confirm_publish: true });
      setFlowResult((current) => ({ ...current, ...result, published: true }));
      setOperation("published"); setConfirmPublish(false);
      await loadCatalog();
    } catch (nextError) { setError(metaErrorMessage(nextError)); setOperation("saved"); }
  }
  function selectTemplateFlow(flowId) {
    const flow = flows.find((item) => item.id === flowId);
    setTemplateDraft((current) => ({ ...current, flowId, flowName: flow?.name || "" }));
  }
  async function saveTemplate() {
    const variables = templateVariables(templateDraft.body);
    if (!templateDraft.name.trim() || !templateDraft.body.trim() || !templateDraft.flowName) {
      setError("Completa el nombre, el mensaje y el Flow publicado."); return;
    }
    if (variables.some((variable) => !String(templateDraft.examples[variable] || "").trim())) {
      setError("Completa un ejemplo para cada variable antes de enviar la plantilla a revisión."); return;
    }
    setOperation("saving-template"); setError("");
    try {
      const result = await createMetaTemplate({
        name: templateDraft.name.trim(), language: templateDraft.language, category: templateDraft.category,
        body: templateDraft.body.trim(), footer: templateDraft.footer.trim(), button_text: templateDraft.buttonText.trim(),
        flow_name: templateDraft.flowName, navigate_screen: templateDraft.screen, variable_examples: templateDraft.examples,
      });
      setTemplateResult(result); setOperation("template-saved"); await loadCatalog();
    } catch (nextError) { setError(metaErrorMessage(nextError)); setOperation("idle"); }
  }

  if (mode === "flow") {
    const flowJson = buildFlowJson(draft);
    const validationErrors = flowResult?.validation_errors || [];
    return <Page>
      <button className="op-back" onClick={() => { setMode("catalog"); loadCatalog(); }}><ArrowLeft /> Volver al catálogo</button>
      <Header eyebrow="NUEVO WHATSAPP FLOW" title="Crear Flow" desc="Diseña el formulario, guarda un borrador en Meta y publícalo cuando esté validado." />
      <FlowStepper step={step} />
      <section className="flow-author-card">
        {step === 1 && <><div className="op-step-title"><span>1</span><div><h2>Identifica el Flow</h2><p>Este nombre aparecerá en el catálogo interno de Meta.</p></div></div><div className="flow-field-grid"><label>Nombre del Flow<input value={draft.name} maxLength="200" onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="Ej.: Encuesta de servicio" /></label><label>Categoría<select value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>{FLOW_CATEGORIES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label>Texto del botón final<input value={draft.buttonLabel} maxLength="30" onChange={(event) => setDraft({ ...draft, buttonLabel: event.target.value })} /></label></div></>}
        {step === 2 && <><div className="op-step-title"><span>2</span><div><h2>Construye el formulario</h2><p>Agrega las preguntas que recibirá el cliente dentro de WhatsApp.</p></div></div><div className="flow-question-list">{draft.questions.map((question, index) => <article key={question.id}><header><b>Pregunta {index + 1}</b><button disabled={draft.questions.length === 1} onClick={() => setDraft({ ...draft, questions: draft.questions.filter((item) => item.id !== question.id) })}><X /> Eliminar</button></header><div className="flow-question-grid"><label>Pregunta<input value={question.label} onChange={(event) => updateQuestion(question.id, { label: event.target.value })} placeholder="Escribe la pregunta" /></label><label>Tipo de respuesta<select value={question.type} onChange={(event) => updateQuestion(question.id, { type: event.target.value })}><option value="text">Texto libre</option><option value="radio">Una opción</option><option value="checkbox">Varias opciones</option><option value="dropdown">Lista desplegable</option></select></label><label className="flow-required"><input type="checkbox" checked={question.required} onChange={(event) => updateQuestion(question.id, { required: event.target.checked })} /> Respuesta obligatoria</label>{question.type !== "text" && <label className="flow-options">Opciones, una por línea<textarea rows="4" value={(question.options || []).join("\n")} onChange={(event) => updateQuestion(question.id, { options: event.target.value.split("\n") })} placeholder={"Primera opción\nSegunda opción"} /></label>}</div></article>)}</div><button className="op-add-row" onClick={() => setDraft({ ...draft, questions: [...draft.questions, emptyQuestion()] })}><Plus /> Agregar pregunta</button></>}
        {step === 3 && <><div className="op-step-title"><span>3</span><div><h2>Revisa antes de crear</h2><p>Meta recibirá primero un borrador. Publicarlo será una acción separada.</p></div></div><dl className="op-review"><div><dt>Flow</dt><dd>{draft.name.trim()}</dd></div><div><dt>Categoría</dt><dd>{FLOW_CATEGORIES.find(([value]) => value === draft.category)?.[1]}</dd></div><div><dt>Preguntas</dt><dd>{draft.questions.length}</dd></div><div><dt>Pantalla inicial</dt><dd>FORMULARIO</dd></div></dl><details className="flow-json-review"><summary>Ver definición técnica validada</summary><pre>{JSON.stringify(flowJson, null, 2)}</pre></details></>}
        {error && <div className="op-error">{error}</div>}
        {!flowResult && <div className="op-wizard-actions"><button onClick={() => setStep(Math.max(1, step - 1))} disabled={step === 1}>Anterior</button>{step < 3 ? <button className="primary" onClick={goNext}>Continuar</button> : <button className="primary" onClick={saveFlow} disabled={operation === "saving"}>{operation === "saving" ? <CircleNotch className="spin" /> : <CheckCircle />} Crear borrador en Meta</button>}</div>}
        {flowResult && <div className="flow-created"><CheckCircle weight="fill" /><div><h3>Borrador creado</h3><p>{flowResult.name} · ID {flowResult.id}</p></div>{validationErrors.length ? <div className="op-error"><b>Meta encontró validaciones pendientes</b>{validationErrors.map((item, index) => <p key={index}>{item.error || item.message || JSON.stringify(item)}</p>)}<button onClick={() => { setFlowResult((current) => ({ ...current })); setStep(2); }}>Volver y corregir</button></div> : <><label className="flow-publish-confirm"><input type="checkbox" checked={confirmPublish} onChange={(event) => setConfirmPublish(event.target.checked)} /> Confirmo que revisé el formulario. Entiendo que después de publicarlo no podré editar esta versión.</label><div className="flow-publish-actions"><button onClick={startFlow}>Crear otro Flow</button>{flowResult.published ? <button className="primary" disabled={!canManageTemplates} onClick={() => startTemplate(flowResult)}><Plus /> Crear plantilla para este Flow</button> : <button className="primary" disabled={!confirmPublish || operation === "publishing"} onClick={publishFlow}>{operation === "publishing" ? <CircleNotch className="spin" /> : <PaperPlaneTilt />} Publicar Flow</button>}</div></>}</div>}
      </section>
    </Page>;
  }

  if (mode === "template") {
    const variables = templateVariables(templateDraft.body);
    const publishedFlows = flows.filter((flow) => flow.published || flow.id === templateDraft.flowId);
    return <Page><button className="op-back" onClick={() => setMode("catalog")}><ArrowLeft /> Volver al catálogo</button><Header eyebrow="NUEVA PLANTILLA" title="Crear plantilla con botón de Flow" desc="La plantilla iniciará la conversación y abrirá el formulario publicado dentro de WhatsApp." />
      <div className="flow-template-layout"><section className="flow-author-card"><div className="flow-field-grid"><label>Flow publicado<select value={templateDraft.flowId} onChange={(event) => selectTemplateFlow(event.target.value)}><option value="">Selecciona un Flow</option>{publishedFlows.map((flow) => <option value={flow.id} key={flow.id}>{flow.name} · {flow.status}</option>)}</select></label><label>Nombre de la plantilla<input value={templateDraft.name} onChange={(event) => setTemplateDraft({ ...templateDraft, name: event.target.value.toLowerCase().replace(/\s+/g, "_") })} placeholder="encuesta_servicio" /><small>Minúsculas, números y guion bajo.</small></label><label>Categoría<select value={templateDraft.category} onChange={(event) => setTemplateDraft({ ...templateDraft, category: event.target.value })}><option value="UTILITY">Utilidad</option><option value="MARKETING">Marketing</option></select></label><label>Idioma<select value={templateDraft.language} onChange={(event) => setTemplateDraft({ ...templateDraft, language: event.target.value })}><option value="es_DO">Español (República Dominicana)</option><option value="es">Español</option><option value="en_US">English (US)</option></select></label><label className="flow-wide">Mensaje<textarea rows="6" value={templateDraft.body} onChange={(event) => setTemplateDraft({ ...templateDraft, body: event.target.value })} placeholder="Escribe el mensaje aprobado que iniciará la conversación." /></label>{variables.map((variable) => <label key={variable}>Ejemplo para {`{{${variable}}}`}<input value={templateDraft.examples[variable] || ""} onChange={(event) => setTemplateDraft({ ...templateDraft, examples: { ...templateDraft.examples, [variable]: event.target.value } })} /></label>)}<label>Texto del botón<input maxLength="25" value={templateDraft.buttonText} onChange={(event) => setTemplateDraft({ ...templateDraft, buttonText: event.target.value })} /></label><label>Pie opcional<input maxLength="60" value={templateDraft.footer} onChange={(event) => setTemplateDraft({ ...templateDraft, footer: event.target.value })} /></label></div>{error && <div className="op-error">{error}</div>}{templateResult ? <div className="flow-template-success"><CheckCircle weight="fill" /><div><b>Plantilla enviada a revisión</b><span>{templateResult.name} · {templateResult.status}</span></div><button onClick={() => startTemplate()}>Crear otra plantilla</button></div> : <div className="op-form-actions"><button onClick={() => setMode("catalog")}>Cancelar</button><button className="primary" onClick={saveTemplate} disabled={operation === "saving-template"}>{operation === "saving-template" ? <CircleNotch className="spin" /> : <PaperPlaneTilt />} Enviar a revisión de Meta</button></div>}</section><aside className="flow-message-preview"><span>VISTA PREVIA</span><div><p>{templateDraft.body || "El mensaje aparecerá aquí exactamente con sus saltos de línea."}</p>{templateDraft.footer && <small>{templateDraft.footer}</small>}<button>{templateDraft.buttonText || "Abrir formulario"}</button></div></aside></div>
    </Page>;
  }

  return <Page>
    <Header eyebrow="WHATSAPP BUSINESS" title="Flows y plantillas" desc="Crea formularios de WhatsApp y administra las plantillas aprobables que los inician." action={loadCatalog} label="Actualizar" />
    <div className="info flow-info"><FlowArrow /> <span>Un Flow no se envía por sí solo: una plantilla aprobada con botón de Flow lo inicia. Selecciona esa plantilla al crear una campaña.</span></div>
    <div className="flow-catalog-actions"><button className="primary" disabled={!canManageFlows} onClick={startFlow}><Plus /> Nuevo Flow</button><button disabled={!canManageTemplates} onClick={() => startTemplate()}><NotePencil /> Nueva plantilla</button>{(!canManageFlows || !canManageTemplates) && <small>Las acciones disponibles dependen de los permisos modulares de tu perfil.</small>}</div>
    {status === "loading" && <div className="flow-loading"><CircleNotch className="spin" /> Consultando Flows publicados de Meta…</div>}
    {status === "error" && <div className="auth-error">No fue posible cargar los Flows de Meta. Actualiza la página e inténtalo nuevamente.</div>}
    {status === "ready" && <Table heads={["Flow", "Identificador", "Estado", "Plantillas que lo inician", "Actualización", "Acción"]}>
      {flows.map((flow) => {
        const attached = templates.filter((template) => template.flow_ids?.includes(flow.id));
        return <tr key={flow.id}><td><b>{flow.name || "Sin nombre"}</b><small>WhatsApp Flow</small></td><td>{flow.id}</td><td><Pill tone={flow.published ? "green" : "amber"}>{flow.status}</Pill></td><td>{attached.length ? attached.map((template) => <Pill key={template.id} tone="blue">{template.name}</Pill>) : <small>Sin plantilla vinculada</small>}</td><td>{flow.updated || "—"}</td><td>{flow.published && canManageTemplates ? <button className="table-action" onClick={() => startTemplate(flow)}><Plus /> Crear plantilla</button> : <small>{flow.published ? "Solo lectura" : "Publica el Flow para vincular plantillas"}</small>}</td></tr>;
      })}
    </Table>}
    {status === "ready" && !!templates.length && <section className="flow-template-catalog"><header><div><h2>Plantillas de Flow</h2><p>Estados actuales del proceso de aprobación de Meta.</p></div><b>{templates.length}</b></header><div>{templates.filter((template) => template.flow_ids?.length).map((template) => <article key={template.id}><div><b>{template.name}</b><small>{template.language} · {template.category}</small></div><Pill tone={template.status_code === "REJECTED" ? "red" : template.status_code === "PENDING" ? "amber" : "green"}>{template.status}</Pill></article>)}</div></section>}
    {status === "ready" && !flows.length && <div className="flow-loading">No se encontraron Flows en la cuenta de WhatsApp.</div>}
  </Page>;
}
function Responses({ initialCampaignId = "", clearInitialCampaign }) {
  const [campaignItems, setCampaignItems] = useState([]);
  const [campaignId, setCampaignId] = useState("");
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("loading");
  const [search, setSearch] = useState("");
  const [exportState, setExportState] = useState("idle");
  const [exportError, setExportError] = useState("");
  const loadResponses = (selectedId) => {
    if (!selectedId) {
      setRows([]);
      setStatus("ready");
      return Promise.resolve();
    }
    setStatus("loading");
    return listCampaignResponses(selectedId)
      .then((result) => {
        setRows(result?.items || []);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  };
  const loadCampaigns = () => {
    setStatus("loading");
    return listCampaignResponses("")
      .then((campaignResult) => {
        const nextCampaigns = campaignResult?.campaigns || [];
        setCampaignItems(nextCampaigns);
        const preferredId = initialCampaignId || campaignId;
        const selectedId = nextCampaigns.some((item) => item.id === preferredId) ? preferredId : (nextCampaigns[0]?.id || "");
        setCampaignId(selectedId);
        if (initialCampaignId && selectedId === initialCampaignId) clearInitialCampaign?.();
        return loadResponses(selectedId);
      })
      .catch(() => setStatus("error"));
  };
  useEffect(() => {
    loadCampaigns();
  }, [initialCampaignId]);
  const selectedCampaign = campaignItems.find((item) => item.id === campaignId);
  const selectedFlows = (selectedCampaign?.flow_ids || []).map((id, index) => ({ id, name: selectedCampaign?.flow_names?.[index] || id }));
  const visibleRows = rows.filter((row) => `${row.customer_name || ""} ${row.phone || ""} ${row.answer_summary || ""}`.toLowerCase().includes(search.toLowerCase()));
  const responseMatrix = useMemo(() => flowResponseMatrix(visibleRows), [visibleRows]);
  const responseColumns = [
    { key: "customer", header: "Cliente", width: 28 }, { key: "phone", header: "Teléfono", width: 18, type: "text" },
    { key: "flow", header: "Formulario / Flow", width: 26 },
    ...responseMatrix.questions.map((question, index) => ({ key: `answer_${index}`, header: question.label, width: 24 })),
    { key: "date", header: "Fecha", width: 22, type: "date" },
  ];
  const responseExportRows = responseMatrix.records.map(({ row, answers }) => ({
    customer: row.customer_name || "Cliente del canal", phone: row.phone || "",
    flow: row.form_name || selectedCampaign?.template_name || "Formulario del canal",
    ...Object.fromEntries(responseMatrix.questions.map((question, index) => [`answer_${index}`, answers[question.field] || "—"])),
    date: row.created_at ? new Date(Number(row.created_at) * 1000) : "",
  }));
  async function exportResponses(format) {
    if (!selectedCampaign || !responseExportRows.length) return;
    setExportState(format); setExportError("");
    const report = {
      filename: `${BRAND.name}-respuestas-${selectedCampaign.name}`,
      title: `Resultados · ${selectedCampaign.name}`,
      subtitle: `${selectedCampaign.template_name || "WhatsApp Flow"}${search ? " · Resultados filtrados" : ""}`,
      metrics: [
        { label: "Destinatarios", value: selectedCampaign.recipient_count || 0 },
        { label: "Entregados", value: selectedCampaign.delivered_count || 0 },
        { label: "Formularios", value: responseExportRows.length },
      ],
    };
    try {
      if (format === "excel") await exportExcelReport({ ...report, sheets: [{ name: "Respuestas", columns: responseColumns, rows: responseExportRows }] });
      else await exportPdfReport({ ...report, sections: [{ title: "Preguntas y respuestas", columns: responseColumns, rows: responseExportRows }] });
    } catch { setExportError("No fue posible generar el archivo. Inténtalo nuevamente."); }
    finally { setExportState("idle"); }
  }
  return (
    <Page>
      <Header
        eyebrow="ANALÍTICA"
        title="Respuestas por campaña"
        desc="Consulta las respuestas de los formularios interactivos según la campaña que los envió."
        action={loadCampaigns}
        label="Actualizar"
      />
      <section className="response-controls">
        <label>Campaña
          <select value={campaignId} onChange={(event) => { setCampaignId(event.target.value); loadResponses(event.target.value); }}>
            {!campaignItems.length && <option value="">No hay campañas enviadas</option>}
            {campaignItems.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name} · {campaign.template_name || "sin plantilla"}</option>)}
          </select>
        </label>
        <div><span>Plantilla enviada</span><b>{selectedCampaign?.template_name || "—"}</b></div>
        <div><span>Flow asociado</span><b>{!selectedCampaign ? "—" : selectedFlows.length ? selectedFlows.map((flow) => flow.name).join(", ") : "Esta campaña no incluyó un Flow"}</b></div>
      </section>
      <div className="metrics">
        <Metric label="Destinatarios" value={selectedCampaign?.recipient_count || 0} note="Números incluidos en la campaña" />
        <Metric label="Entregados" value={selectedCampaign?.delivered_count || 0} note={`Confirmados por ${DEFAULT_CHANNEL_LABEL}`} />
        <Metric label="Formularios recibidos" value={rows.length} note="Respuestas capturadas para esta campaña" />
      </div>
      <div className="response-tools"><div className="response-search"><MagnifyingGlass /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por cliente, teléfono o respuesta…" /></div><div className="response-export-actions"><button disabled={!responseExportRows.length || exportState !== "idle"} onClick={() => exportResponses("excel")}><FileXls />Descargar Excel</button><button disabled={!responseExportRows.length || exportState !== "idle"} onClick={() => exportResponses("pdf")}><FilePdf />Descargar PDF</button></div></div>
      {exportError && <div className="auth-error">{exportError}</div>}
      {status === "error" && <div className="auth-error">No fue posible cargar las respuestas después de varios intentos. Usa Actualizar datos en la barra superior.</div>}
      {status === "loading" && <div className="flow-loading"><CircleNotch className="spin" /> Consultando respuestas…</div>}
      {status === "ready" && campaignId && visibleRows.length > 0 && <div className="response-matrix"><Table
        heads={["Cliente", "Formulario / Flow", ...responseMatrix.questions.map((question) => question.label), "Fecha"]}
      >
        {responseMatrix.records.map(({ row: x, answers }) => (
          <tr key={x.id}>
            <td>
              <b>{x.customer_name || "Cliente del canal"}</b>
              <small>{x.phone}</small>
            </td>
            <td><b>{x.form_name || selectedCampaign?.template_name || "WhatsApp Flow"}</b><small>{x.flow_id || selectedFlows[0]?.id || "—"}</small></td>
            {responseMatrix.questions.map((question) => <td className="response-answer" key={`${x.id}-${question.field}`}>{answers[question.field] || "—"}</td>)}
            <td>{x.created_at ? new Date(Number(x.created_at) * 1000).toLocaleString(LOCALE) : "—"}</td>
          </tr>
        ))}
      </Table>
      </div>}
      {status === "ready" && campaignId && !visibleRows.length && <div className="flow-loading">{rows.length ? "No hay respuestas que coincidan con la búsqueda." : selectedFlows.length ? "Esta campaña todavía no ha recibido formularios completados." : "La campaña seleccionada no envió una plantilla con WhatsApp Flow."}</div>}
      {status === "ready" && !campaignId && <div className="flow-loading">Crea y envía una campaña para comenzar a recibir respuestas organizadas.</div>}
    </Page>
  );
}
function Table({ heads, children }) {
  return (
    <div className="table">
      <table>
        <thead>
          <tr>
            {heads.map((x, i) => (
              <th key={i}>{x}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
const Page = ({ children }) => <main className="module-page">{children}</main>;
function DeveloperAccess() {
  const [profiles, setProfiles] = useState([]);
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    listAccessProfiles()
      .then((data) => {
        setProfiles(data?.items || []);
        setState("ready");
      })
      .catch((requestError) => {
        setError(requestError.message);
        setState("error");
      });
  }, []);

  async function toggle(profile) {
    setState(`saving:${profile.id}`);
    setError("");
    try {
      const updated = await updateAccessProfile(profile.id, !profile.enabled);
      setProfiles((current) =>
        current.map((item) =>
          item.id === profile.id ? { ...item, enabled: updated.enabled } : item,
        ),
      );
      setState("ready");
    } catch (requestError) {
      setError(requestError.message);
      setState("error");
    }
  }

  return (
    <section className="developer-access">
      <header>
        <div>
          <span>SOLO DEVELOPER</span>
          <h2>Acceso por perfil de seguridad</h2>
          <p>Decide qué perfiles pueden abrir {BRAND.name} dentro de Connect.</p>
        </div>
        <Pill>Routing de desarrollo</Pill>
      </header>
      {state === "loading" && <p>Cargando perfiles de Amazon Connect...</p>}
      {error && <div className="auth-error">{error}</div>}
      <div className="profile-access-list">
        {profiles.map((profile) => (
          <div key={profile.id}>
            <div>
              <b>{profile.name}</b>
              <small>{profile.description || "Perfil de seguridad de Amazon Connect"}</small>
            </div>
            <label className="access-switch">
              <input
                type="checkbox"
                checked={profile.enabled}
                disabled={profile.current || state === `saving:${profile.id}`}
                onChange={() => toggle(profile)}
              />
              <span />
              {profile.current ? "Tu perfil" : profile.enabled ? "Permitido" : "Oculto"}
            </label>
          </div>
        ))}
      </div>
    </section>
  );
}

function ModuleAccess() {
  const [items, setItems] = useState([]);
  const [modules, setModules] = useState({});
  const [selected, setSelected] = useState("");
  const [state, setState] = useState("loading");
  useEffect(() => {
    listModulePermissions().then((data) => {
      setItems(data.items || []);
      setModules(data.modules || {});
      setSelected(data.items?.[0]?.id || "");
      setState("ready");
    }).catch(() => setState("error"));
  }, []);
  const profile = items.find((item) => item.id === selected);
  const grants = profile?.grants || {};
  const actionLabels = { view: "Ver", create: "Crear / preparar", import: "Importar archivo", send: "Enviar", delete: "Borrar", manage: "Administrar" };
  async function toggle(module, action) {
    if (!profile) return;
    const next = { ...grants, [module]: { ...(grants[module] || {}), [action]: !grants[module]?.[action] } };
    setState("saving");
    try {
      const saved = await updateModulePermissions(profile.id, next);
      setItems((current) => current.map((item) => item.id === profile.id ? { ...item, grants: saved.grants } : item));
      setState("ready");
    } catch { setState("error"); }
  }
  return (
    <section className="developer-access module-access">
      <header><div><span>SOLO DEVELOPER</span><h2>Permisos por módulo</h2><p>Define qué puede ver o hacer cada security profile dentro de la aplicación. El routing de Developer conserva acceso total para administrar esta matriz.</p></div></header>
      {state === "loading" ? <p>Cargando permisos...</p> : <>
        <label className="profile-picker">Perfil de seguridad
          <select value={selected} onChange={(event) => setSelected(event.target.value)}>{items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        </label>
        <div className="module-grid">{Object.entries(modules).map(([module, actions]) => <article key={module}><b>{NAV.find(([id]) => id === module)?.[1] || module}</b>{actions.map((action) => <label key={action}><input type="checkbox" checked={Boolean(grants[module]?.[action])} disabled={state === "saving"} onChange={() => toggle(module, action)} /> {actionLabels[action] || action}</label>)}</article>)}</div>
        {state === "error" && <small className="auth-error">No se pudo actualizar el permiso.</small>}
      </>}
    </section>
  );
}

function Settings({ context }) {
  const { mode, agent, session } = context;
  return (
    <Page>
      <Header
        eyebrow="ADMINISTRACIÓN"
        title="Configuración"
        desc="Estado de la integración, seguridad y comportamiento de los canales."
      />
      <div className="settings">
        {[
          [
            ShieldCheck,
            "Seguridad y acceso",
            [
              `Credenciales ${RUNTIME.providerName}: Secrets Manager`,
              "Identidad: sesión activa de Connect",
              "Segundo login: deshabilitado",
              "Auditoría: CloudWatch activa",
            ],
          ],
          [
            DeviceMobile,
            DEFAULT_CHANNEL_LABEL,
            [
              "Webhook v2: listo",
              "Multimedia: habilitada",
              "Transcripción: Amazon Transcribe",
            ],
          ],
          [
            FlowArrow,
            "Amazon Connect",
            [
              `Aplicación 3P: ${mode === "connect" ? "conectada" : "demostración"}`,
              `Routing: ${mode === "connect" ? "gestionado por Connect" : "vista local"}`,
              "Contacto: lectura automática",
              "Adjuntos: cifrados",
            ],
          ],
        ].map(([Icon, title, rows]) => (
          <article key={title}>
            <header>
              <Icon weight="duotone" />
              <h3>{title}</h3>
            </header>
            {rows.map((x) => (
              <div key={x}>
                {x}
                <CheckCircle weight="fill" />
              </div>
            ))}
          </article>
        ))}
      </div>
      {session?.role === "developer" && <DeveloperAccess />}
      {session?.role === "developer" && <ModuleAccess />}
    </Page>
  );
}
export function App({ context: ctx }) {
  const [active, setActive] = useState("dashboard");
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [campaignSegmentId, setCampaignSegmentId] = useState("");
  const [responseCampaignId, setResponseCampaignId] = useState("");
  function refresh() {
    setRefreshing(true);
    setRefreshVersion((value) => value + 1);
    window.setTimeout(() => setRefreshing(false), 700);
  }
  const pages = {
    dashboard: <Dashboard refreshVersion={refreshVersion} setActive={setActive} session={ctx.session} />,
    segments: <Segments refreshVersion={refreshVersion} permissions={ctx.session?.module_permissions?.segments} canCreateCampaign={ctx.session?.module_permissions?.campaigns?.create !== false} onCreateCampaign={(segmentId) => { setCampaignSegmentId(segmentId); setActive("campaigns"); }} />,
    quotes: (
      <Quotes contact={ctx.contact} agent={ctx.agent} permissions={ctx.session?.module_permissions?.quotes} />
    ),
    templates: <Templates />,
    campaigns: <OperationsCampaigns refreshVersion={refreshVersion} permissions={ctx.session?.module_permissions?.campaigns} modulePermissions={ctx.session?.module_permissions} initialSegmentId={campaignSegmentId} clearInitialSegment={() => setCampaignSegmentId("")} onViewResults={(campaignId) => { setResponseCampaignId(campaignId); setActive("responses"); }} />,
    surveys: <Survey permissions={ctx.session?.module_permissions?.surveys} templatePermissions={ctx.session?.module_permissions?.templates} />,
    responses: <Responses initialCampaignId={responseCampaignId} clearInitialCampaign={() => setResponseCampaignId("")} />,
    trash: ctx.session?.role === "developer" ? <CampaignTrash refreshVersion={refreshVersion} /> : <Dashboard refreshVersion={refreshVersion} setActive={setActive} session={ctx.session} />,
    settings: <Settings context={ctx} />,
  };
  return (
    <div className="app">
      <Sidebar active={active} setActive={setActive} mode={ctx.mode} session={ctx.session} />
      <div className="main">
        <Topbar agent={ctx.agent} mode={ctx.mode} session={ctx.session} refreshing={refreshing} onRefresh={refresh} />
        <div key={`${active}-${refreshVersion}`}>{pages[active]}</div>
      </div>
    </div>
  );
}
