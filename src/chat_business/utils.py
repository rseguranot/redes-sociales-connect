"""Utilidades de texto, extractores de campos y limpieza de respuestas de agentes."""
from typing import Any, Dict, List
import json
import os
import re
import time
import unicodedata
from config import TRANSFER_TAG_REGEX, CLOSE_TAG_REGEX, AUTOGESTION_COMPLETADA_PATTERNS, USER_CLOSE_PATTERNS, NEGATIVE_AFTER_HELP_PATTERNS, HELP_QUESTION_HINTS, AGENT_REQUEST_PATTERNS, AGENT_HANDOFF_PATTERNS, AGENT_CLOSE_PATTERNS, PRODUCT_CLARIFICATION_QUESTIONS, CASE_REGEX, GENERIC_NUMBER_REGEX, DIGITS_REGEX, bedrock_runtime, NOVA_MICRO_MODEL, COMPLAINT_FIELD_NAMES, ACTION_INPUT_KEY, OTROS_MENU_PATTERNS

def _norm(text: str) -> str:
    return re.sub('\\s+', ' ', (text or '').strip())

def _strip_accents(text: str) -> str:
    if not text:
        return ''
    return ''.join((ch for ch in unicodedata.normalize('NFD', text) if unicodedata.category(ch) != 'Mn'))

def _low(text: str) -> str:
    return _norm(text).lower()

def _low_ascii(text: str) -> str:
    return _strip_accents(_low(text))

def _has_value(v: Any) -> bool:
    return v is not None and str(v).strip() != ''

def _matches_any(text: str, patterns: List[str]) -> bool:
    t = _low_ascii(text)
    return any((re.search(pattern, t) for pattern in patterns))

def _emit_functional_metric(metric_name: str, failure_type: str='') -> None:
    """Emite una metrica EMF de baja cardinalidad y sin datos del cliente."""
    try:
        safe_metric_name = re.sub('[^A-Za-z0-9_]', '', metric_name or '')
        if not safe_metric_name:
            return
        function_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'local')
        stage = os.environ.get('APP_ENV', 'dev' if function_name.endswith('_dev') else 'unknown')
        payload = {'_aws': {'Timestamp': int(time.time() * 1000), 'CloudWatchMetrics': [{'Namespace': 'PlazaLama/ClaimsRequest', 'Dimensions': [['FunctionName', 'Stage']], 'Metrics': [{'Name': safe_metric_name, 'Unit': 'Count'}]}]}, 'FunctionName': function_name, 'Stage': stage, safe_metric_name: 1}
        if failure_type:
            payload['FailureType'] = re.sub('[^A-Za-z0-9_.-]', '_', failure_type)[:80]
        print(json.dumps(payload, ensure_ascii=True, separators=(',', ':')))
    except Exception as error:
        print('FUNCTIONAL METRIC ERROR:', type(error).__name__)

def _extract_transfer_tag(text: str) -> str:
    match = TRANSFER_TAG_REGEX.search(text or '')
    return match.group(1).lower() if match else ''

def _extract_close_tag(text: str) -> bool:
    return bool(CLOSE_TAG_REGEX.search(text or ''))

def _strip_transfer_tag(text: str) -> str:
    return _norm(TRANSFER_TAG_REGEX.sub('', text or ''))

def _strip_all_tags(text: str) -> str:
    return _norm(CLOSE_TAG_REGEX.sub('', _strip_transfer_tag(text)))

def _clean_agent_text(text: str) -> str:
    msg = _norm(text)
    msg = re.sub('^Thought:\\s*', '', msg, flags=re.IGNORECASE)
    msg = re.sub('^<answer>\\s*', '', msg, flags=re.IGNORECASE)
    msg = re.sub('\\s*</answer>$', '', msg, flags=re.IGNORECASE)
    msg = re.sub('^<response>\\s*', '', msg, flags=re.IGNORECASE)
    msg = re.sub('\\s*</response>$', '', msg, flags=re.IGNORECASE)
    msg = re.sub('<thinking>.*?</thinking>', '', msg, flags=re.IGNORECASE | re.DOTALL)
    msg = re.sub('<reasoning>.*?</reasoning>', '', msg, flags=re.IGNORECASE | re.DOTALL)
    return _norm(msg)

def _agent_completed_task_by_patterns(text: str) -> bool:
    return _matches_any(text, AUTOGESTION_COMPLETADA_PATTERNS)

def _looks_like_help_question(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in HELP_QUESTION_HINTS))

