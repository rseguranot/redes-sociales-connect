import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { getRuntimeConfig } from "./runtimeConfig";
import { collectedLabels, historyText } from "./historyText";
import "./contactHistory.css";

export function ContactHistory({ contact }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState([]);
  const [cursor, setCursor] = useState("");
  const [lastAgent, setLastAgent] = useState(contact.lastAgent);
  const [state, setState] = useState("idle");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const date = value => new Date(Number(value) * 1000).toLocaleString(getRuntimeConfig().locale);
  async function load(more = false) {
    if (state === "loading") return;
    setState("loading");
    try {
      const data = await api(`/contact-history?contact_id=${encodeURIComponent(contact.contactId)}${more && cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, {
        headers: { "x-social-history-token": contact.historyToken }, cache: "no-store",
      });
      if (!alive.current) return;
      if (!data) throw new Error("history_unavailable");
      setEntries(previous => more ? [...previous, ...data.entries.filter(item => !previous.some(old => old.id === item.id))] : data.entries);
      setCursor(data.cursor || "");
      setLastAgent(data.last_agent?.name || contact.lastAgent);
      setState("ready");
    } catch {
      if (alive.current) setState("error");
    }
  }
  const collected = Object.entries(contact.collected || {});
  return <section className="contact-history" aria-label="Contexto del contacto activo">
    <button className="history-toggle" onClick={() => { setOpen(!open); if (!open && contact.historyToken && state === "idle") load(); }} aria-expanded={open}>
      <span><strong>Contexto e historial del contacto</strong><small>{lastAgent ? `Última respuesta humana: ${lastAgent}` : "Sin respuesta humana registrada"}</small></span>
      <span>{open ? "Ocultar" : "Ver últimos 7 días"}</span>
    </button>
    {open && <div className="history-body">
      {collected.length > 0 && <><h3>Datos recopilados</h3><p>Información declarada en la conversación; no acredita identidad.</p><dl>{collected.map(([key, value]) => <div key={key}><dt>{collectedLabels[key]}</dt><dd>{value}</dd></div>)}</dl></>}
      <h3>Conversaciones de los últimos 7 días</h3>
      <p>Más recientes primero. Se incluyen mensajes capturados desde la activación del historial. Los adjuntos originales permanecen en Connect.</p>
      {!contact.historyToken ? <p>Este contacto comenzó antes de habilitar el historial. Consulte su transcripción en Connect.</p> : <>
        <button disabled={state === "loading"} onClick={() => load()}>Actualizar historial</button>
        {state === "error" && <p role="alert">No se pudo cargar el historial. Intente actualizarlo.</p>}
        {state === "ready" && entries.length === 0 && <p>No hay mensajes registrados en este período.</p>}
        <ol>{entries.map(item => <li key={item.id} data-role={item.role}>
          <header><strong>{item.role === "SYSTEM" ? `${getRuntimeConfig().businessName} · Bot` : item.name || (item.role === "AGENT" ? "Agente" : "Cliente")}</strong><time>{date(item.timestamp)}</time></header>
          <small>Conversación {item.contact_id?.slice(0, 8)}</small>
          <div className="history-message">{historyText(item.text)}</div>
          {(item.attachments || []).map((name, index) => <p key={index}>Adjunto: {name}</p>)}
        </li>)}</ol>
        {state === "loading" && <p role="status">Cargando historial…</p>}
        {cursor && <button disabled={state === "loading"} onClick={() => load(true)}>Cargar mensajes anteriores</button>}
      </>}
    </div>}
  </section>;
}
