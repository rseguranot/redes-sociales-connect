import { useEffect, useRef, useState } from "react";
import { CircleNotch, ShieldCheck } from "@phosphor-icons/react";
import { createConnectSession, setConnectSessionRefresher, setConnectSessionToken } from "./api";
import { initializeConnect } from "./connectAdapter";
import { getBrand } from "./runtimeConfig";

export function ConnectSessionGate({ children }) {
  const brand = getBrand();
  const [context, setContext] = useState(null);
  const [error, setError] = useState("");
  const sessionRef = useRef(null);
  const connectContextRef = useRef(null);
  const renewalTimerRef = useRef(null);

  useEffect(() => {
    let cleanup = () => {};
    let active = true;
    let renewalPromise = null;
    const scheduleRenewal = (session) => {
      window.clearTimeout(renewalTimerRef.current);
      const delay = Math.max(60, Number(session?.expires_in || 900) - 120) * 1000;
      renewalTimerRef.current = window.setTimeout(() => renewSession().catch(() => {}), delay);
    };
    const renewSession = async () => {
      if (renewalPromise) return renewalPromise;
      const connectContext = connectContextRef.current;
      if (!active || !connectContext?.agent) throw new Error("connect_context_unavailable");
      renewalPromise = createConnectSession(connectContext.agent)
        .then((session) => {
          if (!active) return session;
          sessionRef.current = session;
          setConnectSessionToken(session.session_token);
          setContext({ ...connectContext, session });
          scheduleRenewal(session);
          return session;
        })
        .finally(() => { renewalPromise = null; });
      return renewalPromise;
    };
    setConnectSessionRefresher(renewSession);
    const timeout = window.setTimeout(() => {
      if (!active || sessionRef.current) return;
      setError(
        "Amazon Connect no entregó el contexto de la aplicación. Cierra esta pestaña y ábrela de nuevo desde Agent Workspace.",
      );
    }, 15000);
    initializeConnect(async (connectContext) => {
      if (!active) return;
      connectContextRef.current = connectContext;
      window.clearTimeout(timeout);
      if (connectContext.mode === "demo") {
        setContext({
          ...connectContext,
          session: { role: "developer", role_label: "Developer" },
        });
        return;
      }
      if (connectContext.mode !== "connect") {
        setConnectSessionToken("");
        sessionRef.current = null;
        setContext(null);
        setError(
          connectContext.error ||
            "Abre esta aplicación desde una sesión activa de Amazon Connect.",
        );
        return;
      }
      try {
        if (!sessionRef.current || sessionRef.current.agent_arn !== connectContext.agent.arn) {
          await renewSession();
        } else {
          setContext({ ...connectContext, session: sessionRef.current });
        }
        setError("");
      } catch (sessionError) {
        setConnectSessionToken("");
        sessionRef.current = null;
        setContext(null);
        setError(
          sessionError.message ||
            "Tu usuario de Connect no tiene permiso para abrir esta aplicación.",
        );
      }
    })
      .then((destroy) => {
        if (active) cleanup = destroy;
        else destroy();
      })
      .catch(() => setError("No fue posible validar la sesión de Amazon Connect."));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      window.clearTimeout(renewalTimerRef.current);
      setConnectSessionRefresher(null);
      setConnectSessionToken("");
      cleanup();
    };
  }, []);

  if (context) return children(context);

  return (
    <main className="auth">
      <section>
        <div className="auth-brand">
          <img src={brand.logoUrl} alt={`Logo de ${brand.name}`} />
          <div>
            {!brand.logoIncludesName && <b>{brand.name.toUpperCase()}</b>}
            <span>{brand.tagline}</span>
          </div>
        </div>
        {error ? (
          <ShieldCheck className="auth-shield denied" weight="duotone" />
        ) : (
          <CircleNotch className="auth-shield spin" />
        )}
        <h1>{error ? "Acceso administrado por Connect" : "Validando sesión de Connect"}</h1>
        <p>{error || "Comprobando identidad, conexión y permisos del agente."}</p>
        <small>No se requiere correo, código ni contraseña adicional.</small>
      </section>
    </main>
  );
}
