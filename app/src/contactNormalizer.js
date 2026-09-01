import { getRuntimeConfig } from "./runtimeConfig.js";

export const SOCIAL_CONTACT_ATTRIBUTES = Object.freeze([
  // Canonical, channel-neutral attributes. New integrations must write these.
  "social_channel",
  "social_provider",
  "social_business_id",
  "social_business_name",
  "social_account_id",
  "social_asset_id",
  "social_user_id",
  "social_parent_user_id",
  "social_username",
  "social_handle",
  "social_display_name",
  "social_phone",
  "social_message_id",
  "source_message_id",
  "customer_display_name",
  "customer_name",
  "nombre",
  "nombres",
  "telefono",
  "customer_phone",
  // WhatsApp and title-cased names are compatibility fallbacks only.
  "whatsapp_phone",
  "wa_user_id",
  "wa_username",
  "CustomerName",
  "customerName",
  "WhatsAppName",
  "Company",
  "company",
  "CustomerPhoneNumber",
  "whatsappPhone",
  "wa_id",
  "CustomerRole",
]);

function firstValue(attributes, keys) {
  for (const key of keys) {
    const value = String(attributes[key] || "").trim();
    if (value) return value;
  }
  return "";
}

function isLegacyWhatsAppContact(attributes) {
  return ["whatsapp_phone", "wa_user_id", "wa_username", "WhatsAppName", "whatsappPhone", "wa_id"]
    .some((key) => String(attributes[key] || "").trim());
}

export function normalizeContact(contactId, attributes = {}) {
  const runtime = getRuntimeConfig();
  const name = firstValue(attributes, [
    "social_display_name",
    "social_username",
    "social_handle",
    "customer_display_name",
    "customer_name",
    "nombre",
    "nombres",
    "CustomerName",
    "customerName",
    "WhatsAppName",
    "wa_username",
  ]);
  const channel = firstValue(attributes, ["social_channel"])
    || (isLegacyWhatsAppContact(attributes) ? runtime.legacyChannelLabel : runtime.defaultChannelLabel);
  const initialsSource = name || channel || "Social";
  return {
    contactId,
    name,
    company: firstValue(attributes, ["social_business_name", "Company", "company"]),
    role: firstValue(attributes, ["CustomerRole"]),
    phone: firstValue(attributes, [
      "social_phone",
      "customer_phone",
      "telefono",
      "whatsapp_phone",
      "CustomerPhoneNumber",
      "whatsappPhone",
      "wa_id",
    ]),
    initials: initialsSource
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "SC",
    channel,
    provider: firstValue(attributes, ["social_provider"]) || runtime.providerName,
    userId: firstValue(attributes, ["social_user_id", "wa_user_id", "wa_id"]),
    parentUserId: firstValue(attributes, ["social_parent_user_id"]),
    username: firstValue(attributes, ["social_username", "social_handle", "wa_username"]),
    businessId: firstValue(attributes, ["social_business_id", "social_account_id"]),
    assetId: firstValue(attributes, ["social_asset_id"]),
    messageId: firstValue(attributes, ["social_message_id", "source_message_id"]),
  };
}
