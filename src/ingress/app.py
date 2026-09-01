"""HTTP entry point for Meta webhooks and authenticated administration commands."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets as secure_random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config


_sqs = boto3.client("sqs")
_s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
_secrets = boto3.client("secretsmanager")
_connect = boto3.client("connect")
_ddb = boto3.resource("dynamodb")
_secret_cache: tuple[float, dict[str, str]] | None = None
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MODULE_ACTIONS = {
    "segments": {"view", "create", "import"},
    "quotes": {"view", "send"},
    "templates": {"view", "manage"},
    "campaigns": {"view", "create", "send", "delete"},
    "surveys": {"view", "manage"},
    "responses": {"view"},
}

# Grants saved by older releases used the broad ``manage`` action. Keep those
# profiles working while exposing narrower permissions in the current UI.
LEGACY_ACTION_ALIASES = {
    ("segments", "create"): "manage",
    ("segments", "import"): "manage",
    ("campaigns", "create"): "manage",
    ("campaigns", "send"): "manage",
}

MAX_SEGMENT_CONTACTS = 1000


def _response(status: int, body: str | dict[str, Any]) -> dict[str, Any]:
    def json_default(value: Any) -> int | float:
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": body if isinstance(body, str) else json.dumps(body, default=json_default),
    }


def _media_redirect(token: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
        return {
            "statusCode": 410,
            "headers": {"content-type": "text/plain; charset=utf-8", "cache-control": "no-store"},
            "body": "El enlace del archivo no es válido.",
        }
    item = _ddb.Table(os.environ["STATE_TABLE"]).get_item(
        Key={"pk": f"MEDIA_LINK#{_stable_id(token)}", "sk": "LINK"}, ConsistentRead=True
    ).get("Item")
    now = int(time.time())
    if not item or int(item.get("expires_at") or 0) <= now:
        return {
            "statusCode": 410,
            "headers": {"content-type": "text/plain; charset=utf-8", "cache-control": "no-store"},
            "body": "Este enlace temporal expiró.",
        }
    if item.get("status") != "READY" or not item.get("s3_key"):
        return {
            "statusCode": 425,
            "headers": {
                "content-type": "text/plain; charset=utf-8",
                "cache-control": "no-store",
                "retry-after": "3",
            },
            "body": "El archivo todavía se está procesando. Intente nuevamente en unos segundos.",
        }
    url = _s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": os.environ["MEDIA_BUCKET"],
            "Key": str(item["s3_key"]),
            "ResponseContentType": str(item.get("content_type") or "application/octet-stream"),
            "ResponseContentDisposition": str(item.get("content_disposition") or "inline"),
        },
        ExpiresIn=int(os.environ.get("MEDIA_REDIRECT_SECONDS", "300")),
    )
    return {
        "statusCode": 302,
        "headers": {
            "location": url,
            "cache-control": "no-store, private",
            "referrer-policy": "no-referrer",
        },
        "body": "",
    }


def _secret() -> dict[str, str]:
    global _secret_cache
    now = time.monotonic()
    if _secret_cache and now - _secret_cache[0] < 300:
        return _secret_cache[1]
    value = _secrets.get_secret_value(SecretId=os.environ["WHATSAPP_SECRET_ARN"])
    parsed = json.loads(value["SecretString"])
    _secret_cache = (now, parsed)
    return parsed


def _meta_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    return _meta_request_json(url, headers)


def _meta_request_json(
    url: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    encoded_body: bytes | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers)
    data = encoded_body
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        content_type = "application/json"
    if content_type:
        request_headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"success": True}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        try:
            error = (json.loads(detail).get("error") or {})
            message = str(error.get("message") or "Meta rechazó la operación")[:500]
            code = str(error.get("code") or exc.code)
            raise RuntimeError(f"Meta Graph ({code}): {message}") from exc
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(f"Meta Graph returned HTTP {exc.code}") from exc


def _meta_multipart_json(
    url: str, headers: dict[str, str], fields: dict[str, str], filename: str, content: bytes
) -> dict[str, Any]:
    boundary = f"----social-connect-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"), b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/json\r\n\r\n", content, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return _meta_request_json(
        url, headers, method="POST", encoded_body=b"".join(chunks),
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def _meta_context() -> tuple[str, dict[str, str], str]:
    secret = _secret()
    graph = os.environ.get("META_GRAPH_VERSION", "v26.0")
    headers = {"Authorization": f"Bearer {secret['WA_ACCESS_TOKEN']}"}
    # The WABA is a separate Meta asset; the phone-number node does not expose
    # a parent ``whatsapp_business_account`` field.
    waba_id = str(secret.get("WA_BUSINESS_ACCOUNT_ID") or os.environ.get("WA_BUSINESS_ACCOUNT_ID") or "").strip()
    if not waba_id:
        raise ValueError("WA_BUSINESS_ACCOUNT_ID is not configured")
    return graph, headers, waba_id


def _meta_templates_response(include_pending: bool = False) -> dict[str, Any]:
    """Return the approved templates for the WhatsApp number without exposing Meta credentials."""
    graph, headers, waba_id = _meta_context()
    fields = "name,language,status,category,parameter_format,components,quality_score"
    next_url = f"https://graph.facebook.com/{graph}/{waba_id}/message_templates?{urllib.parse.urlencode({'fields': fields, 'limit': 100})}"
    items: list[dict[str, Any]] = []
    while next_url and len(items) < 500:
        page = _meta_json(next_url, headers)
        for template in page.get("data") or []:
            status = str(template.get("status") or "").upper()
            if not include_pending and status not in {"APPROVED", "ACTIVE"}:
                continue
            components = template.get("components") or []
            header = next((part for part in components if str(part.get("type") or "").upper() == "HEADER"), {})
            body = next((part for part in components if str(part.get("type") or "").upper() == "BODY"), {})
            footer = next((part for part in components if str(part.get("type") or "").upper() == "FOOTER"), {})
            text = str(body.get("text") or "")
            numeric_variables = sorted({int(value) for value in re.findall(r"\{\{\s*(\d+)\s*\}\}", text)})
            named_variables = list(dict.fromkeys(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", text)))
            variables: list[int | str] = numeric_variables or named_variables
            examples = {
                str(example.get("param_name") or ""): str(example.get("example") or "")
                for example in ((body.get("example") or {}).get("body_text_named_params") or [])
                if example.get("param_name")
            }
            flow_ids = []
            for component in components:
                for button in component.get("buttons") or []:
                    if str(button.get("type") or "").upper() == "FLOW" and button.get("flow_id"):
                        flow_ids.append(str(button["flow_id"]))
            items.append({
                "id": f"meta:{template.get('name')}:{template.get('language')}",
                "source": "meta",
                "name": str(template.get("name") or ""),
                "language": str(template.get("language") or ""),
                "category": str(template.get("category") or ""),
                "status": {
                    "APPROVED": "Aprobada", "ACTIVE": "Aprobada", "PENDING": "En revisión",
                    "REJECTED": "Rechazada", "PAUSED": "Pausada", "DISABLED": "Deshabilitada",
                }.get(status, status.title() or "Sin estado"),
                "status_code": status,
                "header": str(header.get("text") or ""),
                "body": text,
                "footer": str(footer.get("text") or ""),
                "variables": variables,
                "parameter_format": str(template.get("parameter_format") or ("NAMED" if named_variables else "POSITIONAL")),
                "variable_examples": examples,
                "flow_ids": flow_ids,
                "quality": str(template.get("quality_score") or ""),
            })
        next_url = str(((page.get("paging") or {}).get("next")) or "")
    return _response(200, {"items": items})


def _meta_flows_response() -> dict[str, Any]:
    """Return the account's WhatsApp Flows without exposing Meta credentials."""
    graph, headers, waba_id = _meta_context()
    url = f"https://graph.facebook.com/{graph}/{waba_id}/flows?{urllib.parse.urlencode({'fields': 'id,name,status,updated_time', 'limit': 100})}"
    items: list[dict[str, Any]] = []
    while url and len(items) < 500:
        page = _meta_json(url, headers)
        for flow in page.get("data") or []:
            status = str(flow.get("status") or "").upper()
            items.append({
                "id": str(flow.get("id") or ""), "name": str(flow.get("name") or ""),
                "status": {"PUBLISHED": "Publicado", "DRAFT": "Borrador", "DEPRECATED": "Obsoleto", "BLOCKED": "Bloqueado"}.get(status, status.title() or "Sin estado"),
                "status_code": status,
                "updated": str(flow.get("updated_time") or ""), "published": status == "PUBLISHED",
            })
        url = str(((page.get("paging") or {}).get("next")) or "")
    return _response(200, {"items": items})


