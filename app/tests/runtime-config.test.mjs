import assert from "node:assert/strict";
import test from "node:test";
import { getBrand, getRuntimeConfig } from "../src/runtimeConfig.js";

test("runtime configuration is generic and safe without a browser global", () => {
  const originalWindow = globalThis.window;
  try {
    delete globalThis.window;
    const config = getRuntimeConfig();
    assert.equal(config.apiBaseUrl, "");
    assert.equal(config.businessName, "Centro de comunicaciones");
    assert.equal(config.defaultChannel, "social");
    assert.equal(config.legacyChannelLabel, "WhatsApp");
    assert.deepEqual(config.supportedChannels, ["whatsapp", "instagram", "messenger"]);
  } finally {
    globalThis.window = originalWindow;
  }
});

test("runtime brand and deployment values come from the canonical configuration object", () => {
  const originalWindow = globalThis.window;
  try {
    globalThis.window = {
      __SOCIAL_HUB_CONFIG__: {
        apiBaseUrl: "https://api.example.test",
        businessName: "Empresa Ejemplo",
        businessTagline: "Atención social",
        brandLogoUrl: "/assets/example.svg",
        logoIncludesName: false,
        locale: "es-MX",
      },
    };
    assert.equal(getRuntimeConfig().apiBaseUrl, "https://api.example.test");
    assert.deepEqual(getBrand(), {
      name: "Empresa Ejemplo",
      tagline: "Atención social",
      logoUrl: "/assets/example.svg",
      logoIncludesName: false,
    });
  } finally {
    globalThis.window = originalWindow;
  }
});
