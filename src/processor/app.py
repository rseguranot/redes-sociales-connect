"""Asynchronous WhatsApp, Amazon Connect, media and campaign processor."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import secrets as secure_random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import unicodedata
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError


ddb = boto3.resource("dynamodb").Table(os.environ["STATE_TABLE"])
connect = boto3.client("connect")
participant = boto3.client("connectparticipant")
s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
secrets = boto3.client("secretsmanager")
textract = boto3.client("textract")
transcribe = boto3.client("transcribe")
sqs = boto3.client("sqs")
bedrock = boto3.client("bedrock-runtime", config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
_secret_cache: tuple[float, dict[str, str]] | None = None
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


_DSL_TAG = re.compile(r"^\s*\[([^\]]+)]\s*(.*)$")
_CONNECT_ATTRIBUTE = re.compile(
    r"\$\.Attributes(?:\.([A-Za-z0-9_-]+)|\.\['([^']+)'\])"
)
_FRIENDLY_VARIABLE = re.compile(r"(?<!\{)\{([A-Za-z0-9_-]+)}(?!})")


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _development_contact_flow(phone: str) -> str:
    """Return the isolated Connect flow for an explicitly allow-listed phone."""
    flow_id = os.environ.get("DEVELOPMENT_CONTACT_FLOW_ID", "").strip()
    if not flow_id:
        return ""
    normalized_phone = re.sub(r"\D", "", phone)
    allowed = {
        re.sub(r"\D", "", value)
        for value in os.environ.get("DEVELOPMENT_PHONE_NUMBERS", "").split(",")
        if value.strip()
    }
    return flow_id if normalized_phone and normalized_phone in allowed else ""


def _normalized_phone(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _template_dsl_enabled(phone: str) -> bool:
    """Return whether plain-text templates are enabled for this recipient."""
    mode = os.environ.get("TEMPLATE_DSL_MODE", "disabled").strip().lower()
    if mode == "enabled":
        return True
    if mode != "allowlist":
        return False
    allowed = {
        _normalized_phone(value)
        for value in os.environ.get(
            "TEMPLATE_DSL_PHONE_NUMBERS",
            os.environ.get("DEVELOPMENT_PHONE_NUMBERS", ""),
        ).split(",")
        if _normalized_phone(value)
    }
    return _normalized_phone(phone) in allowed


def _normalized_dsl_tag(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    normalized = re.sub(r"\s+", " ", normalized)
    if re.fullmatch(r"opcion(?:\s+\d+)?", normalized):
        return "opcion"
    aliases = {
        "texto": "informacion",
        "mensaje": "informacion",
        "footer": "pie",
    }
    return aliases.get(normalized, normalized)


def _is_template_dsl(text: str) -> bool:
    first = next((line for line in str(text or "").splitlines() if line.strip()), "")
    match = _DSL_TAG.match(first)
    return bool(match and _normalized_dsl_tag(match.group(1)) == "plantilla")


def _parse_template_dsl(text: str) -> dict[str, Any]:
    """Parse the readable, line-oriented template syntax used in Connect."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_index is None or not _is_template_dsl("\n".join(lines[first_index:])):
        raise ValueError("template_dsl_marker_required")

    result: dict[str, Any] = {
        "name": "",
        "title": "",
        "information": "",
        "question": "",
        "footer": "",
        "options": [],
    }
    marker = _DSL_TAG.match(lines[first_index])
    if marker and marker.group(2).strip():
        result["name"] = marker.group(2).strip()

    current: str | None = None
    buffer: list[str] = []
    supported = {"nombre", "titulo", "informacion", "pregunta", "opcion", "pie"}

    def flush() -> None:
        nonlocal buffer
        if current is None:
            buffer = []
            return
        value = "\n".join(buffer).strip()
        if current == "opcion":
            if value:
                result["options"].append(value)
        elif value:
            key = {
                "nombre": "name",
                "titulo": "title",
                "informacion": "information",
                "pregunta": "question",
                "pie": "footer",
            }[current]
            result[key] = f"{result[key]}\n{value}" if result[key] else value
        buffer = []

    for line in lines[first_index + 1:]:
        match = _DSL_TAG.match(line)
        if match:
            flush()
            tag = _normalized_dsl_tag(match.group(1))
            if tag == "plantilla":
                raise ValueError("template_dsl_duplicate_marker")
            if tag not in supported:
                raise ValueError(f"template_dsl_unknown_tag:{tag}")
            current = tag
            buffer = [match.group(2)] if match.group(2) else []
        elif current is not None:
            buffer.append(line)
        elif line.strip():
            raise ValueError("template_dsl_text_without_section")
    flush()

    if not result["information"] and not result["question"]:
        raise ValueError("template_dsl_body_required")
    if len(result["options"]) > 10:
        raise ValueError("template_dsl_maximum_10_options")
    return result


def _template_values(row: dict[str, Any]) -> dict[str, str]:
    name = str(row.get("customer_name") or row.get("name") or "").strip()
    # A BSUID/user id routes the conversation but is not a telephone number.
    # Leave phone variables empty when Meta did not provide a real phone.
    phone = str(row.get("phone") or "").strip()
    return {
        "nombre": name,
        "nombres": name,
        "customer_name": name,
        "customer_display_name": name,
        "telefono": phone,
        "customer_phone": phone,
        "whatsapp_phone": phone,
    }


def _resolve_template_variables(value: str, row: dict[str, Any]) -> str:
    values = _template_values(row)

    def connect_replacement(match: re.Match[str]) -> str:
        key = str(match.group(1) or match.group(2) or "")
        return values.get(key, match.group(0))

    def friendly_replacement(match: re.Match[str]) -> str:
        key = str(match.group(1) or "")
        return values.get(key, match.group(0))

    resolved = _CONNECT_ATTRIBUTE.sub(connect_replacement, str(value or ""))
    return _FRIENDLY_VARIABLE.sub(friendly_replacement, resolved)