FLOW_CATEGORIES = {
    "SIGN_UP", "SIGN_IN", "APPOINTMENT_BOOKING", "LEAD_GENERATION", "CONTACT_US",
    "CUSTOMER_SUPPORT", "SURVEY", "OTHER",
}


def _validated_flow_json(value: Any) -> tuple[dict[str, Any], bytes]:
    if not isinstance(value, dict):
        raise ValueError("flow_json_required")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise ValueError("flow_json_too_large")
    screens = value.get("screens")
    if not isinstance(screens, list) or not 1 <= len(screens) <= 50:
        raise ValueError("flow_screens_required")
    ids = [str(screen.get("id") or "") for screen in screens if isinstance(screen, dict)]
    if len(ids) != len(screens) or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,49}", item) for item in ids):
        raise ValueError("invalid_flow_screen_id")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_flow_screen_id")
    if not any(bool(screen.get("terminal")) for screen in screens):
        raise ValueError("flow_terminal_screen_required")
    if not str(value.get("version") or "").strip():
        raise ValueError("flow_version_required")
    return value, encoded


def _flow_identity(body: dict[str, Any]) -> tuple[str, list[str]]:
    name = str(body.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9À-ÿ _.-]{1,200}", name):
        raise ValueError("invalid_flow_name")
    categories = [str(item).strip().upper() for item in (body.get("categories") or ["OTHER"])]
    if not categories or any(item not in FLOW_CATEGORIES for item in categories):
        raise ValueError("invalid_flow_category")
    return name, list(dict.fromkeys(categories))


def _meta_upload_flow_json(flow_id: str, value: Any) -> dict[str, Any]:
    _definition, encoded = _validated_flow_json(value)
    graph, headers, _waba_id = _meta_context()
    return _meta_multipart_json(
        f"https://graph.facebook.com/{graph}/{flow_id}/assets", headers,
        {"name": "flow.json", "asset_type": "FLOW_JSON"}, "flow.json", encoded,
    )


def _invalidate_meta_cache(catalog: str) -> None:
    try:
        _ddb.Table(os.environ["STATE_TABLE"]).delete_item(
            Key={"pk": "ADMIN#META_CATALOG", "sk": catalog.upper()}
        )
    except Exception:
        logger.warning(json.dumps({"event": "meta_catalog_cache_invalidate_failed", "catalog": catalog}), exc_info=True)


