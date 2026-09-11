"""Chat presentation around a version-pinned business hook. Never log content."""
import copy
import json
import os
import re
import unicodedata
from datetime import date

import boto3
from botocore.config import Config

client = boto3.client("lambda", config=Config(
    connect_timeout=3, read_timeout=50,
    retries={"total_max_attempts": 1, "mode": "standard"},
))


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c)).strip(" .!?¿¡")


def template(body, question, options):
    # Only application-owned option labels become instructions in the DSL.
    body = re.sub(r"(?m)^\s*\[", "(", body)
    return "\n".join(["[plantilla]", "[informacion]", body,
                      "[pregunta]", question] +
                     ["[opcion] " + option for option in options])


PRODUCT_KEYS = ("chat_product_active", "chat_product_brand", "chat_product_size",
                "chat_product_branch", "chat_product_model", "chat_product_technology")
BRANCH_NAMES = {"27 de febrero": "27 de Febrero", "herrera": "Herrera",
                "la romana": "La Romana", "duarte": "Duarte",
                "santiago": "Santiago", "bavaro": "Bávaro",
                "carretera mella": "Carretera Mella",
                "nicolas de ovando": "Nicolás de Ovando"}
TV_BRANDS = {"lg", "samsung", "sony", "tcl", "hisense", "panasonic",
             "sankey", "sharp", "tecnomaster", "toshiba"}


def chat_reply(event, text):
    state = copy.deepcopy(event.get("sessionState", {}))
    state["dialogAction"] = {"type": "ElicitIntent"}
    state.pop("intent", None)
    attrs = state.setdefault("sessionAttributes", {})
    attrs["last_agent_response"] = text
    attrs["bedrock_last_response"] = text
    return {"sessionState": state,
            "messages": [{"contentType": "PlainText", "content": text}]}