def _short_display_label(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(compact) <= limit:
        return compact
    candidate = compact[: limit - 1].rstrip()
    if " " in candidate:
        word_boundary = candidate.rsplit(" ", 1)[0].rstrip()
        if len(word_boundary) >= max(8, limit // 2):
            candidate = word_boundary
    return candidate + "…"


def _single_whatsapp_emphasis(value: str, marker: str) -> str:
    """Wrap text once with a WhatsApp emphasis marker."""
    normalized = str(value or "").strip()
    while len(normalized) >= 2 and normalized.startswith(marker) and normalized.endswith(marker):
        normalized = normalized[len(marker):-len(marker)].strip()
    return f"{marker}{normalized}{marker}" if normalized else ""


def _option_identifier(label: str, index: int) -> str:
    normalized = unicodedata.normalize("NFKD", label.lower())
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")[:220] or "opcion"
    return f"dsl_{index}_{slug}"


def _template_dsl_payload(text: str, row: dict[str, Any]) -> tuple[dict[str, Any], str]:
    parsed = _parse_template_dsl(text)
    for key in ("name", "title", "information", "question", "footer"):
        parsed[key] = _resolve_template_variables(parsed[key], row)
    parsed["options"] = [_resolve_template_variables(option, row) for option in parsed["options"]]

    rendered_question = _single_whatsapp_emphasis(parsed["question"], "*")
    body = "\n\n".join(value for value in (parsed["information"], rendered_question) if value).strip()
    options = parsed["options"]
    if not options:
        rendered = "\n\n".join(value for value in (
            f"*{parsed['title']}*" if parsed["title"] else "",
            body,
            parsed["footer"],
        ) if value)
        if len(rendered) > 4096:
            raise ValueError("template_dsl_text_exceeds_4096_characters")
        return {"type": "text", "text": {"body": rendered, "preview_url": False}}, "information"

    is_list = len(options) > 3
    body_limit = 4096 if is_list else 1024
    if not body or len(body) > body_limit:
        raise ValueError(f"template_dsl_body_must_be_1_to_{body_limit}_characters")
    if parsed["title"] and len(parsed["title"]) > 60:
        raise ValueError("template_dsl_title_exceeds_60_characters")
    if parsed["footer"] and len(parsed["footer"]) > 60:
        raise ValueError("template_dsl_footer_exceeds_60_characters")

    interactive: dict[str, Any] = {
        "type": "list" if is_list else "button",
        "body": {"text": body},
    }
    if parsed["title"]:
        interactive["header"] = {"type": "text", "text": parsed["title"]}
    if parsed["footer"]:
        interactive["footer"] = {"text": parsed["footer"]}
    if is_list:
        interactive["action"] = {
            "button": "Ver opciones",
            "sections": [{
                "title": "Opciones",
                "rows": [
                    {"id": _option_identifier(option, index), "title": _short_display_label(option, 24)}
                    for index, option in enumerate(options, start=1)
                ],
            }],
        }
        return {"type": "interactive", "interactive": interactive}, "list"

    interactive["action"] = {
        "buttons": [
            {
                "type": "reply",
                "reply": {
                    "id": _option_identifier(option, index),
                    "title": _short_display_label(option, 20),
                },
            }
            for index, option in enumerate(options, start=1)
        ]
    }
    return {"type": "interactive", "interactive": interactive}, "buttons"


def _participant_display_name(identity: dict[str, str]) -> str:
    """Build an agent-visible name that preserves the WhatsApp phone number."""
    phone = str(identity.get("phone") or "").strip()
    name = str(identity.get("name") or phone or identity.get("id") or "Cliente WhatsApp").strip()
    if not phone or phone == name or phone in name:
        return name[:256]
    suffix = f" | {phone}"
    return f"{name[:max(1, 256 - len(suffix))]}{suffix}"


def _enqueue_fifo(payload: dict[str, Any], group_id: str, deduplication_id: str) -> None:
    sqs.send_message(
        QueueUrl=os.environ["CONVERSATION_QUEUE_URL"],
        MessageBody=json.dumps(payload, separators=(",", ":")),
        MessageGroupId=_stable_id(group_id),
        MessageDeduplicationId=_stable_id(deduplication_id),
    )


def _enqueue_media(payload: dict[str, Any]) -> None:
    sqs.send_message(
        QueueUrl=os.environ["MEDIA_QUEUE_URL"],
        MessageBody=json.dumps(payload, separators=(",", ":")),
    )


def _metric(name: str, value: int = 1, **dimensions: str) -> None:
    metric = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": os.environ.get("METRICS_NAMESPACE", "SocialMessaging"),
                "Dimensions": [sorted(dimensions)] if dimensions else [[]],
                "Metrics": [{"Name": name, "Unit": "Count"}],
            }],
        },
        name: value,
        **dimensions,
    }
    # EMF must be a complete JSON document on stdout. Logging it through the
    # Python logger adds a prefix and prevents CloudWatch from extracting it.
    print(json.dumps(metric, separators=(",", ":")))


def _secret() -> dict[str, str]:
    global _secret_cache
    now = time.monotonic()
    if _secret_cache and now - _secret_cache[0] < 300:
        return _secret_cache[1]
    parsed = json.loads(secrets.get_secret_value(SecretId=os.environ["WHATSAPP_SECRET_ARN"])["SecretString"])
    _secret_cache = (now, parsed)
    return parsed


def _http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None,
               headers: dict[str, str] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"Remote API returned HTTP {exc.code}: {detail}") from exc


def _identity(change: dict[str, Any], message: dict[str, Any]) -> dict[str, str]:
    contacts = change.get("contacts") or []
    contact = contacts[0] if contacts else {}
    profile = contact.get("profile") or {}
    phone = str(message.get("from") or contact.get("wa_id") or "")
    user_id = str(message.get("from_user_id") or contact.get("user_id") or "")
    parent_id = str(message.get("from_parent_user_id") or contact.get("parent_user_id") or "")
    canonical = user_id or parent_id or phone
    if not canonical:
        raise ValueError("Webhook message has no supported customer identity")
    return {
        "id": canonical,
        "phone": phone,
        "user_id": user_id,
        "parent_user_id": parent_id,
        "username": str(profile.get("username") or ""),
        "name": str(profile.get("name") or profile.get("username") or phone or canonical),
    }


def _claim(message_id: str) -> bool:
    try:
        ddb.put_item(
            Item={"pk": f"MESSAGE#{message_id}", "sk": "EVENT", "ttl": int(time.time()) + 7 * 86400},
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _flow_reply(message: dict[str, Any]) -> dict[str, Any] | None:
    interactive = message.get("interactive") or {}
    if str(interactive.get("type") or "").lower() != "nfm_reply":
        return None
    reply = interactive.get("nfm_reply") or {}
    raw = reply.get("response_json") or {}
    try:
        values = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        values = {}
    flow_token = str(values.pop("flow_token", "") or reply.get("flow_token") or "")

    def display(value: Any) -> str:
        if value is None:
            return "—"
        if value is True:
            return "Sí"
        if value is False:
            return "No"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)

    answers = [{"field": str(key), "value": display(value)} for key, value in values.items()]
    return {
        "flow_token": flow_token,
        "name": str(reply.get("name") or ""),
        "body": str(reply.get("body") or ""),
        "answers": answers,
    }


def _content(message: dict[str, Any]) -> tuple[str, str | None]:
    kind = message.get("type", "unknown")
    if kind == "text":
        return message.get("text", {}).get("body", ""), None
    if kind == "interactive":
        flow = _flow_reply(message)
        if flow:
            rows = [f"{answer['field']}: {answer['value']}" for answer in flow["answers"]]
            return "Formulario de WhatsApp recibido" + ("\n" + "\n".join(rows) if rows else ""), None
        value = message.get("interactive", {})
        reply = value.get("button_reply") or value.get("list_reply") or {}
        return reply.get("title") or reply.get("id") or "[Respuesta interactiva]", reply.get("id")
    if kind == "button":
        return message.get("button", {}).get("text") or "[Botón]", message.get("button", {}).get("payload")
    if kind == "location":
        loc = message.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        label = loc.get("name") or loc.get("address") or "Ubicación compartida"
        return f"{label}\nAbrir en el mapa: https://maps.google.com/?q={lat},{lon}", None
    if kind == "contacts":
        rows = []
        for item in message.get("contacts") or []:
            name = (item.get("name") or {}).get("formatted_name", "Contacto")
            phones = ", ".join(p.get("phone", "") for p in item.get("phones") or [])
            emails = ", ".join(e.get("email", "") for e in item.get("emails") or [])
            company = str((item.get("org") or {}).get("company") or "")
            addresses = "; ".join(
                a.get("formatted_address") or ", ".join(
                    str(a.get(key) or "") for key in ("street", "city", "state", "zip", "country") if a.get(key)
                )
                for a in item.get("addresses") or []
            )
            urls = ", ".join(u.get("url", "") for u in item.get("urls") or [])
            details = [value for value in (phones, emails, company, addresses, urls) if value]
            rows.append(f"{name}\n" + "\n".join(details) if details else name)
        return "Contactos compartidos:\n" + "\n".join(rows), None
    if kind in {"image", "audio", "video", "document", "sticker"}:
        node = message.get(kind) or {}
        caption = node.get("caption") or ""
        return caption or _media_link_label(kind), None
    if kind == "reaction":
        reaction = message.get("reaction") or {}
        return f"[Reacción {reaction.get('emoji', '')}]", None
    return f"[Mensaje de tipo {kind}]", None