def _is_negative_after_help(text: str) -> bool:
    t = _low_ascii(text)
    return any((re.search(p, t) for p in NEGATIVE_AFTER_HELP_PATTERNS))

def _user_wants_close(text: str) -> bool:
    return _matches_any(text, USER_CLOSE_PATTERNS)

def _user_wants_agent(text: str) -> bool:
    return _matches_any(text, AGENT_REQUEST_PATTERNS)

def _is_otros_menu(text: str) -> bool:
    return _matches_any(text, OTROS_MENU_PATTERNS)

def _agent_is_handoff(text: str) -> bool:
    return _matches_any(text, AGENT_HANDOFF_PATTERNS)

def _agent_is_close(text: str) -> bool:
    return _matches_any(text, AGENT_CLOSE_PATTERNS)

def _was_product_clarification_question(text: str) -> bool:
    t = _low_ascii(text)
    if 'producto comprado en plaza lama' in t and any((hint in t for hint in ['queja', 'reclamacion', 'reclamo', 'situacion'])):
        return True
    return any((_low_ascii(q) in t for q in PRODUCT_CLARIFICATION_QUESTIONS))

def _normalized_clarification_answer(text: str) -> str:
    t = _low_ascii(text)
    t = re.sub('^\\s*(?:cliente(?:\\s+whatsapp|\\s+chat|\\s+web)?|whatsapp|usuario|customer|user)\\s*:\\s*', '', t)
    t = re.sub('^(?:(?:um+|uh+|eh+|em+|mmm+|ah+|bueno|pues|este)\\b[\\s,.;]*)+', '', t)
    return _norm(re.sub('[^a-z0-9\\s]', ' ', t))

def _is_yes_to_product_clarification(text: str) -> bool:
    t = _normalized_clarification_answer(text)
    yes_values = {'si', 'claro', 'correcto', 'asi es', 'si claro', 'afirmativo', 'exacto'}
    if t in yes_values:
        return True
    return _matches_any(text, ['\\btiene que ver con un producto\\b', '\\bes por una compra\\b', '\\bes por algo que compre\\b', '\\bcompre algo\\b', '\\bproducto\\b', '\\bfactura\\b', '\\bgarantia\\b', '\\bdevolucion\\b', '\\bentrega\\b', '\\binstalacion\\b', '\\bdañado\\b', '\\bdefectuoso\\b', '\\baveriado\\b', '\\broto\\b', '\\brayado\\b', '\\babollado\\b'])

def _is_no_to_product_clarification(text: str) -> bool:
    t = _normalized_clarification_answer(text)
    no_values = {'no', 'no gracias', 'no aplica', 'negativo', 'para nada'}
    if t in no_values:
        return True
    return _matches_any(text, ['\\bno tiene que ver con un producto\\b', '\\bno es por producto\\b', '\\bno es por una compra\\b', '\\bno compre nada\\b', '\\bes por el trato\\b', '\\bes por un empleado\\b', '\\bes por el servicio\\b', '\\bes por seguridad\\b', '\\bes por el gerente\\b', '\\bfue en la tienda\\b', '\\bme trataron mal\\b', '\\btuve un incidente\\b'])

def _quick_product_clarification_prompt(text: str) -> str:
    t = _low_ascii(text)
    if any((p in t for p in ['tengo una queja', 'quiero poner una queja', 'quiero hacer una queja', 'necesito poner una queja'])):
        return '¿La queja tiene que ver con un producto comprado en Plaza Lama?'
    if any((p in t for p in ['tengo una reclamacion', 'quiero hacer una reclamacion', 'quiero poner una reclamacion', 'quiero reclamar', 'tengo un reclamo'])):
        return '¿La reclamación tiene que ver con un producto comprado en Plaza Lama?'
    if any((p in t for p in ['tengo un problema', 'quiero reportar algo', 'necesito ayuda con un problema'])):
        return '¿La situación tiene que ver con un producto comprado en Plaza Lama?'
    return ''

def _extract_case_number_from_text(text: str) -> str:
    match = CASE_REGEX.search(text or '')
    return match.group(0) if match else ''

def _extract_document_from_text(text: str, keyword: str) -> str:
    low = _low_ascii(text)
    if keyword not in low:
        return ''
    match = DIGITS_REGEX.search(text or '')
    if match:
        return match.group(0)
    search_text = _strip_accents(text or '')
    keyword_match = re.search(f'{keyword}(?:\\s*(?:numero|no\\.?|num\\.?|es|:))?\\s*([A-Za-z0-9]{{5,20}})', search_text, flags=re.IGNORECASE)
    if keyword_match:
        return _norm(keyword_match.group(1))
    return ''

