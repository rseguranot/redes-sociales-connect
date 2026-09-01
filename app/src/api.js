import { getRuntimeConfig } from "./runtimeConfig";

let connectSessionToken = "";
let connectSessionRefresher = null;

export function setConnectSessionToken(value) {
  connectSessionToken = value || "";
}

export function setConnectSessionRefresher(refresher) {
  connectSessionRefresher = typeof refresher === "function" ? refresher : null;
}

export async function api(path, options = {}, sessionRetried = false) {
  const base = getRuntimeConfig().apiBaseUrl;
  if (!base) return null;
  const method = String(options.method || "GET").toUpperCase();
  const attempts = method === "GET" ? 3 : 1;
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(`${base}${path}`, {
        ...options,
        headers: {
          "content-type": "application/json",
          ...(connectSessionToken
            ? { authorization: `Bearer ${connectSessionToken}` }
            : {}),
          ...(options.headers || {}),
        },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401 && path !== "/session" && !sessionRetried && connectSessionRefresher) {
          await connectSessionRefresher();
          return api(path, options, true);
        }
        const error = new Error(data.message || data.error || `Error ${response.status}`);
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      lastError = error;
      const transient = !error.status || error.status === 408 || error.status === 429 || error.status >= 500;
      if (!transient || attempt === attempts - 1) break;
      await new Promise((resolve) => globalThis.setTimeout(resolve, 350 * (attempt + 1)));
    }
  }
  throw lastError;
}

export const createConnectSession = (agent) =>
  api("/session", {
    method: "POST",
    body: JSON.stringify({
      agent_arn: agent.arn,
      connect_network_status: agent.connectionStatus,
      connect_network_timestamp: agent.connectionTimestamp,
    }),
  });

export const sendQuote = (payload) =>
  api("/send", { method: "POST", body: JSON.stringify(payload) });

export async function uploadMedia(file) {
  if (!file) throw new Error("Selecciona el archivo de la cotización.");
  const upload = await api("/upload", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, content_type: file.type || "application/pdf" }),
  });
  const response = await fetch(upload.upload_url, {
    method: "PUT",
    headers: upload.headers,
    body: file,
  });
  if (!response.ok) throw new Error("No fue posible cargar el documento de la cotización.");
  return upload.s3_key;
}
export const createCampaign = (payload) =>
  api("/campaign", { method: "POST", body: JSON.stringify(payload) });
export const listResource = (resource) =>
  api(`/${resource}`, { method: "GET" });
export const listCampaignResponses = (campaignId) =>
  api(`/responses?campaign_id=${encodeURIComponent(campaignId)}`, { method: "GET" });
export const deleteCampaign = (campaignId, confirmationName) =>
  api("/campaign-delete", { method: "POST", body: JSON.stringify({ campaign_id: campaignId, confirmation_name: confirmationName }) });
export const listCampaignTrash = () => api("/campaign-trash", { method: "GET" });
export const restoreCampaign = (campaignId) =>
  api("/campaign-restore", { method: "POST", body: JSON.stringify({ campaign_id: campaignId }) });
export const listMetaTemplates = () => api("/meta-templates", { method: "GET" });
export const listMetaFlows = () => api("/meta-flows", { method: "GET" });
export const listManagedMetaTemplates = () => api("/meta-template-management", { method: "GET" });
export const manageMetaFlow = (payload) =>
  api("/meta-flows", { method: "POST", body: JSON.stringify(payload) });
export const createMetaTemplate = (payload) =>
  api("/meta-templates", { method: "POST", body: JSON.stringify(payload) });
export const saveResource = (resource, payload) =>
  api(`/${resource}`, { method: "POST", body: JSON.stringify(payload) });
export const listSegments = () => api("/segments", { method: "GET" });
export const getSegmentContacts = (segmentId) =>
  api(`/segments?segment_id=${encodeURIComponent(segmentId)}`, { method: "GET" });
export const saveSegment = (payload) =>
  api("/segments", { method: "POST", body: JSON.stringify(payload) });
export const listAccessProfiles = () => api("/access-profiles", { method: "GET" });
export const updateAccessProfile = (securityProfileId, enabled) =>
  api("/access-profiles", {
    method: "POST",
    body: JSON.stringify({ security_profile_id: securityProfileId, enabled }),
  });
export const listModulePermissions = () => api("/module-permissions", { method: "GET" });
export const updateModulePermissions = (securityProfileId, grants) =>
  api("/module-permissions", {
    method: "POST",
    body: JSON.stringify({ security_profile_id: securityProfileId, grants }),
  });
