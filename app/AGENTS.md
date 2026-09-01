# Application workspace instructions

Run the local server and open the preview when visual verification is required. Keep all customer-specific values outside the source tree.

Build UI code in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` compatible with the Sites build. Before handoff, run `npm test` and `npm run build`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Durable product decisions

- This is an Amazon Connect third-party workspace application. It augments the active omnichannel contact and must not implement a competing conversations inbox.
- Branding, locale, API endpoint, provider name and supported channels come only from `window.__SOCIAL_HUB_CONFIG__`. Do not add customer aliases, account IDs, ARNs, phone numbers, personal names or production endpoints to source files.
- New contact integrations write channel-neutral `social_*` Amazon Connect attributes. The client reads those first; WhatsApp attribute names remain read-only compatibility fallbacks for previously created contacts.
- The operational sequence is Dashboard, Segmentos, Campañas and Respuestas. Provider-specific tools such as message templates, WhatsApp Flows and quotations are supporting modules.
- A campaign is created on a full-width guided page. It starts from a saved customer segment and then selects a campaign type and an approved provider template.
- After saving a segment, show a completion state with an `Iniciar campaña` action that preserves the new segment as the selected audience.
- Response analytics translate technical field and option identifiers into readable labels while preserving the original stored response data.
- Reports and filenames use the runtime business brand and locale. Never hard-code a customer name in XLSX/PDF metadata, headers or footers.
- Customer segments can be created manually or imported from CSV/XLSX. Imports detect common delimiters and map names, phones, identification and email without inventing records.
- Dashboard metrics and empty states use backend data. Never seed visible contacts, campaigns, responses or performance values.
- Authorization is modular by Amazon Connect security profile and business action. Enforce the same grants in the UI and API. Developer access is determined by server-side configuration, never by a hard-coded user or routing profile.
- Campaign deletion is soft and recoverable. Only authorized developer profiles can open the recycle bin and restore a campaign.
- Production authentication trusts an active Amazon Connect Agent Workspace context, validates the agent and authorization server-side, and blocks direct top-level access. Never render a second login or embed provider credentials in the browser.
- Saving a provider Flow creates or updates a draft first. Publishing remains a separate, explicitly confirmed action. Do not invent an approved or published status.