def _extract_pasaporte_from_text(text: str) -> str:
    low = _low_ascii(text)
    if 'pasaporte' not in low:
        return ''
    match = re.search('pasaporte(?:\\s*(?:numero|número|no\\.?|num\\.?|es|:))?\\s*([A-Za-z0-9]{5,20})', text or '', flags=re.IGNORECASE)
    if match:
        candidate = _norm(match.group(1))
        if _low_ascii(candidate) not in {'pasaporte', 'numero', 'número'}:
            return candidate
    for candidate in GENERIC_NUMBER_REGEX.findall(text or ''):
        clean = _norm(candidate)
        if _low_ascii(clean) not in {'pasaporte', 'numero', 'número'}:
            return clean
    return ''

def _extract_loose_claim_document(text: str) -> str:
    clean = _norm(text)
    for candidate in GENERIC_NUMBER_REGEX.findall(clean):
        value = _norm(candidate)
        if re.search('\\d', value) and len(re.sub('\\W+', '', value)) >= 5:
            return value
    digits = re.sub('\\D+', '', clean)
    if len(digits) >= 5:
        return digits
    return ''
SPANISH_DIGIT_WORDS = {'cero': '0', 'uno': '1', 'un': '1', 'una': '1', 'dos': '2', 'tres': '3', 'cuatro': '4', 'cinco': '5', 'seis': '6', 'siete': '7', 'ocho': '8', 'nueve': '9'}

def _extract_digits_from_spoken_text(text: str) -> str:
    normalized = _low_ascii(text)
    tokens = re.findall('[a-z0-9]+', normalized)
    result: List[str] = []
    for token in tokens:
        if token.isdigit():
            result.append(token)
        elif token in SPANISH_DIGIT_WORDS:
            result.append(SPANISH_DIGIT_WORDS[token])
    return ''.join(result)

def _extract_phone_from_text(text: str) -> str:
    direct_digits = re.sub('\\D+', '', text or '')
    if len(direct_digits) >= 7:
        return direct_digits[-10:] if len(direct_digits) >= 10 else direct_digits
    spoken_digits = _extract_digits_from_spoken_text(text)
    if len(spoken_digits) >= 7:
        return spoken_digits[-10:] if len(spoken_digits) >= 10 else spoken_digits
    return ''

def _extract_name_from_text(text: str) -> str:
    clean = _norm(text)
    clean = re.sub('^(mi nombre es|me llamo|soy|nombre es|yo soy)\\s+', '', clean, flags=re.IGNORECASE)
    return _norm(clean)

def _extract_action_input(session_attrs: Dict[str, str], request_attrs: Dict[str, str]) -> Dict[str, Any]:
    for raw in [request_attrs.get(ACTION_INPUT_KEY, ''), session_attrs.get(ACTION_INPUT_KEY, '')]:
        if not _has_value(raw):
            continue
        try:
            return json.loads(raw)
        except Exception as e:
            pass
    return {}

def _extract_fields_from_action_input(session_attrs: Dict[str, str], request_attrs: Dict[str, str]) -> Dict[str, str]:
    payload = _extract_action_input(session_attrs, request_attrs)
    result: Dict[str, str] = {}

    def _collect(items: Any):
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _norm(str(item.get('name', '')))
            value = item.get('value')
            if name in COMPLAINT_FIELD_NAMES and _has_value(value):
                result[name] = _norm(str(value))
    _collect(payload.get('parameters', []))
    request_body = payload.get('requestBody', {})
    if isinstance(request_body, dict):
        for _, items in request_body.items():
            _collect(items)
    return result

def _get_action_body_value(payload: Dict[str, Any], field_name: str) -> str:
    expected = _low_ascii(field_name)

    def _find_in_items(items: Any) -> str:
        if not isinstance(items, list):
            return ''
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _low_ascii(str(item.get('name', '')))
            value = item.get('value')
            if name == expected and _has_value(value):
                return _norm(str(value))
        return ''
    value = _find_in_items(payload.get('parameters', []))
    if _has_value(value):
        return value
    request_body = payload.get('requestBody', {})
    if isinstance(request_body, dict):
        for _, items in request_body.items():
            value = _find_in_items(items)
            if _has_value(value):
                return value
    return ''
_ENGLISH_REASONING_LEADIN = re.compile("^(we need to|we should|we must|i need to|i should|let me|i will|i'll|the user|based on|according to|as per|here is|note that|first,? i)\\b", re.IGNORECASE)