def product_context(event):
    """Own the bounded TV price dialogue; leave business/agent intents to the hook.

    Store only extracted product fields, never an unrestricted transcript. Branch
    context is not evidence of branch inventory: the legacy catalog is global.
    """
    attrs = event.setdefault("sessionState", {}).setdefault("sessionAttributes", {})
    text = event.get("inputTranscript") or event.get("rawInputTranscript") or ""
    norm = normalized(text)
    active = attrs.get("chat_product_active") == "true"
    if norm in {"informacion general", "pregunta general"}:
        for key in PRODUCT_KEYS:
            attrs.pop(key, None)
        return chat_reply(event, template(
            "Puedo ayudarte con productos, precios, promociones, sucursales y horarios.",
            "¿Qué deseas consultar? También puedes escribir tu pregunta.",
            ["Consultar producto", "Sucursales", "Promociones"]))
    if norm == "consultar producto":
        return chat_reply(event, "¿Qué producto buscas? Puedes indicar marca, modelo o características.")
    if norm in {"menu", "menu principal", "otra consulta", "otro producto"}:
        for key in PRODUCT_KEYS:
            attrs.pop(key, None)
        for key in ("qconnect_last_query", "qconnect_context_kind", "branch_pending_query",
                    "chat_pending_action"):
            attrs.pop(key, None)
        attrs["qconnect_context_active"] = "false"
        attrs["branch_lookup_pending"] = "false"
        return chat_reply(event, template(
            "Puedes elegir una opción o escribir tu consulta libremente.",
            "¿Cómo podemos ayudarte?", ["Información general", "Estatus de mi pedido",
                "Tengo una reclamación", "Tengo una queja", "Hablar con un agente"]))
    # Explicit topic changes must never be rewritten as product searches.
    if re.search(r"\b(agente|representante|reclamacion|queja|garantia|devolucion|pedido|factura|adios|cancelar|horario|direccion|ubicacion)\b", norm):
        for key in PRODUCT_KEYS:
            attrs.pop(key, None)
        return None
    tv = bool(re.search(r"\b(televisor(?:es)?|tv|tele)\b", norm))
    price = bool(re.search(r"\b(precio|cuesta|cuestan|vale|valen|comprar|busco|quiero|tienen|disponible)\b", norm))
    brand = next((b for b in sorted(TV_BRANDS) if re.search(rf"\b{b}\b", norm)), "")
    size_match = re.search(r'\b(\d{2,3})\s*(?:pulgadas?|pulg|["”])', norm)
    if active and re.fullmatch(r"(?:de )?\d{2,3}", norm):
        size_match = re.search(r"(\d+)", norm)
    model = re.search(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9-]{2,24}\b", norm)
    technology = re.search(r"\b(oled|qled|led|nanocell)\b", norm)
    branch = next((label for name, label in BRANCH_NAMES.items()
                   if re.search(rf"\b{re.escape(name)}\b", norm)), "")
    options = norm in {"ver opciones", "mostrar opciones", "no se", "cualquiera"}
    followup = active and (brand or size_match or model or technology or branch or options or
                          norm in {"el precio", "cuanto cuesta", "y el precio"})
    if not ((tv and (price or active)) or followup):
        if active:
            for key in PRODUCT_KEYS:
                attrs.pop(key, None)
        return None
    attrs["chat_product_active"] = "true"
    if brand:
        if attrs.get("chat_product_brand") != brand.upper():
            attrs.pop("chat_product_model", None)
        attrs["chat_product_brand"] = brand.upper()
    if model:
        attrs["chat_product_model"] = model[0].upper()
    if technology:
        attrs["chat_product_technology"] = technology[0].upper()
    if size_match and 10 <= int(size_match[1]) <= 120:
        attrs["chat_product_size"] = size_match[1]
    if branch:
        attrs["chat_product_branch"] = branch
    subject = "un televisor" + (" " + attrs["chat_product_brand"] if attrs.get("chat_product_brand") else "")
    location = ("\n\nSucursal indicada: *" + attrs["chat_product_branch"] + "*."
                if attrs.get("chat_product_branch") else "")
    if not attrs.get("chat_product_size") and not attrs.get("chat_product_model") and not options:
        return chat_reply(event, template(
            "Buscas el precio de *" + subject + "*." + location,
            "¿De cuántas pulgadas lo necesitas? Puedes escribir la medida o ver opciones.",
            ["Ver opciones", "Otra consulta", "Hablar con un agente"]))
    # The pinned hook incorrectly matches only the plural Spanish TV category.
    # Canonicalize the category, preserving brand/size across short replies.
    query = "precio televisores"
    if attrs.get("chat_product_brand"):
        query += " " + attrs["chat_product_brand"]
    if attrs.get("chat_product_size"):
        query += " " + attrs["chat_product_size"] + " pulgadas"
    for key in ("chat_product_model", "chat_product_technology"):
        if attrs.get(key):
            query += " " + attrs[key]
    event["inputTranscript"] = query
    event["rawInputTranscript"] = query
    attrs["branch_lookup_pending"] = "false"
    attrs["branch_pending_query"] = ""
    return None


def prepare(event):
    event = copy.deepcopy(event)
    attrs = event.setdefault("sessionState", {}).setdefault("sessionAttributes", {})
    text = event.get("inputTranscript") or event.get("rawInputTranscript") or ""
    pending = attrs.pop("chat_pending_action", "")
    branch = attrs.get("branch_last_code", "")
    if normalized(text) in {"ver direccion", "ver horario"} and branch:
        event["inputTranscript"] = ("dirección de " if normalized(text) == "ver direccion" else "horario de ") + branch
        event["rawInputTranscript"] = event["inputTranscript"]
        attrs["branch_lookup_pending"] = "false"
        attrs["branch_pending_query"] = ""
    if normalized(text) in {"si", "claro", "por favor", "si por favor", "ver horario"} and pending == "branch_hours" and branch:
        event["inputTranscript"] = "horario de " + branch
        event["rawInputTranscript"] = event["inputTranscript"]
        attrs["branch_lookup_pending"] = "false"
        attrs["branch_pending_query"] = ""
    if normalized(text) == "otra sucursal":
        event["inputTranscript"] = "sucursales"
        attrs["branch_last_code"] = ""
        attrs["branch_lookup_pending"] = "false"
        attrs["branch_pending_query"] = ""
    return event


