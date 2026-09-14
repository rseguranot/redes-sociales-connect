import assert from "node:assert/strict";
import test from "node:test";
import { normalizeContact, SOCIAL_CONTACT_ATTRIBUTES } from "../src/contactNormalizer.js";
import { historyText } from "../src/historyText.js";

test("history capability and declared identity never replace Meta identity", () => {
  const contact = normalizeContact("qa", {social_display_name:"Meta QA", social_collected_name:"Declarado QA", social_collected_phone:"not-verified", social_history_token:"qa-token", social_input_source:"voice", social_reply_preference:"audio", social_audio_url:"https://media.example/audio", social_audio_filename:"voice.ogg"});
  assert.equal(contact.name, "Meta QA");
  assert.equal(contact.phone, "");
  assert.equal(contact.historyToken, "qa-token");
  assert.equal(contact.collected.social_collected_name, "Declarado QA");
  assert.equal(contact.collected.social_history_token, undefined);
  assert.equal(contact.inputSource, "voice");
  assert.equal(contact.replyPreference, "audio");
  assert.equal(contact.audioFilename, "voice.ogg");
});

test("history presents DSL without executing HTML", () => {
  assert.equal(historyText("[plantilla]\n[informacion]\nHola\n[opcion] Sí"), "Hola\n• Sí");
  assert.equal(historyText("<script>evil</script>"), "<script>evil</script>");
});

test("channel-neutral contact attributes win over generic and WhatsApp fallbacks", () => {
  const originalWindow = globalThis.window;
  try {
    globalThis.window = {
      __SOCIAL_HUB_CONFIG__: {
        defaultChannelLabel: "Canal social",
        providerName: "Proveedor configurado",
      },
    };
    const contact = normalizeContact("contact-example", {
      social_channel: "Instagram",
      social_provider: "Meta",
      social_display_name: "Perfil social",
      customer_display_name: "Nombre genérico anterior",
      WhatsAppName: "Nombre WhatsApp anterior",
      social_phone: "+12025550101",
      customer_phone: "+12025550102",
      whatsapp_phone: "+12025550103",
      social_user_id: "social-user",
      wa_user_id: "whatsapp-user",
      social_message_id: "social-message",
      source_message_id: "source-message",
    });
    assert.equal(contact.name, "Perfil social");
    assert.equal(contact.phone, "+12025550101");
    assert.equal(contact.channel, "Instagram");
    assert.equal(contact.provider, "Meta");
    assert.equal(contact.userId, "social-user");
    assert.equal(contact.messageId, "social-message");
  } finally {
    globalThis.window = originalWindow;
  }
});

test("old WhatsApp contacts remain readable without becoming the canonical schema", () => {
  const contact = normalizeContact("legacy-contact", {
    WhatsAppName: "Perfil anterior",
    whatsapp_phone: "+12025550104",
    wa_user_id: "legacy-user",
  });
  assert.equal(contact.name, "Perfil anterior");
  assert.equal(contact.phone, "+12025550104");
  assert.equal(contact.channel, "WhatsApp");
  assert.equal(contact.userId, "legacy-user");
  assert.ok(SOCIAL_CONTACT_ATTRIBUTES.indexOf("social_user_id") < SOCIAL_CONTACT_ATTRIBUTES.indexOf("wa_user_id"));
});
