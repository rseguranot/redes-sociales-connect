import { AmazonConnectApp } from "@amazon-connect/app";
import { AgentClient, ContactClient } from "@amazon-connect/contact";
import { normalizeContact, SOCIAL_CONTACT_ATTRIBUTES } from "./contactNormalizer.js";

const ATTRIBUTES = SOCIAL_CONTACT_ATTRIBUTES;

const contextListeners = new Set();
let latestContext = null;
let runtimePromise = null;

function publishContext(context) {
  latestContext = context;
  for (const listener of contextListeners) listener(context);
}

async function startConnectRuntime() {
  let contactClient;
  let connectedHandler;
  let started = false;
  try {
    const { provider } = AmazonConnectApp.init({
      // Do not call Agent or Contact APIs from onCreate. Agent Workspace waits
      // for this lifecycle callback to finish before starting the app, while
      // those APIs wait for the started workspace channel.
      onCreate: () => {},
      onDestroy: async () => {
        if (contactClient && connectedHandler)
          contactClient.offConnected(connectedHandler);
      },
    });
    provider.onStart(async ({ context }) => {
      if (started) return;
      started = true;
      try {
        contactClient = new ContactClient(provider);
        const agentClient = new AgentClient(provider);
        // The ARN is the only identity datum required by the backend. Avoid
        // optional Agent SDK calls that may not be authorized for every
        // Connect security profile.
        const arn = await agentClient.getARN();
        const name = await agentClient.getName().catch(() => "Agente Connect");
        const agent = {
          name,
          arn,
          connectionStatus: "connected",
          connectionTimestamp: Date.now(),
          availabilityState: "",
        };
        const publishContact = async (contactId) => {
          if (!contactId)
            return publishContext({ mode: "connect", contact: null, agent });
          const attributes = await contactClient
            .getAttributes(contactId, ATTRIBUTES)
            .catch(() => ({}));
          publishContext({
            mode: "connect",
            contact: normalizeContact(contactId, attributes),
            agent,
          });
        };
        if (context.scope?.type === "contact")
          await publishContact(context.scope.contactId);
        else await publishContact();
        connectedHandler = ({ contactId }) => publishContact(contactId);
        contactClient.onConnected(connectedHandler);
      } catch (error) {
        console.warn("Amazon Connect context unavailable.", error);
        publishContext({
          mode: "blocked",
          error: "No fue posible obtener la sesión activa de Amazon Connect.",
        });
      }
    });
  } catch (error) {
    console.warn("Amazon Connect context unavailable.", error);
    publishContext({
      mode: "blocked",
      error: "No fue posible obtener la sesión activa de Amazon Connect.",
    });
  }
}

export async function initializeConnect(onContext) {
  if (window.self === window.top) {
    onContext(
      import.meta.env.DEV
        ? {
            mode: "demo",
            contact: null,
            agent: { name: "Vista local", arn: "demo-agent" },
          }
        : {
            mode: "blocked",
            error: "Abre esta aplicación desde Amazon Connect Agent Workspace.",
          },
    );
    return () => {};
  }

  contextListeners.add(onContext);
  if (latestContext) onContext(latestContext);
  if (!runtimePromise) runtimePromise = startConnectRuntime();
  await runtimePromise;
  return () => contextListeners.delete(onContext);
}
