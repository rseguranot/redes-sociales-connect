import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("production access is gated by the active Amazon Connect session", async () => {
  const [gate, adapter, normalizer, entry] = await Promise.all([
    source("src/AuthGate.jsx"),
    source("src/connectAdapter.js"),
    source("src/contactNormalizer.js"),
    source("src/main.jsx"),
  ]);
  assert.match(entry, /ConnectSessionGate/);
  assert.doesNotMatch(adapter, /agentClient\.getNetworkConnectionStatus\(\)/);
  assert.match(adapter, /agentClient\.getARN\(\)/);
  assert.doesNotMatch(adapter, /agentClient\.getRoutingProfile\(\)/);
  assert.doesNotMatch(adapter, /contactClient\.listContacts\(\)/);
  assert.match(adapter, /runtimePromise/);
  assert.match(adapter, /contextListeners/);
  assert.match(adapter, /SOCIAL_CONTACT_ATTRIBUTES/);
  assert.match(normalizer, /"social_channel"/);
  assert.match(normalizer, /"social_display_name"/);
  assert.match(normalizer, /"social_phone"/);
  assert.match(normalizer, /"social_user_id"/);
  assert.match(normalizer, /"social_message_id"/);
  assert.match(normalizer, /"customer_display_name"/);
  assert.match(normalizer, /"customer_name"/);
  assert.match(normalizer, /"telefono"/);
  assert.match(normalizer, /"customer_phone"/);
  assert.match(normalizer, /"whatsapp_phone"/);
  assert.ok(normalizer.indexOf('"social_display_name"') < normalizer.indexOf('"customer_display_name"'));
  assert.ok(normalizer.indexOf('"social_phone"') < normalizer.indexOf('"whatsapp_phone"'));
  assert.match(normalizer, /\["social_user_id", "wa_user_id", "wa_id"\]/);
  assert.doesNotMatch(adapter, /listSecurityProfilePermissions/);
  assert.match(adapter, /onCreate: \(\) => \{\}/);
  assert.match(adapter, /provider\.onStart/);
  assert.doesNotMatch(adapter, /onCreate: async/);
  assert.match(adapter, /Abre esta aplicación desde Amazon Connect Agent Workspace/);
  assert.match(gate, /createConnectSession/);
  assert.match(gate, /scheduleRenewal/);
  assert.match(gate, /setConnectSessionRefresher/);
  assert.match(gate, /expires_in/);
  assert.match(gate, /Amazon Connect no entregó el contexto/);
  assert.match(gate, /else destroy\(\)/);
  assert.doesNotMatch(gate, /EMAIL_OTP|InitiateAuthCommand|type="email"/);
});

test("developer profile administration is routing-controlled and Cognito is absent", async () => {
  const [application, api, manifest] = await Promise.all([
    source("src/App.jsx"),
    source("src/api.js"),
    source("package.json"),
  ]);
  assert.match(application, /session\?\.role === "developer"/);
  assert.match(application, /DeveloperAccess/);
  assert.match(api, /\/access-profiles/);
  assert.match(api, /response\.status === 401/);
  assert.match(api, /connectSessionRefresher/);
  assert.doesNotMatch(manifest, /cognito/i);
});

test("the authenticated full agent name is prefilled into the customer-visible quote template", async () => {
  const application = await source("src/App.jsx");
  assert.match(application, /function quoteTemplateValues\(template, customerName, agentName\)/);
  assert.match(application, /key === "nombre_agente"[\s\S]*?String\(agentName \|\| ""\)\.trim\(\)/);
  assert.match(application, /quoteTemplateValues\([^)]*,\s*agent\.name\)/);
  assert.match(application, /agent_name: agent\.name/);
});

test("a newly created segment starts the campaign wizard at campaign type", async () => {
  const operations = await source("src/Operations.jsx");
  assert.match(operations, /setCreatedSegment\(saved\); setMode\("success"\)/);
  assert.match(operations, /Iniciar campaña/);
  assert.match(operations, /onCreateCampaign\(createdSegment\.id\)/);
  assert.match(operations, /if \(initialSegmentId\) \{ setSegmentId\(initialSegmentId\); setStep\(1\)/);
  assert.doesNotMatch(operations, /setStep\(2\); setView\("create"\)/);
});