def _connect_text_content(text: str) -> tuple[str, str]:
    """Translate valid WhatsApp emphasis into Amazon Connect Markdown.

    WhatsApp uses one asterisk for bold, while Connect follows standard
    Markdown and needs two. Only complete, non-whitespace-delimited spans are
    converted so literal or unmatched symbols remain plain text.
    """
    rendered = str(text or "")
    uses_markdown = bool(re.search(
        r"(?<![\\*])\*\*(?=\S)([^*\r\n]*?\S)\*\*(?!\*)",
        rendered,
    ))

    rendered, code_count = re.subn(
        r"(?<!`)```(?=\S)(.*?\S)```(?!`)",
        lambda match: f"`{match.group(1)}`",
        rendered,
        flags=re.DOTALL,
    )
    uses_markdown = uses_markdown or code_count > 0

    rendered, bold_count = re.subn(
        r"(?<![\w\\*])\*(?=\S)([^*\r\n]*?\S)\*(?![\w*])",
        lambda match: f"**{match.group(1)}**",
        rendered,
    )
    uses_markdown = uses_markdown or bold_count > 0

    # WhatsApp and Connect share the underscore syntax for italics.
    if re.search(r"(?<![\w\\_])_(?=\S)([^_\r\n]*?\S)_(?![\w_])", rendered):
        uses_markdown = True

    # Connect chat does not document strikethrough support. Preserve the words
    # without showing WhatsApp's tildes rather than relying on an unsupported style.
    rendered, _ = re.subn(
        r"(?<![\w\\~])~(?=\S)([^~\r\n]*?\S)~(?![\w~])",
        lambda match: match.group(1),
        rendered,
    )

    return rendered, "text/markdown" if uses_markdown else "text/plain"


def _canonical_envelope(change: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(change, message)
    text, reply_id = _content(message)
    kind = str(message.get("type") or "unknown")
    media = dict(message.get(kind) or {}) if kind in {"image", "audio", "video", "document", "sticker"} else {}
    return {
        "schema": "social-message/1.0",
        "channel": "whatsapp",
        "provider": "meta_direct",
        "business_id": str(change.get("_social_business_id") or ""),
        "sender_asset_id": str((change.get("metadata") or {}).get("phone_number_id") or ""),
        "conversation_key": identity["id"],
        "customer": identity,
        "message": {
            "id": str(message.get("id") or ""),
            "type": kind,
            "text": text,
            "reply_id": str(reply_id or ""),
            "reply_to": str((message.get("context") or {}).get("id") or ""),
            "timestamp": str(message.get("timestamp") or ""),
            "media": media,
            "flow_response": _flow_reply(message) or {},
        },
    }


def _session(
    identity: dict[str, str],
    initial_text: str,
    attributes: dict[str, str],
    event_id: str,
    initial_content_type: str = "text/plain",
) -> tuple[dict[str, str], bool]:
    key = {"pk": f"IDENTITY#{identity['id']}", "sk": "SESSION"}
    current = ddb.get_item(Key=key, ConsistentRead=True).get("Item")
    if current and int(current.get("expires_at", 0)) > int(time.time()):
        try:
            described = connect.describe_contact(
                InstanceId=os.environ["CONNECT_INSTANCE_ID"], ContactId=current["contact_id"]
            )["Contact"]
            if not described.get("DisconnectTimestamp"):
                return {k: str(current[k]) for k in ("contact_id", "participant_token")}, False
        except ClientError:
            pass

    idempotency_token = hashlib.sha256(event_id.encode()).hexdigest()
    requested_flow_id = attributes.pop("target_flow_id", None)
    development_flow_id = _development_contact_flow(identity["phone"])
    if development_flow_id:
        attributes["routing_rule"] = "development_phone"
    elif requested_flow_id:
        attributes["routing_rule"] = "campaign_button"
    started = connect.start_chat_contact(
        InstanceId=os.environ["CONNECT_INSTANCE_ID"],
        ContactFlowId=development_flow_id or requested_flow_id or os.environ["DEFAULT_CONTACT_FLOW_ID"],
        ParticipantDetails={"DisplayName": _participant_display_name(identity)},
        Attributes={k: v[:32767] for k, v in attributes.items() if v},
        InitialMessage={
            "ContentType": initial_content_type,
            "Content": initial_text[:1024] or "Mensaje recibido",
        },
        SupportedMessagingContentTypes=["text/plain", "text/markdown", "application/vnd.amazonaws.connect.message.interactive"],
        ClientToken=idempotency_token,
    )
    try:
        connect.start_contact_streaming(
            InstanceId=os.environ["CONNECT_INSTANCE_ID"], ContactId=started["ContactId"],
            ChatStreamingConfiguration={"StreamingEndpointArn": os.environ["OUTBOUND_TOPIC_ARN"]},
            ClientToken=idempotency_token,
        )
        participant.create_participant_connection(
            Type=["CONNECTION_CREDENTIALS"],
            ParticipantToken=started["ParticipantToken"],
            ConnectParticipant=True,
        )
    except Exception:
        try:
            connect.stop_contact(InstanceId=os.environ["CONNECT_INSTANCE_ID"], ContactId=started["ContactId"])
        except Exception:
            logger.exception("Could not stop chat after streaming setup failure")
        raise
    expires_at = int(time.time()) + int(os.environ.get("SESSION_TTL_SECONDS", "86400"))
    item = {
        **key,
        "contact_id": started["ContactId"],
        "participant_token": started["ParticipantToken"],
        "identity_id": identity["id"],
        "phone": identity["phone"],
        "user_id": identity["user_id"],
        "username": identity["username"],
        "customer_name": identity["name"],
        "gsi1pk": f"CONTACT#{started['ContactId']}",
        "gsi1sk": "SESSION",
        "expires_at": expires_at,
        "ttl": expires_at + 7 * 86400,
    }
    ddb.put_item(Item=item)
    return {"contact_id": started["ContactId"], "participant_token": started["ParticipantToken"]}, True


def _text_chunks(text: str, limit: int = 1000) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks


def _send_connect(session: dict[str, str], text: str, content_type: str = "text/plain") -> None:
    connection = participant.create_participant_connection(
        Type=["CONNECTION_CREDENTIALS"], ParticipantToken=session["participant_token"]
    )["ConnectionCredentials"]["ConnectionToken"]
    for chunk in _text_chunks(text):
        participant.send_message(
            ConnectionToken=connection, ContentType=content_type, Content=chunk, ClientToken=str(uuid.uuid4())
        )


def _send_connect_if_active(session: dict[str, str], text: str, content_type: str = "text/plain") -> bool:
    try:
        _send_connect(session, text, content_type)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"AccessDeniedException", "ResourceNotFoundException"}:
            logger.warning("Connect session is no longer active; preserving processed media without chat delivery",
                           extra={"contact_id": session.get("contact_id")})
            return False
        raise


