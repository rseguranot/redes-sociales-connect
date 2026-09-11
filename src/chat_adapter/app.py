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
    action = response["sessionState"].get("dialogAction", {}).get("type")
    for message in response.get("messages", []):
        if message.get("contentType") == "PlainText" and action != "Close":
            message["content"] = present(message.get("content", ""), attrs)
    return response


def lambda_handler(event, context):
    prepared = prepare(event)
    result = client.invoke(FunctionName=os.environ["BUSINESS_HOOK_ARN"],
                           InvocationType="RequestResponse",
                           Payload=json.dumps(prepared, ensure_ascii=False).encode("utf-8"))
    with result["Payload"] as stream:
        response = json.loads(stream.read())
    if result.get("FunctionError"):
        raise RuntimeError("business_hook_failed")
    return adapt(response, prepared)