def _meta_flow_command(actor: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    action = str(body.get("action") or "").strip().lower()
    graph, headers, waba_id = _meta_context()
    if action == "create":
        name, categories = _flow_identity(body)
        _definition, _encoded = _validated_flow_json(body.get("flow_json"))
        form = urllib.parse.urlencode({"name": name, "categories": json.dumps(categories)}).encode("utf-8")
        created = _meta_request_json(
            f"https://graph.facebook.com/{graph}/{waba_id}/flows", headers, method="POST",
            encoded_body=form, content_type="application/x-www-form-urlencoded",
        )
        flow_id = str(created.get("id") or "")
        if not re.fullmatch(r"\d+", flow_id):
            raise RuntimeError("Meta no devolvió el identificador del Flow creado")
        uploaded = _meta_upload_flow_json(flow_id, body.get("flow_json"))
        _invalidate_meta_cache("flows")
        logger.info(json.dumps({"event": "meta_flow_created", "flow_id": flow_id, "actor": actor.get("subject"), "categories": categories}))
        return _response(201, {
            "id": flow_id, "name": name, "status": "Borrador",
            "validation_errors": uploaded.get("validation_errors") or [], "uploaded": bool(uploaded.get("success", True)),
        })
    flow_id = str(body.get("flow_id") or "").strip()
    if not re.fullmatch(r"\d+", flow_id):
        raise ValueError("invalid_flow_id")
    if action == "update_json":
        uploaded = _meta_upload_flow_json(flow_id, body.get("flow_json"))
        _invalidate_meta_cache("flows")
        logger.info(json.dumps({"event": "meta_flow_json_updated", "flow_id": flow_id, "actor": actor.get("subject")}))
        return _response(200, {"id": flow_id, "validation_errors": uploaded.get("validation_errors") or [], "uploaded": bool(uploaded.get("success", True))})
    if action == "publish":
        if body.get("confirm_publish") is not True:
            raise ValueError("publish_confirmation_required")
        published = _meta_request_json(f"https://graph.facebook.com/{graph}/{flow_id}/publish", headers, method="POST", payload={})
        _invalidate_meta_cache("flows")
        logger.info(json.dumps({"event": "meta_flow_published", "flow_id": flow_id, "actor": actor.get("subject")}))
        return _response(200, {"id": flow_id, "published": bool(published.get("success", True)), "status": "Publicado"})
    raise ValueError("invalid_flow_action")


def _template_component_body(text: str, examples: dict[str, Any]) -> dict[str, Any]:
    variables = list(dict.fromkeys(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", text)))
    component: dict[str, Any] = {"type": "BODY", "text": text}
    if variables:
        clean_examples = {str(key): str(value).strip() for key, value in examples.items()}
        if any(not clean_examples.get(variable) for variable in variables):
            raise ValueError("template_variable_examples_required")
        component["example"] = {"body_text_named_params": [
            {"param_name": variable, "example": clean_examples[variable]} for variable in variables
        ]}
    return component


def _meta_template_command(actor: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name") or "").strip().lower()
    language = str(body.get("language") or "es_DO").strip()
    category = str(body.get("category") or "UTILITY").strip().upper()
    text = str(body.get("body") or "").strip()
    footer = str(body.get("footer") or "").strip()
    flow_name = str(body.get("flow_name") or "").strip()
    navigate_screen = str(body.get("navigate_screen") or "").strip()
    button_text = str(body.get("button_text") or "Abrir formulario").strip()
    if not re.fullmatch(r"[a-z0-9_]{1,512}", name):
        raise ValueError("invalid_template_name")
    if not re.fullmatch(r"[a-z]{2}(?:_[A-Z]{2})?", language):
        raise ValueError("invalid_template_language")
    if category not in {"UTILITY", "MARKETING"}:
        raise ValueError("invalid_template_category")
    if not text or len(text) > 1024:
        raise ValueError("invalid_template_body")
    if not flow_name or len(flow_name) > 200 or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,49}", navigate_screen):
        raise ValueError("invalid_template_flow")
    if not 1 <= len(button_text) <= 25:
        raise ValueError("invalid_template_button")
    components = [_template_component_body(text, body.get("variable_examples") or {})]
    if footer:
        components.append({"type": "FOOTER", "text": footer[:60]})
    components.append({"type": "BUTTONS", "buttons": [{
        "type": "FLOW", "text": button_text, "flow_name": flow_name,
        "navigate_screen": navigate_screen, "flow_action": "navigate",
    }]})
    graph, headers, waba_id = _meta_context()
    created = _meta_request_json(
        f"https://graph.facebook.com/{graph}/{waba_id}/message_templates", headers, method="POST",
        payload={"name": name, "language": language, "category": category, "parameter_format": "NAMED", "components": components},
    )
    _invalidate_meta_cache("templates")
    logger.info(json.dumps({"event": "meta_template_created", "template_id": str(created.get("id") or ""), "actor": actor.get("subject"), "flow_name": flow_name}))
    return _response(201, {
        "id": str(created.get("id") or ""), "name": name,
        "status": str(created.get("status") or "PENDING"), "category": str(created.get("category") or category),
    })


def _meta_catalog_with_cache(catalog: str, loader: Any) -> dict[str, Any]:
    """Prefer Meta's live catalog and retain the last sanitized successful response."""
    table = _ddb.Table(os.environ["STATE_TABLE"])
    cache_key = {"pk": "ADMIN#META_CATALOG", "sk": catalog.upper()}
    try:
        live_response = loader()
        payload = json.loads(str(live_response.get("body") or "{}"))
        now = int(time.time())
        payload.update({"source": "live", "stale": False, "synced_at": now})
        try:
            table.put_item(Item={**cache_key, "items": payload.get("items") or [], "synced_at": now})
        except Exception:
            logger.warning(json.dumps({"event": "meta_catalog_cache_write_failed", "catalog": catalog}), exc_info=True)
        return _response(200, payload)
    except Exception:
        logger.exception(json.dumps({"event": "meta_catalog_error", "catalog": catalog}))
        cached = table.get_item(Key=cache_key, ConsistentRead=True).get("Item") or {}
        if cached.get("items") is not None:
            return _response(200, {
                "items": cached.get("items") or [], "source": "cache", "stale": True,
                "synced_at": int(cached.get("synced_at") or 0),
            })
        raise


def _raw_body(event: dict[str, Any]) -> bytes:
    body = event.get("body") or ""
    return base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")


def _header(event: dict[str, Any], name: str) -> str:
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    return headers.get(name.lower(), "")


def _valid_signature(raw: bytes, signature: str, app_secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _app_origin_allowed(event: dict[str, Any]) -> bool:
    expected = os.environ.get("ADMIN_APP_ORIGIN", "").rstrip("/")
    if not expected:
        return True
    return _header(event, "origin").rstrip("/") == expected


def _connect_actor(agent_arn: str) -> dict[str, Any] | None:
    instance_id = os.environ["CONNECT_INSTANCE_ID"]
    marker = f":instance/{instance_id}/agent/"
    if marker not in agent_arn:
        return None
    agent_id = agent_arn.rsplit("/", 1)[-1]
    user = _connect.describe_user(InstanceId=instance_id, UserId=agent_id).get("User") or {}
    if str(user.get("Arn") or "") != agent_arn:
        return None
    # ``get_current_user_data`` only returns agents that have an active entry in
    # the real-time view.  That is not the same as an authenticated user of
    # Agent Workspace: an agent can legitimately open this 3P application while
    # inactive or without a contact.  The App SDK handshake already supplied the
    # ARN, and DescribeUser is the authoritative source for the Connect user and
    # its routing/security profiles, so do not make access depend on live data.
    namespace = os.environ["ADMIN_APP_NAMESPACE"]
    security_profile_ids = [str(value) for value in user.get("SecurityProfileIds") or []]
    permitted = False
    permissions: set[str] = set()
    for profile_id in security_profile_ids:
        applications = _connect.list_security_profile_applications(
            InstanceId=instance_id, SecurityProfileId=profile_id, MaxResults=100
        ).get("Applications") or []
        if any(
            app.get("Namespace") == namespace and "ACCESS" in (app.get("ApplicationPermissions") or [])
            for app in applications
        ):
            permitted = True
        permissions.update(
            _connect.list_security_profile_permissions(
                InstanceId=instance_id, SecurityProfileId=profile_id
            ).get("Permissions") or []
        )
    if not permitted:
        return None
    routing_profile_id = str(user.get("RoutingProfileId") or "")
    developer_routing_ids = {
        value.strip() for value in os.environ.get("DEVELOPER_ROUTING_PROFILE_IDS", "").split(",") if value.strip()
    }
    developer_security_ids = {
        value.strip() for value in os.environ.get("DEVELOPER_SECURITY_PROFILE_IDS", "").split(",") if value.strip()
    }
    if routing_profile_id in developer_routing_ids or developer_security_ids.intersection(security_profile_ids):
        role, role_label = "developer", "Developer"
    elif "SecurityProfiles.Edit" in permissions:
        role, role_label = "admin", "Administrador"
    else:
        role, role_label = "agent", "Agente"
    identity = user.get("IdentityInfo") or {}
    name = " ".join(str(identity.get(key) or "").strip() for key in ("FirstName", "LastName")).strip()
    return {
        "agent_arn": agent_arn,
        "agent_id": agent_id,
        "username": str(user.get("Username") or agent_id),
        "name": name or str(user.get("Username") or agent_id),
        "routing_profile_id": routing_profile_id,
        "security_profile_ids": security_profile_ids,
        "role": role,
        "role_label": role_label,
    }


def _create_connect_session(event: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    # Agent Workspace securely mediates SDK calls inside the iframe, but it does
    # not issue a server-verifiable identity token to a third-party backend.
    # AWS therefore requires 3P applications to provide their own authentication.
    # Keep context-only bootstrap explicit and disabled by default.
    if os.environ.get("ADMIN_APP_AUTH_MODE", "disabled") != "connect-context-preview":
        return _response(503, {"error": "admin_auth_not_configured"})
    if not _app_origin_allowed(event):
        return _response(403, {"error": "invalid_app_origin"})
    if str(body.get("connect_network_status") or "") != "connected":
        return _response(403, {"error": "connect_not_connected"})
    actor = _connect_actor(str(body.get("agent_arn") or ""))
    if not actor:
        return _response(403, {"error": "connect_access_denied"})
    token = secure_random.token_urlsafe(32)
    now = int(time.time())
    ttl_seconds = int(os.environ.get("CONNECT_SESSION_SECONDS", "900"))
    table = _ddb.Table(os.environ["STATE_TABLE"])
    table.put_item(Item={
        "pk": f"CONNECT_SESSION#{_stable_id(token)}", "sk": "SESSION", **actor,
        "created_at": now, "expires_at": now + ttl_seconds, "ttl": now + ttl_seconds,
    })
    return _response(200, {
        "session_token": token, "expires_in": ttl_seconds, "agent_arn": actor["agent_arn"],
        "name": actor["name"], "username": actor["username"], "role": actor["role"],
        "role_label": actor["role_label"], "routing_profile_id": actor["routing_profile_id"],
        "module_permissions": _module_permissions(actor),
    })


def _session_actor(event: dict[str, Any]) -> dict[str, Any] | None:
    authorization = _header(event, "authorization")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    item = _ddb.Table(os.environ["STATE_TABLE"]).get_item(
        Key={"pk": f"CONNECT_SESSION#{_stable_id(token)}", "sk": "SESSION"}, ConsistentRead=True
    ).get("Item")
    if not item or int(item.get("expires_at") or 0) <= int(time.time()):
        return None
    return item


def _profile_applications(profile_id: str) -> list[dict[str, Any]]:
    return _connect.list_security_profile_applications(
        InstanceId=os.environ["CONNECT_INSTANCE_ID"], SecurityProfileId=profile_id, MaxResults=100
    ).get("Applications") or []


def _module_permissions(actor: dict[str, Any]) -> dict[str, dict[str, bool]]:
    if actor.get("role") == "developer":
        return {module: {action: True for action in actions} for module, actions in MODULE_ACTIONS.items()}
    table = _ddb.Table(os.environ["STATE_TABLE"])
    configured = False
    result = {module: {action: False for action in actions} for module, actions in MODULE_ACTIONS.items()}
    for profile_id in actor.get("security_profile_ids") or []:
        item = table.get_item(Key={"pk": "ADMIN#MODULE_PERMISSIONS", "sk": f"PROFILE#{profile_id}"}).get("Item")
        if not item:
            continue
        configured = True
        grants = item.get("grants") or {}
        for module, actions in result.items():
            for action in actions:
                module_grants = grants.get(module) or {}
                legacy_action = LEGACY_ACTION_ALIASES.get((module, action))
                actions[action] = actions[action] or bool(
                    module_grants.get(action) or (legacy_action and module_grants.get(legacy_action))
                )
    if not configured and actor.get("role") == "admin":
        return {module: {action: True for action in actions} for module, actions in MODULE_ACTIONS.items()}
    return result


def _has_module_permission(actor: dict[str, Any], module: str, action: str) -> bool:
    return bool(_module_permissions(actor).get(module, {}).get(action))


def _normalized_grants(grants: dict[str, Any]) -> dict[str, dict[str, bool]]:
    normalized: dict[str, dict[str, bool]] = {}
    for module, actions in MODULE_ACTIONS.items():
        module_grants = grants.get(module) or {}
        normalized[module] = {}
        for action in actions:
            legacy_action = LEGACY_ACTION_ALIASES.get((module, action))
            normalized[module][action] = bool(
                module_grants.get(action) or (legacy_action and module_grants.get(legacy_action))
            )
    return normalized


def _module_permissions_response(actor: dict[str, Any], method: str, body: dict[str, Any] | None) -> dict[str, Any]:
    if actor.get("role") != "developer":
        return _response(403, {"error": "developer_routing_required"})
    table = _ddb.Table(os.environ["STATE_TABLE"])
    if method == "POST":
        profile_id = str((body or {}).get("security_profile_id") or "")
        grants = (body or {}).get("grants") or {}
        if not profile_id or not isinstance(grants, dict):
            return _response(400, {"error": "security_profile_id_and_grants_required"})
        clean = {module: {action: bool((grants.get(module) or {}).get(action)) for action in actions} for module, actions in MODULE_ACTIONS.items()}
        table.put_item(Item={"pk": "ADMIN#MODULE_PERMISSIONS", "sk": f"PROFILE#{profile_id}", "profile_id": profile_id, "grants": clean, "updated_at": int(time.time())})
        return _response(200, {"id": profile_id, "grants": clean})
    profiles = _connect.list_security_profiles(InstanceId=os.environ["CONNECT_INSTANCE_ID"], MaxResults=100).get("SecurityProfileSummaryList") or []
    items = []
    for profile in sorted(profiles, key=lambda value: str(value.get("Name") or "")):
        profile_id = str(profile.get("Id") or "")
        stored = table.get_item(Key={"pk": "ADMIN#MODULE_PERMISSIONS", "sk": f"PROFILE#{profile_id}"}).get("Item") or {}
        if stored:
            grants = _normalized_grants(stored.get("grants") or {})
        else:
            connect_permissions = _connect.list_security_profile_permissions(
                InstanceId=os.environ["CONNECT_INSTANCE_ID"], SecurityProfileId=profile_id
            ).get("Permissions") or []
            default_allowed = "SecurityProfiles.Edit" in connect_permissions
            grants = {
                module: {action: default_allowed for action in actions}
                for module, actions in MODULE_ACTIONS.items()
            }
        items.append({
            "id": profile_id,
            "name": str(profile.get("Name") or profile_id),
            "grants": grants,
        })
    return _response(200, {"items": items, "modules": {key: sorted(value) for key, value in MODULE_ACTIONS.items()}})


def _access_profiles_response(actor: dict[str, Any], method: str, body: dict[str, Any] | None) -> dict[str, Any]:
    if actor.get("role") != "developer":
        return _response(403, {"error": "developer_routing_required"})
    instance_id = os.environ["CONNECT_INSTANCE_ID"]
    namespace = os.environ["ADMIN_APP_NAMESPACE"]
    if method == "POST":
        profile_id = str((body or {}).get("security_profile_id") or "")
        enabled = (body or {}).get("enabled") is True
        if not profile_id:
            return _response(400, {"error": "security_profile_id_required"})
        if not enabled and profile_id in {str(value) for value in actor.get("security_profile_ids") or []}:
            return _response(409, {"error": "cannot_remove_current_profile"})
        existing = _profile_applications(profile_id)
        applications = [app for app in existing if app.get("Namespace") != namespace]
        if enabled:
            applications.append({
                "Namespace": namespace, "ApplicationPermissions": ["ACCESS"],
                "Type": "THIRD_PARTY_APPLICATION",
            })
        _connect.update_security_profile(
            InstanceId=instance_id, SecurityProfileId=profile_id, Applications=applications
        )
        return _response(200, {"id": profile_id, "enabled": enabled})
    profiles: list[dict[str, Any]] = []
    next_token: str | None = None
    while True:
        request: dict[str, Any] = {"InstanceId": instance_id, "MaxResults": 100}
        if next_token:
            request["NextToken"] = next_token
        page = _connect.list_security_profiles(**request)
        profiles.extend(page.get("SecurityProfileSummaryList") or [])
        next_token = page.get("NextToken")
        if not next_token:
            break
    current = {str(value) for value in actor.get("security_profile_ids") or []}
    items = []
    for profile in sorted(profiles, key=lambda value: str(value.get("Name") or "")):
        profile_id = str(profile.get("Id") or "")
        applications = _profile_applications(profile_id)
        items.append({
            "id": profile_id, "name": str(profile.get("Name") or profile_id),
            "description": str(profile.get("Description") or ""), "current": profile_id in current,
            "enabled": any(
                app.get("Namespace") == namespace and "ACCESS" in (app.get("ApplicationPermissions") or [])
                for app in applications
            ),
        })
    return _response(200, {"items": items})


def _enqueue_fifo(queue_url: str, payload: dict[str, Any], group_id: str, deduplication_id: str) -> None:
    _sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(payload, separators=(",", ":")),
        MessageGroupId=_stable_id(group_id),
        MessageDeduplicationId=_stable_id(deduplication_id),
    )


def _meta_units(body: dict[str, Any]) -> list[tuple[dict[str, Any], str, str]]:
    """Split a Meta webhook into independently ordered, deduplicated units."""
    units: list[tuple[dict[str, Any], str, str]] = []
    for entry in body.get("entry") or []:
        for wrapper in entry.get("changes") or []:
            value = wrapper.get("value") or {}
            common = {k: v for k, v in value.items() if k not in {"messages", "statuses"}}
            contacts = value.get("contacts") or []
            contact = contacts[0] if contacts else {}
            for message in value.get("messages") or []:
                identity = str(
                    message.get("from_user_id")
                    or message.get("from_parent_user_id")
                    or message.get("from")
                    or contact.get("user_id")
                    or contact.get("parent_user_id")
                    or contact.get("wa_id")
                    or "unknown"
                )
                message_id = str(message.get("id") or uuid.uuid4())
                unit_value = {**common, "contacts": contacts, "messages": [message]}
                unit = {
                    "object": body.get("object", "whatsapp_business_account"),
                    "entry": [{"id": entry.get("id"), "changes": [{"field": wrapper.get("field"), "value": unit_value}]}],
                }
                units.append((unit, f"whatsapp:{identity}", f"message:{message_id}"))
            for status in value.get("statuses") or []:
                recipient = str(status.get("recipient_id") or status.get("id") or "status")
                status_id = str(status.get("id") or uuid.uuid4())
                status_value = {**common, "statuses": [status]}
                unit = {
                    "object": body.get("object", "whatsapp_business_account"),
                    "entry": [{"id": entry.get("id"), "changes": [{"field": wrapper.get("field"), "value": status_value}]}],
                }
                units.append((unit, f"whatsapp:{recipient}", f"status:{status_id}:{status.get('status', '')}"))
    return units


def _enqueue_admin(command: str, body: dict[str, Any], request_id: str, actor: dict[str, str]) -> int:
    queue_url = os.environ["CAMPAIGN_QUEUE_URL"]
    if command == "quote":
        recipients = body.get("recipients") or [{"to": body.get("to") or body.get("phone")}]
        if not 1 <= len(recipients) <= 100:
            raise ValueError("quote recipients must contain between 1 and 100 entries")
        common = {key: value for key, value in body.items() if key not in {"recipients", "template", "media", "to", "phone"}}
        common["_actor"] = actor
        template = body.get("template")
        media = body.get("media")
        if not media:
            raise ValueError("quote requires media")
        queued = 0
        for index, recipient in enumerate(recipients):
            to = str(recipient.get("to") or recipient.get("phone") or "")
            if not to:
                raise ValueError("quote recipient requires phone")
            recipient_body = {**common, "to": to, "campaign_id": str(body.get("campaign_id") or "direct")}
            if template:
                _enqueue_fifo(
                    queue_url,
                    {"source": "admin", "command": "send", "body": {**recipient_body, "template": template, "quote_stage": "template"}, "request_id": f"{request_id}:template:{index}"},
                    f"whatsapp:{to}", f"quote:{request_id}:{to}:template",
                )
                queued += 1
            _enqueue_fifo(
                queue_url,
                {"source": "admin", "command": "send", "body": {**recipient_body, "media": media, "quote_stage": "document"}, "request_id": f"{request_id}:document:{index}"},
                f"whatsapp:{to}", f"quote:{request_id}:{to}:document",
            )
            queued += 1
        return queued
    if command == "campaign":
        recipients = body.get("recipients") or []
        segment_id = str(body.get("segment_id") or "").strip()
        if segment_id:
            recipients = _segment_recipients(segment_id, str(body.get("phone_strategy") or "primary"))
        if not 1 <= len(recipients) <= MAX_SEGMENT_CONTACTS:
            raise ValueError(f"campaign recipients must contain between 1 and {MAX_SEGMENT_CONTACTS} entries")
        campaign_id = str(body.get("campaign_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", campaign_id):
            raise ValueError("campaign_id is required and contains invalid characters")
        template = body.get("template") or {}
        mappings = body.get("variable_mappings") or {}
        if mappings and not isinstance(mappings, dict):
            raise ValueError("variable_mappings must be an object")
        allowed_fields = {"name", "phone", "document_id", "email"}
        clean_mappings = {
            str(number): str(field) for number, field in mappings.items()
            if str(number).isdigit() and str(field) in allowed_fields
        }
        if len(clean_mappings) != len(mappings):
            raise ValueError("variable_mappings contains unsupported fields")
        if clean_mappings:
            personalized: list[dict[str, Any]] = []
            for recipient in recipients:
                values = {
                    "name": str(recipient.get("customer_name") or recipient.get("name") or "").strip(),
                    "phone": str(recipient.get("to") or recipient.get("phone") or "").strip(),
                    "document_id": str(recipient.get("document_id") or "").strip(),
                    "email": str(recipient.get("email") or "").strip(),
                }
                if not all(values.get(field) for field in clean_mappings.values()):
                    continue
                body_parameters = [
                    {"type": "text", "text": values[clean_mappings[number]]}
                    for number in sorted(clean_mappings, key=int)
                ]
                components = [component for component in (template.get("components") or [])
                              if str(component.get("type") or "").lower() != "body"]
                components.insert(0, {"type": "body", "parameters": body_parameters})
                personalized.append({**recipient, "template": {**template, "components": components}})
            recipients = personalized
            if not recipients:
                raise ValueError("segment has no recipients with all mapped template fields")
        now = int(time.time())
        campaign = {
            "id": campaign_id,
            "campaign_id": campaign_id,
            "name": str(body.get("name") or campaign_id)[:200],
            "template_name": str(template.get("name") or "")[:512],
            "template_language": str((template.get("language") or {}).get("code") or "")[:32],
            "flow_ids": [str(value)[:128] for value in (body.get("flow_ids") or [])],
            "flow_names": [str(value)[:512] for value in (body.get("flow_names") or [])],
            "campaign_type": str(body.get("campaign_type") or "informative")[:32],
            "segment_id": segment_id[:128],
            "segment_name": str(body.get("segment_name") or "")[:200],
            "phone_strategy": str(body.get("phone_strategy") or "primary")[:16],
            "variable_mappings": clean_mappings,
            "recipient_count": len(recipients),
            "status": "QUEUING",
            "created_at": now,
            "updated_at": now,
            "actor": actor,
            "ttl": now + 395 * 86400,
        }
        table = _ddb.Table(os.environ["STATE_TABLE"])
        table.put_item(Item={"pk": "ADMIN#CAMPAIGNS", "sk": f"CAMPAIGN#{campaign_id}", **campaign})
        table.put_item(Item={"pk": f"CAMPAIGN#{campaign_id}", "sk": "META", **campaign})
        common = {k: v for k, v in body.items() if k != "recipients"}
        common["_actor"] = actor
        for index in range(0, len(recipients), 100):
            chunk = recipients[index:index + 100]
            _enqueue_fifo(
                queue_url,
                {"source": "admin", "command": "campaign", "body": {**common, "recipients": chunk},
                 "request_id": f"{request_id}:{index // 100}"},
                f"campaign:{campaign_id}:{index // 100}",
                f"campaign:{request_id}:{campaign_id}:{index // 100}",
            )
        for key in (
            {"pk": "ADMIN#CAMPAIGNS", "sk": f"CAMPAIGN#{campaign_id}"},
            {"pk": f"CAMPAIGN#{campaign_id}", "sk": "META"},
        ):
            table.update_item(
                Key=key,
                UpdateExpression="SET #s=:s, updated_at=:u",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "QUEUED", ":u": int(time.time())},
            )
        return len(recipients)
    identity = str(body.get("user_id") or body.get("to") or body.get("phone") or request_id)
    _enqueue_fifo(
        queue_url,
        {"source": "admin", "command": "send", "body": {**body, "_actor": actor}, "request_id": request_id},
        f"whatsapp:{identity}",
        f"send:{request_id}:{identity}",
    )
    return 1


def _campaign_status(campaign: dict[str, Any], accepted_count: int, delivered_count: int,
                     response_count: int) -> dict[str, str]:
    """Derive the operational status from durable WhatsApp activity, not the enqueue flag."""
    recipients = max(0, int(campaign.get("recipient_count") or 0))
    campaign_type = str(campaign.get("campaign_type") or "informative").lower()
    has_flow = campaign_type == "survey" or bool(campaign.get("flow_ids"))
    if recipients and accepted_count < recipients:
        return {"status": "PROCESSING", "status_label": "Procesando envíos", "status_tone": "blue"}
    if has_flow:
        if recipients and response_count >= recipients:
            return {"status": "COMPLETED", "status_label": "Completada", "status_tone": "green"}
        if response_count:
            return {"status": "PARTIAL_RESPONSES", "status_label": "Respuestas parciales", "status_tone": "amber"}
        if recipients and delivered_count >= recipients:
            return {"status": "AWAITING_RESPONSES", "status_label": "Esperando respuestas", "status_tone": "blue"}
        return {"status": "SENT", "status_label": "Enviada", "status_tone": "blue"}
    if recipients and delivered_count >= recipients:
        return {"status": "COMPLETED", "status_label": "Completada", "status_tone": "green"}
    return {"status": "SENT", "status_label": "Enviada", "status_tone": "blue"}


def _campaign_items(include_deleted: bool = False) -> list[dict[str, Any]]:
    table = _ddb.Table(os.environ["STATE_TABLE"])
    rows = table.query(
        KeyConditionExpression=Key("pk").eq("ADMIN#CAMPAIGNS"), ScanIndexForward=False, Limit=100
    ).get("Items", [])
    items: list[dict[str, Any]] = []
    delivered_statuses = {"DELIVERED", "READ"}
    for row in rows:
        if bool(row.get("deleted_at")) != include_deleted:
            continue
        campaign_id = str(row.get("campaign_id") or row.get("id") or "")
        activity = table.query(
            KeyConditionExpression=Key("pk").eq(f"CAMPAIGN#{campaign_id}"), Limit=500
        ).get("Items", []) if campaign_id else []
        deliveries = [item for item in activity if str(item.get("sk") or "").startswith("OUTBOUND#")]
        responses = [item for item in activity if str(item.get("sk") or "").startswith("RESPONSE#")]
        item = {key: value for key, value in row.items() if key not in {"pk", "sk", "ttl", "actor"}}
        accepted_count = len(deliveries)
        delivered_count = sum(str(value.get("status") or "").upper() in delivered_statuses for value in deliveries)
        response_count = len(responses)
        item.update({
            "accepted_count": accepted_count,
            "delivered_count": delivered_count,
            "read_count": sum(str(value.get("status") or "").upper() == "READ" for value in deliveries),
            "response_count": response_count,
        })
        if not include_deleted:
            item.update(_campaign_status(item, accepted_count, delivered_count, response_count))
        items.append(item)
    return items


def _campaigns_response() -> dict[str, Any]:
    return _response(200, {"items": _campaign_items()})


def _responses_response(campaign_id: str) -> dict[str, Any]:
    if not campaign_id:
        return _response(200, {"campaign_id": "", "campaigns": _campaign_items(), "items": []})
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", campaign_id):
        return _response(400, {"error": "invalid_campaign_id"})
    table = _ddb.Table(os.environ["STATE_TABLE"])
    campaign = table.get_item(Key={"pk": f"CAMPAIGN#{campaign_id}", "sk": "META"}).get("Item") or {}
    if not campaign or campaign.get("deleted_at"):
        return _response(404, {"error": "campaign_not_found"})
    activity = table.query(
        KeyConditionExpression=Key("pk").eq(f"CAMPAIGN#{campaign_id}"), ScanIndexForward=False, Limit=500
    ).get("Items", [])
    rows = [row for row in activity if str(row.get("sk") or "").startswith("RESPONSE#")]
    items = [{key: value for key, value in row.items() if key not in {"pk", "sk", "ttl"}} for row in rows]
    summary = {key: value for key, value in campaign.items() if key not in {"pk", "sk", "ttl", "actor"}}
    return _response(200, {"campaign_id": campaign_id, "campaign": summary, "items": items})


def _campaign_delete_response(actor: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    campaign_id = str(body.get("campaign_id") or "").strip()
    confirmation_name = str(body.get("confirmation_name") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", campaign_id):
        return _response(400, {"error": "invalid_campaign_id"})
    table = _ddb.Table(os.environ["STATE_TABLE"])
    admin_key = {"pk": "ADMIN#CAMPAIGNS", "sk": f"CAMPAIGN#{campaign_id}"}
    campaign = table.get_item(Key=admin_key, ConsistentRead=True).get("Item") or {}
    if not campaign or campaign.get("deleted_at"):
        return _response(404, {"error": "campaign_not_found"})
    if confirmation_name != str(campaign.get("name") or "").strip():
        return _response(400, {"error": "campaign_name_confirmation_required"})
    now = int(time.time())
    values = {
        ":deleted_at": now,
        ":deleted_by": str(actor.get("agent_arn") or "")[:512],
        ":deleted_by_name": str(actor.get("name") or actor.get("username") or "Developer")[:200],
        ":updated_at": now,
    }
    for key in (admin_key, {"pk": f"CAMPAIGN#{campaign_id}", "sk": "META"}):
        table.update_item(
            Key=key,
            UpdateExpression="SET deleted_at=:deleted_at, deleted_by=:deleted_by, deleted_by_name=:deleted_by_name, updated_at=:updated_at",
            ExpressionAttributeValues=values,
        )
    logger.info(json.dumps({"event": "campaign_soft_deleted", "campaign_id": campaign_id,
                            "actor": _stable_id(str(actor.get("agent_arn") or "unknown"))}))
    return _response(200, {"campaign_id": campaign_id, "deleted": True, "recoverable": True})


def _campaign_trash_response(actor: dict[str, Any]) -> dict[str, Any]:
    if actor.get("role") != "developer":
        return _response(403, {"error": "developer_routing_required"})
    return _response(200, {"items": _campaign_items(include_deleted=True)})


def _campaign_restore_response(actor: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    if actor.get("role") != "developer":
        return _response(403, {"error": "developer_routing_required"})
    campaign_id = str(body.get("campaign_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", campaign_id):
        return _response(400, {"error": "invalid_campaign_id"})
    table = _ddb.Table(os.environ["STATE_TABLE"])
    admin_key = {"pk": "ADMIN#CAMPAIGNS", "sk": f"CAMPAIGN#{campaign_id}"}
    campaign = table.get_item(Key=admin_key, ConsistentRead=True).get("Item") or {}
    if not campaign or not campaign.get("deleted_at"):
        return _response(404, {"error": "deleted_campaign_not_found"})
    now = int(time.time())
    values = {":updated_at": now, ":restored_at": now,
              ":restored_by": str(actor.get("agent_arn") or "")[:512]}
    for key in (admin_key, {"pk": f"CAMPAIGN#{campaign_id}", "sk": "META"}):
        table.update_item(
            Key=key,
            UpdateExpression="SET updated_at=:updated_at, restored_at=:restored_at, restored_by=:restored_by REMOVE deleted_at, deleted_by, deleted_by_name",
            ExpressionAttributeValues=values,
        )
    logger.info(json.dumps({"event": "campaign_restored", "campaign_id": campaign_id,
                            "actor": _stable_id(str(actor.get("agent_arn") or "unknown"))}))
    return _response(200, {"campaign_id": campaign_id, "restored": True})


def _clean_phone(value: Any) -> str:
    phone = re.sub(r"[^0-9+]", "", str(value or "")).strip()
    digits = re.sub(r"\D", "", phone)
    return phone if 8 <= len(digits) <= 15 else ""


def _clean_segment_contact(value: dict[str, Any], index: int) -> dict[str, Any] | None:
    raw_phones = value.get("phones") or value.get("phone") or []
    if isinstance(raw_phones, str):
        raw_phones = re.split(r"[,;|\n]+", raw_phones)
    phones: list[str] = []
    for raw in raw_phones if isinstance(raw_phones, list) else []:
        phone = _clean_phone(raw)
        if phone and phone not in phones:
            phones.append(phone)
    if not phones:
        return None
    email = str(value.get("email") or "").strip().lower()[:254]
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        email = ""
    return {
        "id": str(value.get("id") or f"contact-{index + 1}")[:128],
        "name": str(value.get("name") or "").strip()[:200],
        "phones": phones[:10],
        "document_id": str(value.get("document_id") or "").strip()[:80],
        "email": email,
    }


def _segments_response(method: str, body: dict[str, Any] | None = None, segment_id: str = "") -> dict[str, Any]:
    table = _ddb.Table(os.environ["STATE_TABLE"])
    if method == "GET":
        if segment_id:
            if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", segment_id):
                return _response(400, {"error": "invalid_segment_id"})
            rows: list[dict[str, Any]] = []
            cursor = None
            while len(rows) < MAX_SEGMENT_CONTACTS + 1:
                query: dict[str, Any] = {
                    "KeyConditionExpression": Key("pk").eq(f"SEGMENT#{segment_id}"),
                    "ScanIndexForward": True,
                    "Limit": min(250, MAX_SEGMENT_CONTACTS + 1 - len(rows)),
                }
                if cursor:
                    query["ExclusiveStartKey"] = cursor
                result = table.query(**query)
                rows.extend(result.get("Items", []))
                cursor = result.get("LastEvaluatedKey")
                if not cursor:
                    break
            summary = next((row for row in rows if row.get("sk") == "META"), {})
            contacts = [
                {key: value for key, value in row.items() if key not in {"pk", "sk", "ttl"}}
                for row in rows if str(row.get("sk") or "").startswith("MEMBER#")
            ]
            if not summary:
                return _response(404, {"error": "segment_not_found"})
            return _response(200, {
                "segment": {key: value for key, value in summary.items() if key not in {"pk", "sk", "ttl", "actor"}},
                "contacts": contacts,
            })
        rows = table.query(
            KeyConditionExpression=Key("pk").eq("ADMIN#SEGMENTS"), ScanIndexForward=False, Limit=200
        ).get("Items", [])
        items = [{key: value for key, value in row.items() if key not in {"pk", "sk", "actor"}} for row in rows]
        return _response(200, {"items": items})

    payload = dict(body or {})
    name = str(payload.get("name") or "").strip()
    if not name:
        return _response(400, {"error": "segment_name_required"})
    raw_contacts = payload.get("contacts") or []
    if not isinstance(raw_contacts, list) or not 1 <= len(raw_contacts) <= MAX_SEGMENT_CONTACTS:
        return _response(400, {"error": f"segment_contacts_must_contain_between_1_and_{MAX_SEGMENT_CONTACTS}"})
    contacts = [contact for index, value in enumerate(raw_contacts) if isinstance(value, dict)
                and (contact := _clean_segment_contact(value, index))]
    if not contacts:
        return _response(400, {"error": "segment_requires_valid_phone"})

    segment_id = str(payload.get("id") or f"seg-{uuid.uuid4().hex[:16]}")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", segment_id):
        return _response(400, {"error": "invalid_segment_id"})
    now = int(time.time())
    unique_phones = {phone for contact in contacts for phone in contact["phones"]}
    field_counts = {
        "name": sum(bool(contact.get("name")) for contact in contacts),
        "phone": len(contacts),
        "document_id": sum(bool(contact.get("document_id")) for contact in contacts),
        "email": sum(bool(contact.get("email")) for contact in contacts),
    }
    summary = {
        "id": segment_id,
        "name": name[:200],
        "description": str(payload.get("description") or "").strip()[:500],
        "source": str(payload.get("source") or "manual")[:32],
        "contact_count": len(contacts),
        "phone_count": len(unique_phones),
        "available_fields": [field for field, count in field_counts.items() if count],
        "field_counts": field_counts,
        "created_at": now,
        "updated_at": now,
    }
    with table.batch_writer() as batch:
        batch.put_item(Item={"pk": "ADMIN#SEGMENTS", "sk": f"SEGMENT#{segment_id}", **summary})
        batch.put_item(Item={"pk": f"SEGMENT#{segment_id}", "sk": "META", **summary})
        for index, contact in enumerate(contacts):
            batch.put_item(Item={"pk": f"SEGMENT#{segment_id}", "sk": f"MEMBER#{index:06d}", **contact})
    return _response(200, {**summary, "contacts": contacts})


def _segment_recipients(segment_id: str, phone_strategy: str = "primary") -> list[dict[str, str]]:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", segment_id):
        raise ValueError("invalid segment_id")
    table = _ddb.Table(os.environ["STATE_TABLE"])
    rows: list[dict[str, Any]] = []
    cursor = None
    while len(rows) <= MAX_SEGMENT_CONTACTS:
        query: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(f"SEGMENT#{segment_id}"),
            "Limit": min(250, MAX_SEGMENT_CONTACTS + 1 - len(rows)),
        }
        if cursor:
            query["ExclusiveStartKey"] = cursor
        result = table.query(**query)
        rows.extend(result.get("Items", []))
        cursor = result.get("LastEvaluatedKey")
        if not cursor:
            break
    recipients: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not str(row.get("sk") or "").startswith("MEMBER#"):
            continue
        phones = row.get("phones") or []
        selected = phones if phone_strategy == "all" else phones[:1]
        for raw_phone in selected:
            phone = _clean_phone(raw_phone)
            if phone and phone not in seen:
                seen.add(phone)
                recipients.append({
                    "to": phone,
                    "customer_name": str(row.get("name") or "")[:200],
                    "document_id": str(row.get("document_id") or "")[:80],
                    "email": str(row.get("email") or "")[:254],
                })
    return recipients


def _resource_response(method: str, resource: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Small authenticated control plane for templates, surveys and their results."""
    allowed = {"templates", "surveys", "campaigns", "responses"}
    if resource not in allowed:
        return _response(404, {"error": "resource_not_found"})
    table = _ddb.Table(os.environ["STATE_TABLE"])
    pk = f"ADMIN#{resource.upper()}"
    if method == "GET":
        rows = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=200).get("Items", [])
        return _response(200, {"items": rows})
    if resource not in {"templates", "surveys"}:
        return _response(405, {"error": "method_not_allowed"})
    item = dict(body or {})
    item_id = str(item.get("id") or uuid.uuid4())
    now = int(time.time())
    item.update({"pk": pk, "sk": f"ITEM#{item_id}", "id": item_id, "updated_at": now})
    table.put_item(Item=item)
    item.pop("pk", None)
    item.pop("sk", None)
    return _response(200, item)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request = event.get("requestContext") or {}
    http = request.get("http") or {}
    method = http.get("method", "").upper()
    path = http.get("path") or event.get("rawPath") or "/"

    if method == "GET" and path.startswith("/m/"):
        return _media_redirect(path.rsplit("/", 1)[-1])

    if method == "GET" and path.endswith("/webhook/whatsapp"):
        query = event.get("queryStringParameters") or {}
        if query.get("hub.mode") == "subscribe" and hmac.compare_digest(
            query.get("hub.verify_token", ""), _secret().get("WA_VERIFY_TOKEN", "")
        ):
            return {"statusCode": 200, "body": query.get("hub.challenge", "")}
        return _response(403, {"error": "verification_failed"})

    if method == "POST" and path.endswith("/webhook/whatsapp"):
        raw = _raw_body(event)
        if not _valid_signature(raw, _header(event, "x-hub-signature-256"), _secret().get("WA_APP_SECRET", "")):
            return _response(403, {"error": "invalid_signature"})
        try:
            body = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(400, {"error": "invalid_json"})
        units = _meta_units(body)
        queue_url = os.environ.get("CONVERSATION_QUEUE_URL") or os.environ["WORK_QUEUE_URL"]
        for unit, group_id, deduplication_id in units:
            _enqueue_fifo(queue_url, {"source": "meta", "body": unit}, group_id, deduplication_id)
        return _response(200, {"accepted": True, "events": len(units)})

    if path.endswith("/admin/session") and method == "POST":
        try:
            body = json.loads(_raw_body(event))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(400, {"error": "invalid_json"})
        return _create_connect_session(event, body)

    actor = None
    if path.startswith("/admin/"):
        if not _app_origin_allowed(event):
            return _response(403, {"error": "invalid_app_origin"})
        actor = _session_actor(event)
        if not actor:
            return _response(401, {"error": "connect_session_required"})

    if path.endswith("/admin/access-profiles") and method in {"GET", "POST"}:
        body = None
        if method == "POST":
            try:
                body = json.loads(_raw_body(event))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _response(400, {"error": "invalid_json"})
        return _access_profiles_response(actor or {}, method, body)

    if path.endswith("/admin/module-permissions") and method in {"GET", "POST"}:
        body = None
        if method == "POST":
            try:
                body = json.loads(_raw_body(event))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _response(400, {"error": "invalid_json"})
        return _module_permissions_response(actor or {}, method, body)

    if path.endswith("/admin/campaign-trash") and method == "GET":
        return _campaign_trash_response(actor or {})

    if path.endswith("/admin/campaign-delete") and method == "POST":
        if not _has_module_permission(actor or {}, "campaigns", "delete"):
            return _response(403, {"error": "module_permission_required"})
        try:
            body = json.loads(_raw_body(event))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(400, {"error": "invalid_json"})
        return _campaign_delete_response(actor or {}, body)

    if path.endswith("/admin/campaign-restore") and method == "POST":
        try:
            body = json.loads(_raw_body(event))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(400, {"error": "invalid_json"})
        return _campaign_restore_response(actor or {}, body)

    if path.endswith("/admin/meta-templates") and method == "GET":
        if not any((
            _has_module_permission(actor or {}, "templates", "view"),
            _has_module_permission(actor or {}, "quotes", "view"),
            _has_module_permission(actor or {}, "campaigns", "create"),
            _has_module_permission(actor or {}, "surveys", "view"),
        )):
            return _response(403, {"error": "module_permission_required"})
        try:
            return _meta_catalog_with_cache("templates", _meta_templates_response)
        except Exception:
            return _response(502, {"error": "meta_templates_unavailable"})

    if path.endswith("/admin/meta-template-management") and method == "GET":
        if not _has_module_permission(actor or {}, "templates", "view"):
            return _response(403, {"error": "module_permission_required"})
        try:
            return _meta_templates_response(include_pending=True)
        except Exception:
            logger.exception(json.dumps({"event": "meta_template_management_unavailable"}))
            return _response(502, {"error": "meta_templates_unavailable"})

    if path.endswith("/admin/meta-flows") and method == "GET":
        if not any((
            _has_module_permission(actor or {}, "surveys", "view"),
            _has_module_permission(actor or {}, "campaigns", "create"),
        )):
            return _response(403, {"error": "module_permission_required"})
        try:
            return _meta_catalog_with_cache("flows", _meta_flows_response)
        except Exception:
            return _response(502, {"error": "meta_flows_unavailable"})

    if path.endswith("/admin/meta-flows") and method == "POST":
        if not _has_module_permission(actor or {}, "surveys", "manage"):
            return _response(403, {"error": "module_permission_required"})
        try:
            body = json.loads(_raw_body(event))
            return _meta_flow_command(actor or {}, body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(400, {"error": "invalid_json"})
        except ValueError as exc:
            return _response(400, {"error": str(exc)})
        except RuntimeError as exc:
            logger.warning(json.dumps({"event": "meta_flow_command_rejected", "message": str(exc)[:500]}))
            return _response(502, {"error": "meta_flow_operation_failed", "message": str(exc)})

    if path.endswith("/admin/meta-templates") and method == "POST":
        if not _has_module_permission(actor or {}, "templates", "manage"):
            return _response(403, {"error": "module_permission_required"})
        try:
            body = json.loads(_raw_body(event))
            return _meta_template_command(actor or {}, body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(400, {"error": "invalid_json"})
        except ValueError as exc:
            return _response(400, {"error": str(exc)})
        except RuntimeError as exc:
            logger.warning(json.dumps({"event": "meta_template_command_rejected", "message": str(exc)[:500]}))
            return _response(502, {"error": "meta_template_operation_failed", "message": str(exc)})

    if path.startswith("/admin/") and method in {"GET", "POST"}:
        resource = path.rsplit("/", 1)[-1]
        if method == "GET" or resource in {"templates", "surveys", "segments"}:
            body = None
            action = "view" if method == "GET" else "manage"
            if resource == "segments" and method == "POST":
                try:
                    body = json.loads(_raw_body(event))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return _response(400, {"error": "invalid_json"})
                action = "import" if str(body.get("source") or "").lower() == "file" else "create"
            if resource not in MODULE_ACTIONS or not _has_module_permission(actor or {}, resource, action):
                return _response(403, {"error": "module_permission_required"})
            if method == "POST" and body is None:
                try:
                    body = json.loads(_raw_body(event))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return _response(400, {"error": "invalid_json"})
            if resource == "campaigns" and method == "GET":
                return _campaigns_response()
            if resource == "responses" and method == "GET":
                query = event.get("queryStringParameters") or {}
                return _responses_response(str(query.get("campaign_id") or ""))
            if resource == "segments":
                query = event.get("queryStringParameters") or {}
                return _segments_response(method, body, str(query.get("segment_id") or ""))
            return _resource_response(method, resource, body)

    if method == "POST" and path.startswith("/admin/"):
        try:
            body = json.loads(_raw_body(event))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(400, {"error": "invalid_json"})
        command = path.rsplit("/", 1)[-1]
        if command == "upload":
            if not _has_module_permission(actor or {}, "quotes", "send"):
                return _response(403, {"error": "module_permission_required"})
            filename = str(body.get("filename") or "archivo.bin").replace("/", "_").replace("\\", "_")[:180]
            content_type = str(body.get("content_type") or "application/octet-stream")[:255]
            key = f"outbound/{time.strftime('%Y/%m/%d')}/{int(time.time())}-{filename}"
            url = _s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": os.environ["MEDIA_BUCKET"], "Key": key, "ContentType": content_type,
                    "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": os.environ["KMS_KEY_ARN"],
                },
                ExpiresIn=900,
            )
            return _response(200, {
                "s3_key": key, "upload_url": url,
                "headers": {"content-type": content_type, "x-amz-server-side-encryption": "aws:kms",
                            "x-amz-server-side-encryption-aws-kms-key-id": os.environ["KMS_KEY_ARN"]},
                "expires_in": 900,
            })
        if command not in {"send", "campaign", "quote"}:
            return _response(404, {"error": "unknown_command"})
        if command == "send" and body.get("template") and body.get("media"):
            command = "quote"
        module, action = ("quotes", "send") if command in {"send", "quote"} else ("campaigns", "send")
        if not _has_module_permission(actor or {}, module, action):
            return _response(403, {"error": "module_permission_required"})
        request_id = str(request.get("requestId") or int(time.time() * 1000))
        try:
            accepted = _enqueue_admin(command, body, request_id, {
                "subject": str((actor or {}).get("agent_arn") or ""),
                "username": str((actor or {}).get("username") or ""),
                "role": str((actor or {}).get("role") or ""),
            })
        except ValueError as exc:
            return _response(400, {"error": str(exc)})
        return _response(202, {"accepted": True, "messages": accepted})

    return _response(404, {"error": "not_found"})