def expired_promotion(text, today=None):
    today = today or date.today()
    match = re.search(r"hasta\s+(\d{1,2})-([A-Z]{3})-(\d{2,4})", text, re.I)
    if not match:
        return False
    months = {m: i for i, m in enumerate(
        ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"], 1)}
    try:
        year = int(match[3]); year += 2000 if year < 100 else 0
        return date(year, months[match[2].upper()], int(match[1])) < today
    except (ValueError, KeyError):
        return False


def present(text, attrs):
    if text.lstrip().startswith("[plantilla]"):
        return text
    if expired_promotion(text):
        return template(
            "La promoción encontrada *ya venció*. No puedo confirmar una oferta vigente con esa información.",
            "¿Cómo deseas continuar?", ["Consultar producto", "Hablar con un agente"])
    if "PercentageDiscount" in text or "Diferencia total:" in text:
        return "No tengo información comercial suficientemente clara para confirmar esa promoción.\n\n¿Qué producto deseas consultar?"
    clean = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", text).strip()
    # Keep the exact facts; only split existing clauses for mobile reading.
    clean = re.sub(r";\s*(domingo\b)", r"\n- \1", clean, flags=re.I)
    clean = re.sub(r"\s+(¿?(?:Deseas|Desea|Te interesa|Buscas|Qué|Cual|Cuál)\b)", r"\n\n\1", clean)
    norm = normalized(text)
    if "el cliente quiere consultar" in norm and "factura" in norm:
        return "Para consultar el estatus de tu pedido, necesito el *número de factura*.\n\n¿Lo tienes a mano?"
    if "tiene que ver con un producto comprado" in norm:
        return template("Para orientarte correctamente:", text, ["Sí", "No"])
    if "deseas consultar el horario" in norm and attrs.get("branch_last_code"):
        attrs["chat_pending_action"] = "branch_hours"
        body = re.split(r"¿?Deseas consultar el horario", clean, flags=re.I)[0].strip()
        return template("📍 " + body, "¿Deseas ver el horario de esta sucursal?", ["Ver horario", "Otra sucursal"])
    if "el horario de " in norm:
        match = re.match(r"El horario de (.+?) es (.+)", clean, re.S)
        if match:
            details = re.split(r"¿?Deseas consultar otra cosa", match[2], flags=re.I)[0].strip()
            return template("🕒 *" + match[1] + "*\n\n- " + details,
                            "¿Necesitas algo más?", ["Ver dirección", "Otra sucursal", "Otra consulta"])
    if "hay varias sucursales que coinciden:" in norm:
        return clean
    if "tenemos varias sucursales. puedo ayudarte con" in norm:
        return template("📍 Elige una sucursal o escribe su nombre.", "¿Cuál deseas consultar?",
                        ["Duarte", "Herrera", "27 de Febrero", "Carretera Mella", "Nicolás de Ovando", "Santiago", "La Romana", "Bávaro"])
    if "pesos dominicanos" in norm:
        clean = re.sub(r"(\d[\d,.]*) pesos dominicanos", r"*RD$ \1*", clean)
    return clean


def adapt(response, event):
    attrs = response.setdefault("sessionState", {}).setdefault("sessionAttributes", {})
    source_attrs = event.get("sessionState", {}).get("sessionAttributes", {})
    for key in PRODUCT_KEYS:
        if key in source_attrs:
            attrs[key] = source_attrs[key]
    action = response["sessionState"].get("dialogAction", {}).get("type")
    for message in response.get("messages", []):
        if message.get("contentType") == "PlainText" and action != "Close":
            message["content"] = present(message.get("content", ""), attrs)
            if source_attrs.get("chat_product_active") == "true":
                content = message["content"]
                if "sucursal exacta" in normalized(content):
                    content = "No pude confirmar un precio para ese televisor con la información disponible."
                if source_attrs.get("chat_product_branch"):
                    content += ("\n\nSucursal indicada: *" + source_attrs["chat_product_branch"] +
                                "*. La disponibilidad y el precio en esa sucursal aún requieren confirmación.")
                message["content"] = content
    return response


def lambda_handler(event, context):
    prepared = prepare(event)
    reply = product_context(prepared)
    if reply is not None:
        return reply
    result = client.invoke(FunctionName=os.environ["BUSINESS_HOOK_ARN"],
                           InvocationType="RequestResponse",
                           Payload=json.dumps(prepared, ensure_ascii=False).encode("utf-8"))
    with result["Payload"] as stream:
        response = json.loads(stream.read())
    if result.get("FunctionError"):
        raise RuntimeError("business_hook_failed")
    return adapt(response, prepared)
