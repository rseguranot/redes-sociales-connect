const DEFAULT_RUNTIME_CONFIG = Object.freeze({
  region: "",
  apiBaseUrl: "",
  businessName: "Centro de comunicaciones",
  businessTagline: "Atención omnicanal",
  brandLogoUrl: "/assets/brand-logo.svg",
  logoIncludesName: true,
  locale: "es",
  defaultTemplateLanguage: "es",
  defaultChannel: "social",
  defaultChannelLabel: "Canal social",
  legacyChannelLabel: "WhatsApp",
  providerName: "Meta",
  supportedChannels: ["whatsapp", "instagram", "messenger"],
});

export function getRuntimeConfig() {
  const scope = typeof globalThis.window === "object" ? globalThis.window : globalThis;
  const configured = scope?.__SOCIAL_HUB_CONFIG__;
  return configured && typeof configured === "object"
    ? { ...DEFAULT_RUNTIME_CONFIG, ...configured }
    : { ...DEFAULT_RUNTIME_CONFIG };
}

export function getBrand() {
  const cfg = getRuntimeConfig();
  return {
    name: cfg.businessName || "Centro de comunicaciones",
    tagline: cfg.businessTagline || "Atención omnicanal",
    logoUrl: cfg.brandLogoUrl || "/assets/brand-logo.svg",
    logoIncludesName: Boolean(cfg.logoIncludesName),
  };
}