def _attachment_name(message: dict[str, Any], kind: str, content_type: str) -> str:
    node = message.get(kind) or {}
    original = (
        str(node.get("filename") or "")
        .replace("/", "_")
        .replace("\\", "_")
        .replace("\r", "")
        .replace("\n", "")
        .strip()
    )
    if original:
        return original[:240]
    extension = mimetypes.guess_extension(content_type.split(";", 1)[0]) or ""
    timestamp = str(message.get("timestamp") or "")
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(int(timestamp)))
    except (TypeError, ValueError, OverflowError):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = _stable_id(str(message.get("id") or uuid.uuid4()))[:8]
    label = {"image": "foto", "audio": "audio", "video": "video", "sticker": "sticker"}.get(kind, "archivo")
    return f"{label}-whatsapp-{stamp}-{suffix}{extension}"


def _inline_content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "'") or "archivo"
    encoded = urllib.parse.quote(filename, safe="")
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def _media_link_label(kind: str) -> str:
    return {
        "image": "Imagen enviada por el cliente",
        "audio": "Audio enviado por el cliente",
        "video": "Video enviado por el cliente",
        "document": "Documento enviado por el cliente",
        "sticker": "Sticker enviado por el cliente",
    }.get(kind, "Archivo enviado por el cliente")


def _markdown_link_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _media_link_text(message: dict[str, Any], kind: str, url: str) -> str:
    node = message.get(kind) or {}
    content_type = str(node.get("mime_type") or "application/octet-stream")
    filename = _attachment_name(message, kind, content_type)
    link = f"[{_markdown_link_label(filename)}]({url})"
    caption = str(node.get("caption") or "").strip()
    return f"{caption}\n\n{link}" if caption else link


def _transcribe_language_parameters() -> dict[str, Any]:
    language_code = os.environ.get("TRANSCRIBE_LANGUAGE_CODE", "es-US").strip()
    if not language_code or language_code.lower() == "auto":
        return {"IdentifyLanguage": True}
    return {"LanguageCode": language_code}


def _transcription_message(text: str) -> str:
    return f"Transcripción:\n\n{text.strip()}"


def _reserve_media_link(kind: str) -> tuple[str, str]:
    token = secure_random.token_urlsafe(12)
    now = int(time.time())
    expires_at = now + int(os.environ.get("MEDIA_LINK_SECONDS", "86400"))
    ddb.put_item(Item={
        "pk": f"MEDIA_LINK#{_stable_id(token)}",
        "sk": "LINK",
        "status": "PENDING",
        "media_type": kind,
        "created_at": now,
        "expires_at": expires_at,
        "ttl": expires_at,
    })
    base_url = os.environ["MEDIA_LINK_BASE_URL"].rstrip("/")
    return token, f"{base_url}/{token}"


def _activate_media_link(token: str, key: str, filename: str, content_type: str) -> None:
    safe_content_type = content_type.split(";", 1)[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*", safe_content_type):
        safe_content_type = "application/octet-stream"
    ddb.update_item(
        Key={"pk": f"MEDIA_LINK#{_stable_id(token)}", "sk": "LINK"},
        UpdateExpression="SET #s=:s, s3_key=:k, filename=:f, content_type=:c, content_disposition=:d, updated_at=:u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "READY",
            ":k": key,
            ":f": filename,
            ":c": safe_content_type,
            ":d": _inline_content_disposition(filename),
            ":u": int(time.time()),
        },
    )