def _strip_leaked_english_reasoning(text: str) -> str:
    """gpt-oss filtra su razonamiento interno en inglés pegado al español sin espacio."""
    if not text:
        return text
    match = re.search('\\.([A-Z])', text)
    if not match:
        return text
    prefix = text[:match.start() + 1]
    has_non_ascii = any((ord(ch) > 127 for ch in prefix))
    if _ENGLISH_REASONING_LEADIN.search(prefix.strip()) and (not has_non_ascii):
        return text[match.start() + 1:].lstrip()
    return text

def _strip_message_tags(text: str, strip_control_tags: bool=True) -> str:
    raw = text or ''
    raw = _strip_leaked_english_reasoning(raw)
    _DEEPSEEK_CUTOFF = ('</answer', '</assistant', '<|', '<reasoning>', '<thinking>')
    for marker in _DEEPSEEK_CUTOFF:
        idx = raw.find(marker)
        if idx > 8:
            raw = raw[:idx]
            break
        if idx == 0:
            raw = re.sub(re.escape(marker) + '.*?>' if marker.startswith('<|') else re.escape(marker), '', raw, count=1, flags=re.DOTALL)
    raw = re.sub('<reasoning>.*?</reasoning>', '', raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub('<thinking>.*?</thinking>', '', raw, flags=re.IGNORECASE | re.DOTALL)
    message_matches = re.findall('<message>(.*?)</message>', raw, flags=re.IGNORECASE | re.DOTALL)
    if message_matches:
        raw = ' '.join(message_matches)
    raw = re.sub('</?message>', '', raw, flags=re.IGNORECASE)
    raw = re.sub('</?answer>', '', raw, flags=re.IGNORECASE)
    raw = re.sub('</?response>', '', raw, flags=re.IGNORECASE)
    clean = _clean_agent_text(raw)
    return _strip_all_tags(clean) if strip_control_tags else _norm(clean)

def _read_bedrock_agent_completion(response: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for event in response.get('completion', []):
        if not isinstance(event, dict):
            continue
        if 'chunk' in event:
            data = event['chunk'].get('bytes', b'')
            chunks.append(data.decode('utf-8', errors='ignore') if isinstance(data, bytes) else str(data))
        elif 'returnControl' in event:
            pass
    return _strip_message_tags(''.join(chunks), strip_control_tags=False)

def _classify_with_nova(transcript: str) -> str:
    """Clasifica el mensaje del cliente usando Nova Micro. Devuelve: quejas/reclamaciones/consulta/general."""
    try:
        prompt_text = f'''Eres un clasificador de intenciones para el servicio al cliente de Plaza Lama (supermercado RD). Clasifica el mensaje del cliente en exactamente una de estas categorias:\n- quejas: mal trato, empleado grosero, mala atencion, incidente con personal, queja formal\n- reclamaciones: producto danado, garantia, devolucion, reclamo, numero de caso, cedula, RNC, factura de reclamo\n- consulta: el cliente quiere verificar el estado de una FACTURA o ENTREGA ya realizada y menciona palabras como factura, numero de factura, estado de mi factura, estado de mi pedido, seguimiento de entrega, consultar factura, numero de orden. SOLO si hay contexto de factura o entrega concreta.\n- general: preguntas generales, disponibilidad de productos, catalogo, precios, horarios, sucursales, saludos, o frases vagas como 'tengo una consulta', 'tengo una pregunta', 'quiero hacer una consulta' SIN mencionar factura o entrega.\n\nREGLA CLAVE 1: preguntas como 'tienen X?', 'venden Y?', 'cuanto cuesta X' son SIEMPRE general.\nREGLA CLAVE 2: 'tengo una consulta' o 'quiero hacer una consulta' SIN mencionar factura o entrega es SIEMPRE general.\nREGLA CLAVE 3: solo clasifica como 'consulta' si el cliente menciona factura, numero de orden, o estado de una entrega concreta.\n\nMensaje: "{transcript}"\n\nResponde SOLAMENTE con una de estas palabras: quejas, reclamaciones, consulta, o general'''
        body = json.dumps({'messages': [{'role': 'user', 'content': [{'text': prompt_text}]}]})
        resp = bedrock_runtime.invoke_model(modelId=NOVA_MICRO_MODEL, body=body)
        result = json.loads(resp['body'].read())
        text = result['output']['message']['content'][0]['text'].strip().lower()
        for intent in ('quejas', 'reclamaciones', 'consulta'):
            if intent in text:
                return intent
    except Exception as exc:
        pass
    return 'general'