def _ocr_lines(result: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    minimum_confidence = float(os.environ.get("OCR_MIN_CONFIDENCE", "80"))
    for block in result.get("Blocks") or []:
        if block.get("BlockType") != "LINE" or not block.get("Text"):
            continue
        text = str(block["Text"]).strip()
        confidence = float(block.get("Confidence") or 0)
        if confidence < minimum_confidence or sum(character.isalnum() for character in text) < 2:
            continue
        box = (block.get("Geometry") or {}).get("BoundingBox") or {}
        lines.append({
            "id": len(lines),
            "text": text,
            "confidence": round(confidence, 2),
            "page": int(block.get("Page") or 1),
            "top": round(float(box.get("Top") or 0), 5),
            "left": round(float(box.get("Left") or 0), 5),
        })
    return lines


def _geometric_ocr_text(lines: list[dict[str, Any]]) -> str:
    ordered = sorted(lines, key=lambda line: (line["page"], line["top"], line["left"]))
    return "\n".join(line["text"] for line in ordered)


def _organized_ocr_text(lines: list[dict[str, Any]], blob: bytes | None = None, content_type: str = "") -> str:
    if not lines or sum(character.isalnum() for line in lines for character in line["text"]) < 4:
        return ""
    if len(lines) > 400:
        return _geometric_ocr_text(lines)
    compact = [{k: line[k] for k in ("id", "text", "page", "top", "left")} for line in lines]
    prompt = (
        "Organiza estas líneas OCR en secciones semánticas según la imagen, su posición bidimensional y sentido "
        "de lectura. Agrupa títulos, columnas, etiquetas laterales y el contenido visualmente relacionado. "
        "No transcribas ni corrijas texto. "
        "Devuelve solo JSON con esta forma: {\"sections\":[{\"heading\":[0],\"body\":[1,2]}]}. "
        "Cada id debe aparecer exactamente una vez, sin inventar, omitir ni repetir ids. Las líneas de título van "
        f"en heading y las demás en body. Líneas: {json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}"
    )
    content: list[dict[str, Any]] = []
    image_format = {
        "image/jpeg": "jpeg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"
    }.get(content_type.split(";", 1)[0])
    if blob and image_format:
        content.append({"image": {"format": image_format, "source": {"bytes": blob}}})
    content.append({"text": prompt})
    try:
        response = bedrock.converse(
            modelId=os.environ.get("OCR_BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0"),
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": 2048, "temperature": 0},
        )
    except ClientError:
        logger.exception("Bedrock OCR ordering failed; using geometric order")
        return _geometric_ocr_text(lines)
    raw = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        sections = json.loads(raw)["sections"]
        used = [int(index) for section in sections for key in ("heading", "body") for index in section.get(key, [])]
        expected = list(range(len(lines)))
        if len(used) != len(expected) or sorted(used) != expected:
            raise ValueError("Bedrock did not return an exact permutation of OCR line ids")
        rendered: list[str] = []
        by_id = {line["id"]: line["text"] for line in lines}
        for section in sections:
            rendered.extend(by_id[int(index)] for index in section.get("heading", []))
            rendered.extend(by_id[int(index)] for index in section.get("body", []))
            rendered.append("")
        return "\n".join(rendered).strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Bedrock OCR ordering was invalid; using geometric order")
        return _geometric_ocr_text(lines)


def _organized_transcript_text(transcript: str) -> str:
    segments = [segment.strip() for segment in re.findall(r"[^.!?]+(?:[.!?]+|$)", transcript) if segment.strip()]
    if len(segments) <= 1:
        return transcript.strip()
    indexed = [{"id": index, "text": text} for index, text in enumerate(segments)]
    prompt = (
        "Agrupa estos segmentos de una transcripción en párrafos temáticos para facilitar la lectura. No corrijas, "
        "resumas, reescribas ni agregues texto. Devuelve solo JSON: {\"paragraphs\":[[0,1],[2]]}. Cada id debe "
        f"aparecer exactamente una vez, sin omitir ni repetir. Segmentos: {json.dumps(indexed, ensure_ascii=False, separators=(',', ':'))}"
    )
    try:
        response = bedrock.converse(
            modelId=os.environ.get("OCR_BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0"),
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
        )
        raw = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        paragraphs = json.loads(raw)["paragraphs"]
        used = [int(index) for paragraph in paragraphs for index in paragraph]
        if len(used) != len(segments) or sorted(used) != list(range(len(segments))):
            raise ValueError("Bedrock did not return an exact permutation of transcript segment ids")
        return "\n\n".join(" ".join(segments[int(index)] for index in paragraph) for paragraph in paragraphs)
    except (ClientError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Bedrock transcript formatting failed; preserving Transcribe output")
        return transcript.strip()


def _media(message: dict[str, Any], session: dict[str, str]) -> str | None:
    kind = message["type"]
    node = message.get(kind) or {}
    media_id = node.get("id")
    if not media_id:
        return None
    max_bytes = int(os.environ.get("MAX_MEDIA_BYTES", "20971520"))
    content_type = node.get("mime_type") or "application/octet-stream"
    extension = mimetypes.guess_extension(content_type.split(";", 1)[0]) or ""
    filename = _attachment_name(message, kind, content_type)
    try:
        received_path = time.strftime("%Y/%m/%d", time.gmtime(int(message.get("timestamp") or time.time())))
    except (TypeError, ValueError, OverflowError):
        received_path = time.strftime("%Y/%m/%d")
    prefix = f"inbound/{received_path}/{media_id}"
    key = f"{prefix}{extension}"
    stored = False
    candidates = s3.list_objects_v2(Bucket=os.environ["MEDIA_BUCKET"], Prefix=prefix, MaxKeys=1).get("Contents") or []
    if candidates:
        key = str(candidates[0]["Key"])
    try:
        existing = s3.get_object(Bucket=os.environ["MEDIA_BUCKET"], Key=key)
        with existing["Body"] as body:
            blob = body.read(max_bytes + 1)
        content_type = existing.get("ContentType") or content_type
        stored = True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
            raise
        secret = _secret()
        graph = os.environ.get("META_GRAPH_VERSION", "v26.0")
        headers = {"Authorization": f"Bearer {secret['WA_ACCESS_TOKEN']}"}
        metadata = _http_json(f"https://graph.facebook.com/{graph}/{media_id}", headers=headers)
        request = urllib.request.Request(metadata["url"], headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            blob = response.read(max_bytes + 1)
        content_type = metadata.get("mime_type") or content_type
        extension = mimetypes.guess_extension(content_type.split(";", 1)[0]) or extension
        filename = _attachment_name(message, kind, content_type)
        key = f"{prefix}{extension}"
    if len(blob) > max_bytes:
        raise ValueError("Media exceeds configured size limit")
    if not stored:
        s3.put_object(Bucket=os.environ["MEDIA_BUCKET"], Key=key, Body=blob, ContentType=content_type,
                      ContentDisposition=_inline_content_disposition(filename),
                      ServerSideEncryption="aws:kms", SSEKMSKeyId=os.environ["KMS_KEY_ARN"])

    media_link_token = str(message.get("_media_link_token") or "")
    if not media_link_token:
        raise ValueError("Media task does not contain its short-link token")
    _activate_media_link(media_link_token, key, filename, content_type)

    if kind == "image" or (kind == "document" and content_type.split(";", 1)[0] == "application/pdf"):
        try:
            result = textract.analyze_document(
                Document={"S3Object": {"Bucket": os.environ["MEDIA_BUCKET"], "Name": key}},
                FeatureTypes=["LAYOUT"],
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {
                "UnsupportedDocumentException", "BadDocumentException", "DocumentTooLargeException"
            }:
                logger.warning("Textract could not process document", extra={"media_id": media_id})
                return None
            raise
        text = _organized_ocr_text(_ocr_lines(result), blob if kind == "image" else None, content_type)
        return _transcription_message(text) if text else None
    if kind in {"audio", "video"}:
        project = re.sub(
            r"[^A-Za-z0-9._-]", "-", os.environ.get("POWERTOOLS_SERVICE_NAME", "redes-sociales-connect")
        )[:40]
        job = f"{project}-wa-" + re.sub(r"[^A-Za-z0-9._-]", "-", media_id)[-150:]
        media_format = {
            ".mpeg": "mp3", ".mp3": "mp3", ".mp4": "mp4", ".wav": "wav", ".flac": "flac",
            ".ogg": "ogg", ".oga": "ogg", ".amr": "amr", ".webm": "webm", ".m4a": "m4a",
        }.get(extension.lower(), "ogg" if "ogg" in content_type else "mp4" if kind == "video" else "mp3")
        transcribe.start_transcription_job(
            TranscriptionJobName=job,
            **_transcribe_language_parameters(),
            MediaFormat=media_format,
            Media={"MediaFileUri": f"s3://{os.environ['MEDIA_BUCKET']}/{key}"},
            OutputBucketName=os.environ["MEDIA_BUCKET"],
            OutputKey=f"transcripts/{job}.json",
            OutputEncryptionKMSKeyId=os.environ["KMS_KEY_ARN"],
            JobExecutionSettings={"DataAccessRoleArn": os.environ["TRANSCRIBE_DATA_ROLE_ARN"]},
            Settings={"ShowSpeakerLabels": False},
        )
        ddb.put_item(Item={
            "pk": f"TRANSCRIBE#{job}", "sk": "JOB", **session, "media_type": kind, "filename": filename,
            "ttl": int(time.time()) + 86400,
        })
    return None


def _route(identity_id: str, reply_id: str | None) -> dict[str, Any] | None:
    if not reply_id:
        return None
    item = ddb.get_item(Key={"pk": f"ROUTE#{identity_id}", "sk": f"BUTTON#{reply_id}"}).get("Item")
    return item if item and item.get("contact_flow_id") else None


def _store_flow_response(
    flow_response: dict[str, Any], identity: dict[str, str], message_id: str, text: str
) -> str:
    flow_token = str(flow_response.get("flow_token") or "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", flow_token):
        flow_token = ""
    campaign = ddb.get_item(
        Key={"pk": f"CAMPAIGN#{flow_token}", "sk": "META"}, ConsistentRead=True
    ).get("Item") if flow_token else None
    campaign_id = flow_token if campaign else "unassigned"
    flow_ids = [str(value) for value in ((campaign or {}).get("flow_ids") or [])]
    now = int(time.time())
    ddb.put_item(Item={
        "pk": f"CAMPAIGN#{campaign_id}",
        "sk": f"RESPONSE#{now:010d}#{message_id}",
        "id": message_id,
        "message_id": message_id,
        "campaign_id": campaign_id,
        "flow_token": flow_token,
        "flow_id": flow_ids[0] if flow_ids else "",
        "flow_ids": flow_ids,
        "form_name": str((campaign or {}).get("template_name") or flow_response.get("name") or "WhatsApp Flow"),
        "identity_id": identity["id"],
        "customer_name": identity.get("name") or identity["id"],
        "phone": identity.get("phone") or "",
        "answers": list(flow_response.get("answers") or []),
        "answer_summary": text,
        "created_at": now,
        "ttl": now + 395 * 86400,
    })
    if campaign:
        ddb.update_item(
            Key={"pk": "ADMIN#CAMPAIGNS", "sk": f"CAMPAIGN#{campaign_id}"},
            UpdateExpression="SET last_response_at=:u, updated_at=:u ADD response_count :one",
            ExpressionAttributeValues={":u": now, ":one": 1},
        )
        ddb.update_item(
            Key={"pk": f"CAMPAIGN#{campaign_id}", "sk": "META"},
            UpdateExpression="SET last_response_at=:u, updated_at=:u ADD response_count :one",
            ExpressionAttributeValues={":u": now, ":one": 1},
        )
    return campaign_id


def _meta_event(body: dict[str, Any]) -> None:
    for entry in body.get("entry") or []:
        for change_wrapper in entry.get("changes") or []:
            change = dict(change_wrapper.get("value") or {})
            # WhatsApp identifies the business account at entry level and the
            # sender phone-number asset inside change.metadata. Preserve both.
            change["_social_business_id"] = str(entry.get("id") or "")
            for delivery_status in change.get("statuses") or []:
                meta_id = str(delivery_status.get("id") or "")
                status = str(delivery_status.get("status") or "unknown").upper()
                if not meta_id:
                    continue
                key = {"pk": f"MESSAGE#{meta_id}", "sk": "DELIVERY"}
                delivery = ddb.get_item(Key=key).get("Item")
                ddb.update_item(
                    Key=key,
                    UpdateExpression="SET #s=:s, updated_at=:u",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": status, ":u": int(time.time())},
                )
                if delivery and delivery.get("campaign_id"):
                    ddb.update_item(
                        Key={"pk": f"CAMPAIGN#{delivery['campaign_id']}", "sk": f"OUTBOUND#{meta_id}"},
                        UpdateExpression="SET #s=:s, updated_at=:u",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":s": status, ":u": int(time.time())},
                    )
            for message in change.get("messages") or []:
                message_id = str(message.get("id") or uuid.uuid4())
                if not _claim(message_id):
                    continue
                try:
                    canonical = _canonical_envelope(change, message)
                    identity = canonical["customer"]
                    text = canonical["message"]["text"]
                    media_kind = str(message.get("type") or "")
                    is_media = media_kind in {"image", "audio", "video", "document", "sticker"}
                    media_link_token = ""
                    chat_content_type = "text/plain"
                    if is_media:
                        media_link_token, media_link_url = _reserve_media_link(media_kind)
                        text = _media_link_text(message, media_kind, media_link_url)
                        chat_content_type = "text/markdown"
                    elif media_kind == "text":
                        text, chat_content_type = _connect_text_content(text)
                        canonical["message"]["text"] = text
                    flow_response = canonical["message"].get("flow_response") or {}
                    reply_id = canonical["message"]["reply_id"] or None
                    route = _route(identity["id"], reply_id)
                    flow_campaign_id = str(flow_response.get("flow_token") or "")
                    attributes = {
                        "chatframework_Channel": "WHATSAPP",
                        "chatframework_VendorId": identity["phone"] or identity["id"],
                        "telefono": identity["phone"],
                        "wa_user_id": identity["user_id"],
                        "wa_username": identity["username"],
                        "nombre": identity["name"],
                        "customer_name": identity["name"],
                        "customer_display_name": identity["name"],
                        "customer_phone": identity["phone"],
                        "whatsapp_phone": identity["phone"],
                        "nombres": identity["name"],
                        "initial_message": text,
                        "whatsapp_message_id": message_id,
                        "social_schema": canonical["schema"],
                        "social_provider": canonical["provider"],
                        "social_channel": canonical["channel"],
                        "social_business_id": canonical["business_id"],
                        "social_account_id": canonical["business_id"],
                        "social_asset_id": canonical["sender_asset_id"],
                        "social_user_id": identity["id"],
                        "social_parent_user_id": identity.get("parent_user_id") or "",
                        "social_display_name": identity["name"],
                        "social_phone": identity["phone"],
                        "social_username": identity["username"],
                        "social_handle": identity["username"],
                        "social_message_id": message_id,
                        "customer_handle": identity["username"],
                        "source_message_id": message_id,
                        "campaign_id": flow_campaign_id or str((route or {}).get("campaign_id") or ""),
                        "button_id": str(reply_id or ""),
                        "target_flow_id": str((route or {}).get("contact_flow_id") or ""),
                    }
                    session, is_new = _session(
                        identity,
                        text,
                        attributes,
                        message_id,
                        initial_content_type=chat_content_type,
                    )
                    if not is_new:
                        _send_connect(session, text, chat_content_type)
                    if is_media:
                        _enqueue_media({
                            "source": "media",
                            "canonical": canonical,
                            "message": {**message, "_media_link_token": media_link_token},
                            "session": session,
                        })
                    if flow_response:
                        _store_flow_response(flow_response, identity, message_id, text)
                    elif route and reply_id:
                        ddb.put_item(Item={
                            "pk": f"CAMPAIGN#{route.get('campaign_id') or 'unassigned'}",
                            "sk": f"RESPONSE#{int(time.time() * 1000)}#{message_id}",
                            "identity_id": identity["id"], "button_id": reply_id, "answer": text,
                            "contact_flow_id": str(route["contact_flow_id"]), "created_at": int(time.time()),
                            "ttl": int(time.time()) + 395 * 86400,
                        })
                    ddb.update_item(
                        Key={"pk": f"IDENTITY#{identity['id']}", "sk": "SESSION"},
                        UpdateExpression="SET last_message_id=:m, updated_at=:u, expires_at=:e, #ttl=:t",
                        ExpressionAttributeNames={"#ttl": "ttl"},
                        ExpressionAttributeValues={
                            ":m": message_id, ":u": int(time.time()),
                            ":e": int(time.time()) + int(os.environ.get("SESSION_TTL_SECONDS", "86400")),
                            ":t": int(time.time()) + int(os.environ.get("SESSION_TTL_SECONDS", "86400")) + 7 * 86400,
                        },
                    )
                    ddb.update_item(
                        Key={"pk": f"MESSAGE#{message_id}", "sk": "EVENT"},
                        UpdateExpression="SET #s=:s", ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":s": "COMPLETED"},
                    )
                    _metric("MessagesProcessed", Channel="whatsapp", Direction="inbound")
                except Exception:
                    # The SQS retry must be able to reclaim an event that failed halfway through.
                    ddb.delete_item(Key={"pk": f"MESSAGE#{message_id}", "sk": "EVENT"})
                    raise


def _send_whatsapp(identity: dict[str, str], message: dict[str, Any]) -> dict[str, Any]:
    secret = _secret()
    payload = {"messaging_product": "whatsapp", **message}
    if identity.get("phone"):
        payload["to"] = identity["phone"]
    else:
        payload["recipient"] = identity["id"]
    return _http_json(
        f"https://graph.facebook.com/{os.environ.get('META_GRAPH_VERSION', 'v26.0')}/{secret['WA_PHONE_NUMBER_ID']}/messages",
        method="POST", payload=payload,
        headers={"Authorization": f"Bearer {secret['WA_ACCESS_TOKEN']}", "Content-Type": "application/json"},
    )


def _download_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        blob = response.read(int(os.environ.get("MAX_MEDIA_BYTES", "20971520")) + 1)
    if len(blob) > int(os.environ.get("MAX_MEDIA_BYTES", "20971520")):
        raise ValueError("Media exceeds configured size limit")
    return blob


def _upload_whatsapp_media(blob: bytes, content_type: str, filename: str) -> str:
    secret = _secret()
    boundary = f"----social-connect-{uuid.uuid4().hex}"
    safe_filename = filename.replace('"', "'").replace("\r", "").replace("\n", "")
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"messaging_product\"\r\n\r\nwhatsapp\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\n{content_type}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe_filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + blob + f"\r\n--{boundary}--\r\n".encode("ascii")
    graph = os.environ.get("META_GRAPH_VERSION", "v26.0")
    request = urllib.request.Request(
        f"https://graph.facebook.com/{graph}/{secret['WA_PHONE_NUMBER_ID']}/media",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {secret['WA_ACCESS_TOKEN']}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            media_id = str(json.loads(response.read() or b"{}").get("id") or "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"Meta media upload returned HTTP {exc.code}: {detail}") from exc
    if not media_id:
        raise RuntimeError("Meta media upload did not return an id")
    return media_id


def _whatsapp_media_kind(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    return "document"


def _send_agent_attachments(event: dict[str, Any], row: dict[str, Any]) -> None:
    connection = participant.create_participant_connection(
        Type=["CONNECTION_CREDENTIALS"], ParticipantToken=str(row["participant_token"])
    )["ConnectionCredentials"]["ConnectionToken"]
    identity = {"id": str(row["identity_id"]), "phone": str(row.get("phone") or "")}
    event_id = str(event.get("Id") or uuid.uuid4())
    for attachment in event.get("Attachments") or []:
        if str(attachment.get("Status") or "").upper() != "APPROVED":
            continue
        attachment_id = str(attachment.get("AttachmentId") or "")
        if not attachment_id:
            continue
        claim_id = f"connect-attachment-{event_id}-{attachment_id}"
        if not _claim(claim_id):
            continue
        try:
            details = participant.get_attachment(AttachmentId=attachment_id, ConnectionToken=connection)
            blob = _download_url(details["Url"])
            content_type = str(attachment.get("ContentType") or "application/octet-stream")
            filename = str(attachment.get("AttachmentName") or "archivo").replace("/", "_").replace("\\", "_")[:240]
            media_id = _upload_whatsapp_media(blob, content_type, filename)
            kind = _whatsapp_media_kind(content_type)
            media = {"id": media_id}
            if kind == "document":
                media["filename"] = filename
            result = _send_whatsapp(identity, {"type": kind, kind: media})
            meta_id = str(((result.get("messages") or [{}])[0]).get("id") or "")
            if meta_id:
                now = int(time.time())
                ddb.put_item(Item={
                    "pk": f"MESSAGE#{meta_id}", "sk": "DELIVERY", "meta_message_id": meta_id,
                    "status": "ACCEPTED", "direction": "OUTBOUND_ATTACHMENT", "identity_id": identity["id"],
                    "contact_id": str(event.get("InitialContactId") or event.get("ContactId") or ""),
                    "connect_attachment_id": attachment_id, "filename": filename,
                    "created_at": now, "updated_at": now, "ttl": now + 395 * 86400,
                })
            _metric("MessagesProcessed", Channel="whatsapp", Direction="outbound_attachment", MediaType=kind)
        except Exception:
            ddb.delete_item(Key={"pk": f"MESSAGE#{claim_id}", "sk": "EVENT"})
            raise


def _admin_one(body: dict[str, Any], request_id: str) -> None:
    # `to` is the public admin API field; `phone` remains accepted for backwards compatibility.
    phone = str(body.get("to") or body.get("phone") or "")
    identity = {"id": str(body.get("user_id") or phone), "phone": phone}
    if not identity["id"]:
        raise ValueError("phone or user_id is required")
    if body.get("template"):
        payload = {"type": "template", "template": body["template"]}
    elif body.get("media"):
        media = dict(body["media"])
        kind = str(media.pop("type"))
        if kind not in {"image", "audio", "video", "document"}:
            raise ValueError("unsupported outbound media type")
        s3_key = media.pop("s3_key", None)
        if s3_key:
            media["link"] = s3.generate_presigned_url(
                "get_object", Params={"Bucket": os.environ["MEDIA_BUCKET"], "Key": s3_key}, ExpiresIn=3600
            )
        if not media.get("link") and not media.get("id"):
            raise ValueError("media requires s3_key, link or Meta media id")
        payload = {"type": kind, kind: media}
    else:
        payload = {"type": "text", "text": {"body": str(body["text"]), "preview_url": False}}
    claim_id = f"admin-{request_id}-{identity['id']}"
    if not _claim(claim_id):
        return
    try:
        result = _send_whatsapp(identity, payload)
        meta_id = str(((result.get("messages") or [{}])[0]).get("id") or "")
        if meta_id:
            now = int(time.time())
            campaign_id = str(body.get("campaign_id") or "direct")
            delivery = {
                "meta_message_id": meta_id, "campaign_id": campaign_id, "identity_id": identity["id"],
                "status": "ACCEPTED", "request_id": request_id, "created_at": now,
                "updated_at": now, "actor": dict(body.get("_actor") or {}), "agent_name": str(body.get("agent_name") or ""),
                "contact_id": str(body.get("contact_id") or ""), "ttl": now + 395 * 86400,
            }
            ddb.put_item(Item={"pk": f"MESSAGE#{meta_id}", "sk": "DELIVERY", **delivery})
            ddb.put_item(Item={"pk": f"CAMPAIGN#{campaign_id}", "sk": f"OUTBOUND#{meta_id}", **delivery})
        for route in body.get("button_routes") or []:
            ddb.put_item(Item={
                "pk": f"ROUTE#{identity['id']}", "sk": f"BUTTON#{route['button_id']}",
                "contact_flow_id": route["contact_flow_id"], "campaign_id": str(body.get("campaign_id") or ""),
                "ttl": int(time.time()) + int(body.get("route_ttl_seconds", 604800)),
            })
    except Exception:
        ddb.delete_item(Key={"pk": f"MESSAGE#{claim_id}", "sk": "EVENT"})
        raise


def _admin(command: str, body: dict[str, Any], request_id: str) -> None:
    if command == "campaign":
        recipients = body.get("recipients") or []
        if not 1 <= len(recipients) <= 100:
            raise ValueError("campaign recipients must contain between 1 and 100 entries")
        common = {k: v for k, v in body.items() if k != "recipients"}
        for recipient_data in recipients:
            _admin_one({**common, **recipient_data}, request_id)
        return
    _admin_one(body, request_id)


def _connect_event(notification: dict[str, Any]) -> None:
    event = notification.get("Message")
    if isinstance(event, str):
        event = json.loads(event)
    event = event or {}
    if str(event.get("ParticipantRole", "")).upper() not in {"AGENT", "SYSTEM"}:
        return
    contact_id = str(event.get("InitialContactId") or event.get("ContactId") or "")
    if not contact_id:
        return
    rows = ddb.query(IndexName="ContactIndex", KeyConditionExpression=Key("gsi1pk").eq(f"CONTACT#{contact_id}"))["Items"]
    if not rows:
        return
    row = rows[0]
    if str(event.get("ParticipantRole", "")).upper() == "AGENT" and event.get("Attachments"):
        _send_agent_attachments(event, row)
        return
    content = str(event.get("Content") or "")
    if not content:
        return
    identity = {"id": str(row["identity_id"]), "phone": str(row.get("phone") or "")}
    if _template_dsl_enabled(identity["phone"]) and _is_template_dsl(content):
        try:
            payload, template_type = _template_dsl_payload(content, row)
        except ValueError as exc:
            logger.warning(json.dumps({
                "event": "template_dsl_rejected",
                "contact_id": contact_id,
                "reason": str(exc),
            }, separators=(",", ":")))
            _metric("TemplateDslRejected", Channel="whatsapp", Reason=str(exc)[:100])
            return
        _send_whatsapp(identity, payload)
        _metric("MessagesProcessed", Channel="whatsapp", Direction="outbound", MessageType=template_type)
        return
    _send_whatsapp(identity, {"type": "text", "text": {"body": content[:4096], "preview_url": False}})
    _metric("MessagesProcessed", Channel="whatsapp", Direction="outbound", MessageType="text")


def _transcribe_event(detail: dict[str, Any]) -> None:
    job = detail["TranscriptionJobName"]
    item = ddb.get_item(Key={"pk": f"TRANSCRIBE#{job}", "sk": "JOB"}).get("Item")
    if not item:
        return
    if detail.get("TranscriptionJobStatus") == "FAILED":
        ddb.update_item(
            Key={"pk": f"TRANSCRIBE#{job}", "sk": "JOB"},
            UpdateExpression="SET #s=:s, updated_at=:u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "FAILED", ":u": int(time.time())},
        )
        _send_connect_if_active(
            {"contact_id": str(item["contact_id"]), "participant_token": str(item["participant_token"])},
            f"El archivo {item.get('filename') or ''} está disponible en la vista previa, pero no pudo transcribirse automáticamente.",
        )
        return
    if detail.get("TranscriptionJobStatus") != "COMPLETED":
        return
    obj = s3.get_object(Bucket=os.environ["MEDIA_BUCKET"], Key=f"transcripts/{job}.json")
    with obj["Body"] as body:
        result = json.loads(body.read())
    text = (result.get("results", {}).get("transcripts") or [{}])[0].get("transcript", "")
    label = "audio" if str(item.get("media_type") or "") == "audio" else "audio del video"
    if not text:
        ddb.update_item(
            Key={"pk": f"TRANSCRIBE#{job}", "sk": "JOB"},
            UpdateExpression="SET #s=:s, transcript_characters=:c, updated_at=:u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "COMPLETED_NO_SPEECH", ":c": 0, ":u": int(time.time())},
        )
        _send_connect_if_active(
            {"contact_id": str(item["contact_id"]), "participant_token": str(item["participant_token"])},
            f"El {label} {item.get('filename') or ''} se procesó correctamente, pero no contenía voz reconocible.",
        )
        return
    if text:
        formatted = _organized_transcript_text(text)
        formatted_key = f"formatted-transcripts/{job}.txt"
        s3.put_object(
            Bucket=os.environ["MEDIA_BUCKET"], Key=formatted_key, Body=formatted.encode("utf-8"),
            ContentType="text/plain; charset=utf-8", ContentDisposition=_inline_content_disposition(f"{job}.txt"),
            ServerSideEncryption="aws:kms", SSEKMSKeyId=os.environ["KMS_KEY_ARN"],
        )
        ddb.update_item(
            Key={"pk": f"TRANSCRIBE#{job}", "sk": "JOB"},
            UpdateExpression="SET #s=:s, transcript_s3_key=:t, formatted_s3_key=:f, transcript_characters=:c, updated_at=:u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "COMPLETED", ":t": f"transcripts/{job}.json", ":f": formatted_key,
                ":c": len(text), ":u": int(time.time()),
            },
        )
        _send_connect_if_active(
            {"contact_id": str(item["contact_id"]), "participant_token": str(item["participant_token"])},
            _transcription_message(formatted), "text/plain"
        )


def _dispatch(payload: dict[str, Any]) -> None:
    mode = os.environ.get("WORKER_MODE", "conversation")
    source = payload.get("source")
    if source == "meta" and mode == "conversation":
        _meta_event(payload.get("body") or {})
    elif source == "admin" and mode == "campaign":
        _admin(str(payload.get("command") or "send"), payload.get("body") or {}, str(payload.get("request_id") or uuid.uuid4()))
        _metric("CampaignMessagesSubmitted", Channel="whatsapp")
    elif source == "media" and mode == "media":
        transcript = _media(payload.get("message") or {}, payload.get("session") or {})
        if transcript:
            _send_connect_if_active(payload.get("session") or {}, transcript)
        _metric(
            "MediaProcessed",
            Channel="whatsapp",
            MediaType=str((payload.get("message") or {}).get("type") or "unknown"),
        )
    elif source == "aws.transcribe" and mode == "media":
        _transcribe_event(payload.get("detail") or {})
    elif source == "connect_ordered" and mode == "conversation":
        _connect_event(payload.get("notification") or {})
    elif payload.get("Type") == "Notification" and mode == "conversation":
        event = payload.get("Message")
        if isinstance(event, str):
            event = json.loads(event)
        event = event or {}
        contact_id = str(event.get("InitialContactId") or event.get("ContactId") or "unknown")
        event_id = str(
            event.get("Id")
            or event.get("MessageId")
            or _stable_id(json.dumps(event, sort_keys=True, separators=(",", ":")))
        )
        _enqueue_fifo(
            {"source": "connect_ordered", "notification": payload},
            f"connect:{contact_id}",
            f"connect:{contact_id}:{event_id}",
        )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    failures = []
    for record in event.get("Records") or []:
        try:
            _dispatch(json.loads(record["body"]))
        except Exception:
            logger.exception("Work item failed", extra={"message_id": record.get("messageId", "unknown")})
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
