"""Lógica de negocio: sesión, respuestas Lex, Bedrock, Amazon Q y todos los flujos."""
from datetime import date
from typing import Any, Dict, List
import json
import re
from botocore.exceptions import ClientError
from config import INTENT_AMAZON_Q, INTENT_CERRAR, ROUTE_ATTR, ROUTE_AMAZON_Q, ROUTE_BEDROCK_SUPERVISOR, ROUTE_AGENT_TRANSFER, ROUTE_CLOSED, BEDROCK_SESSION_ATTR, BEDROCK_SESSION_PREFIX, INTENT_AGENT_MAP, LEX_INTENT_ROUTING, SEARCH_RESPONSE_KEY, Q_RESPONSE_KEY, BRANCH_ALIASES, BRANCH_DIRECTORY, BEDROCK_ROUTE_PATTERNS, GENERAL_PATTERNS, BRANCH_GENERAL_INFO_PATTERNS, VAGUE_GENERAL_START_PATTERNS, EXPLICIT_NEW_REQUEST_PATTERNS, CLAIM_PATTERNS, STATUS_PATTERNS, COMPLAINT_PATTERNS, COMPLAINT_FIELD_NAMES, CONSULTA_FACTURA_PATTERNS, bedrock_intent_runtime, qconnect_client, QCONNECT_ASSISTANT_ID, QCONNECT_ASSOCIATION_ID
from utils import _norm, _low_ascii, _has_value, _matches_any, _extract_transfer_tag, _extract_close_tag, _strip_transfer_tag, _strip_all_tags, _agent_completed_task_by_patterns, _clean_agent_text, _looks_like_help_question, _is_negative_after_help, _user_wants_close, _user_wants_agent, _agent_is_handoff, _agent_is_close, _is_otros_menu, _emit_functional_metric, _was_product_clarification_question, _is_yes_to_product_clarification, _is_no_to_product_clarification, _quick_product_clarification_prompt, _extract_case_number_from_text, _extract_document_from_text, _extract_pasaporte_from_text, _extract_loose_claim_document, _extract_phone_from_text, _extract_name_from_text, _extract_action_input, _extract_fields_from_action_input, _get_action_body_value, _strip_message_tags, _read_bedrock_agent_completion, _classify_with_nova

def _mentions_store_personnel(text: str) -> bool:
    return _matches_any(text, ['\\bemplead[oa]\\b', '\\bpersonal\\b', '\\bgerente\\b', '\\bsupervisor\\b', '\\bcajer[oa]\\b', '\\bseguridad\\b', '\\bguardia\\b', '\\bvendedor[a]?\\b', '\\brepresentante\\b'])

def _looks_high_priority_complaint(text: str) -> bool:
    return _matches_any(text, ['\\bagresion\\b', '\\bagresión\\b', '\\bgolpe\\b', '\\bempuj', '\\blesion\\b', '\\blesión\\b', '\\baccidente\\b', '\\bcaida\\b', '\\bcaída\\b', '\\bme chocaron\\b', '\\bdaño fisico\\b', '\\bdaño físico\\b', '\\bsalud\\b', '\\bembarazo\\b', '\\bdenuncia\\b', '\\bdemanda\\b', '\\bproconsumidor\\b', '\\bredes sociales\\b', '\\bprensa\\b'])

def _is_simple_complaint_start(text: str) -> bool:
    t = _low_ascii(text)
    return t in {'tengo una queja', 'yo tengo una queja', 'quiero poner una queja', 'quiero registrar una queja', 'quiero hacer una queja'}

def _is_direct_complaint_start(text: str) -> bool:
    t = _low_ascii(text)
    keyword_hit = any((w in t for w in ['gerente', 'cajero', 'cajera', 'personal', 'seguridad', 'empleado', 'empleada', 'me cai', 'amenaz', 'groser', 'falto el respeto', 'denunciar', 'denuncia', 'maltrato', 'me trataron mal']))
    return (_matches_any(text, COMPLAINT_PATTERNS) or keyword_hit) and (not _is_simple_complaint_start(text))

def _is_direct_claim_start(text: str) -> bool:
    t = _low_ascii(text)
    product_problem = any((w in t for w in ['danad', 'dañad', 'defectuos', 'averiad', 'no funciona', 'rayad', 'abollad', 'incomplet', 'faltant', 'garantia', 'devolucion', 'devoluci'])) and any((w in t for w in ['producto', 'compra', 'compre', 'compr', 'pedido', 'orden', 'factura', 'llego', 'lleg']))
    if product_problem or 'reclamar' in t or 'reclamo' in t:
        return True
    if _matches_any(text, CLAIM_PATTERNS):
        return True
    return _matches_any(text, ['\\bproducto.*(danad|dañad|defectuos|averiad|rot|rayad|abollad|no funciona)\\b', '\\b(compre|compré|compra|pedido|orden).*(danad|dañad|defectuos|averiad|rot|rayad|abollad|incomplet|faltant|no funciona)\\b', '\\b(llego|llegó).*(danad|dañad|rot|rayad|abollad|incomplet|faltant)\\b'])
GENERIC_RECLAMATION_START_PATTERNS = ['^(?:(?:hola|bueno|eh|um+|mmm+)\\s+)*(?:yo\\s+)?tengo\\s+(?:una\\s+)?(?:reclamacion|reclamo)\\b', '^(?:(?:hola|bueno|eh|um+|mmm+)\\s+)*(?:quiero|necesito|deseo)\\s+(?:hacer|poner|presentar|registrar)\\s+(?:una\\s+)?reclamacion\\b', '^(?:(?:hola|bueno|eh|um+|mmm+)\\s+)*quiero\\s+reclamar\\b']
GENERIC_COMPLAINT_START_PATTERNS = ['^(?:(?:hola|bueno|eh|um+|mmm+)\\s+)*(?:yo\\s+)?tengo\\s+(?:una\\s+)?queja\\b', '^(?:(?:hola|bueno|eh|um+|mmm+)\\s+)*(?:quiero|necesito|deseo)\\s+(?:hacer|poner|presentar|registrar)\\s+(?:una\\s+)?queja\\b']
PRODUCT_CASE_EVIDENCE_PATTERNS = ['\\b(producto|articulo|televisor|tv|lavadora|nevera|refrigerador|licuadora|estufa|secadora|microonda|freidora|tostadora|plancha|aire\\s+acondicionado|abanico|computadora|laptop|celular)\\b', '\\b(mi\\s+)?(compra|pedido|orden|factura|entrega)\\b', '\\b(compre|comprado|adquiri|recibi)\\b']
PRODUCT_PROBLEM_PATTERNS = ['\\b(producto|articulo|televisor|tv|lavadora|nevera|refrigerador|licuadora|estufa|secadora|microonda|freidora|tostadora|plancha|aire\\s+acondicionado|abanico|computadora|laptop|celular)\\b.*\\b(danad|defectuos|averiad|roto|rayad|abollad|incomplet|faltant|no\\s+funciona|problema)\\b', '\\b(danad|defectuos|averiad|roto|rayad|abollad|incomplet|faltant|no\\s+funciona|problema)\\b.*\\b(producto|articulo|televisor|tv|lavadora|nevera|refrigerador|licuadora|estufa|secadora|microonda|freidora|tostadora|plancha|aire\\s+acondicionado|abanico|computadora|laptop|celular)\\b', '\\b(compre|comprado|compra|pedido|orden|entrega|recibi|llego)\\b.*\\b(danad|defectuos|averiad|roto|rayad|abollad|incomplet|faltant|no\\s+funciona|no\\s+llego|problema)\\b']
NON_PRODUCT_COMPLAINT_EVIDENCE_PATTERNS = ['\\b(emplead[oa]|personal|gerente|supervisor|cajer[oa]|seguridad|guardia|vendedor[a]?)\\b', '\\b(mal\\s+trato|maltrato|insult|agredi|amenaz|empuj|acos|groser|falto\\s+el\\s+respeto|me\\s+trataron\\s+mal)\\b', '\\b(accidente|me\\s+cai|me\\s+lesione|incidente\\s+en\\s+(?:la\\s+)?(?:tienda|sucursal))\\b', '\\b(no\\s+(?:es|fue)\\s+(?:por\\s+)?(?:un\\s+)?producto|por\\s+(?:el\\s+)?servicio|servicio\\s+(?:malo|pesimo))\\b']
MAIN_MENU_SELECTION_PATTERNS = {'1': ['^(?:(?:la\\s+)?opcion(?:\\s+numero)?\\s+|(?:el\\s+)?numero\\s+|la\\s+)?(?:1|uno|primer[oa]?)(?:\\s+(?:(?:informacion|preguntas?)\\s+general(?:es)?|general))?$', '^(?:(?:informacion|preguntas?)\\s+general(?:es)?|general)\\s+(?:1|uno|primer[oa]?)$', '^(?:informacion|preguntas?)\\s+general(?:es)?$', '^general$'], '2': ['^(?:(?:la\\s+)?opcion(?:\\s+numero)?\\s+|(?:el\\s+)?numero\\s+|la\\s+)?(?:2|dos|segund[oa])(?:\\s+(?:consulta\\s+(?:de\\s+)?estatus|estatus))?$', '^(?:consulta\\s+(?:de\\s+)?estatus|estatus)\\s+(?:2|dos|segund[oa])$', '^consulta\\s+(?:de\\s+)?estatus$', '^estatus$'], '3': ['^(?:(?:la\\s+)?opcion(?:\\s+numero)?\\s+|(?:el\\s+)?numero\\s+|la\\s+)?(?:3|tres|tercer[oa]?)(?:\\s+(?:reclamacion(?:es)?|reclamo))?$', '^(?:reclamacion(?:es)?|reclamo)\\s+(?:3|tres|tercer[oa]?)$', '^reclamacion(?:es)?$', '^reclamo$'], '4': ['^(?:(?:la\\s+)?opcion(?:\\s+numero)?\\s+|(?:el\\s+)?numero\\s+|la\\s+)?(?:4|cuatro|cuart[oa])(?:\\s+quejas?)?$', '^quejas?\\s+(?:4|cuatro|cuart[oa])$', '^quejas?$'], '5': ['^(?:(?:la\\s+)?opcion(?:\\s+numero)?\\s+|(?:el\\s+)?numero\\s+|la\\s+)?(?:5|cinco|quint[oa])(?:\\s+(?:(?:u\\s+)?otr[oa]s?(?:\\s+opciones?)?|agente|representante))?$', '^(?:(?:u\\s+)?otr[oa]s?(?:\\s+opciones?)?|agente|representante)\\s+(?:5|cinco|quint[oa])$', '^(?:u\\s+)?otr[oa]s?(?:\\s+opciones?)?$', '^(?:agente|representante)$']}

def _parse_main_menu_selection(transcript: str) -> str:
    normalized = re.sub('[^a-z0-9\\s]+', ' ', _low_ascii(transcript))
    normalized = _norm(normalized)
    normalized = re.sub('^(?:(?:por\\s+favor|favor\\s+de|quiero|quisiera|deseo|elijo|selecciono|marco|digo)\\s+)+', '', normalized)
    normalized = re.sub('\\s+(?:por\\s+favor|porfa|gracias)$', '', normalized)
    normalized = _norm(normalized)
    for option, patterns in MAIN_MENU_SELECTION_PATTERNS.items():
        if _matches_any(normalized, patterns):
            return option
    return ''

def _reset_intent_routing(session_attrs: Dict[str, str]) -> None:
    for key in ('bedrock_active_intent', 'pending_product_clarification', 'product_clarification_prompted', 'product_clarification_attempts', 'initial_customer_message', 'bedrock_supervisor_active'):
        session_attrs.pop(key, None)
    session_attrs[ROUTE_ATTR] = ''

def _clear_q_routing_context(session_attrs: Dict[str, str]) -> None:
    managed_prefix = 'x-amz-lex:q-in-connect'
    for key in list(session_attrs):
        if key.startswith(managed_prefix) or key in {'Tool', 'ToolUseId', 'query', 'qconnect_last_query', 'qconnect_result_offset', 'qconnect_direct_retrieve_count', 'qconnect_direct_retrieve_error', 'qconnect_retrieve_error'}:
            session_attrs.pop(key, None)
    session_attrs['qconnect_context_active'] = 'false'
    session_attrs['qconnect_context_kind'] = ''
    session_attrs['pregunta_general_detectada'] = 'false'

def _handle_explicit_service_intent(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    if not _has_value(transcript) or session_attrs.get('pending_product_clarification'):
        return None
    generic_reclamation = _matches_any(transcript, GENERIC_RECLAMATION_START_PATTERNS)
    generic_complaint = _matches_any(transcript, GENERIC_COMPLAINT_START_PATTERNS)
    product_evidence = _matches_any(transcript, PRODUCT_CASE_EVIDENCE_PATTERNS)
    product_problem = _matches_any(transcript, PRODUCT_PROBLEM_PATTERNS)
    non_product_evidence = _matches_any(transcript, NON_PRODUCT_COMPLAINT_EVIDENCE_PATTERNS)
    if not (generic_reclamation or generic_complaint or product_problem or non_product_evidence):
        return None
    _reset_intent_routing(session_attrs)
    _clear_q_routing_context(session_attrs)
    session_attrs[BEDROCK_SESSION_ATTR] = ''
    session_attrs['bedrock_error_count'] = '0'
    session_attrs['bedrock_last_response'] = ''
    session_attrs['last_agent_response'] = ''
    session_attrs['initial_customer_message'] = transcript
    if product_problem:
        _mark_claim_route(session_attrs)
        session_attrs['bedrock_active_intent'] = 'reclamaciones'
        return None
    if non_product_evidence:
        _mark_complaint_route(session_attrs)
        session_attrs['bedrock_active_intent'] = 'quejas'
        session_attrs['reclamacion_detectada'] = 'false'
        return None
    if (generic_reclamation or generic_complaint) and product_evidence:
        _mark_claim_route(session_attrs)
        session_attrs['bedrock_active_intent'] = 'reclamaciones'
        return None
    pending_intent = 'reclamaciones' if generic_reclamation else 'quejas'
    question = '¿La reclamación tiene que ver con un producto comprado en Plaza Lama?' if pending_intent == 'reclamaciones' else '¿La queja tiene que ver con un producto comprado en Plaza Lama?'
    _add_origin(session_attrs, pending_intent)
    session_attrs['pending_product_clarification'] = pending_intent
    session_attrs['product_clarification_prompted'] = pending_intent
    session_attrs['product_clarification_attempts'] = '0'
    session_attrs['bedrock_last_response'] = question
    session_attrs['last_agent_response'] = question
    return _build_elicit_intent_response(session_state, session_attrs, question)

def _add_origin(session_attrs: Dict[str, str], origin: str):
    if not origin:
        return
    current = [x.strip() for x in session_attrs.get('origen_flujos', '').split(',') if x.strip()]
    if origin not in current:
        current.append(origin)
    session_attrs['origen_flujos'] = ','.join(current)
    session_attrs['origen_actual'] = origin

def _switch_to_amazon_q(session_attrs: Dict[str, str]) -> None:
    session_attrs[ROUTE_ATTR] = ROUTE_AMAZON_Q
    session_attrs['bedrock_supervisor_active'] = 'false'

def _switch_to_bedrock_supervisor(session_attrs: Dict[str, str]) -> None:
    session_attrs[ROUTE_ATTR] = ROUTE_BEDROCK_SUPERVISOR
    session_attrs['bedrock_supervisor_active'] = 'true'

def _mark_complaint_route(session_attrs: Dict[str, str]) -> None:
    _switch_to_bedrock_supervisor(session_attrs)
    _add_origin(session_attrs, 'quejas')
    session_attrs['servicio'] = 'queja'

def _mark_claim_route(session_attrs: Dict[str, str]) -> None:
    _switch_to_bedrock_supervisor(session_attrs)
    _add_origin(session_attrs, 'reclamaciones')
    session_attrs['reclamacion_detectada'] = 'true'

def _normalize_document_type(document_type: str) -> str:
    raw = _norm(document_type)
    low = _low_ascii(raw)
    if low in {'rnc'}:
        return 'RNC'
    if low in {'cedula', 'cédula'}:
        return 'Cedula'
    if low in {'pasaporte', 'passport'}:
        return 'Pasaporte'
    if low in {'factura', 'invoice'}:
        return 'Factura'
    if low in {'caso', 'case', 'case_number', 'casenumber', 'numero de caso', 'número de caso'}:
        return 'Caso'
    return raw

def _set_claim_document(session_attrs: Dict[str, str], document_type: str, document_value: str):
    if not _has_value(document_type) or not _has_value(document_value):
        return
    clean_type = _normalize_document_type(document_type)
    clean_value = _norm(str(document_value))
    session_attrs['reclamacion_tipo_documento'] = clean_type
    session_attrs['reclamacion_documento'] = clean_value
    session_attrs['tipo_documento'] = clean_type
    session_attrs['documento_cliente'] = clean_value
    session_attrs['reclamacion_cliente_identificado'] = 'true'
    if _low_ascii(clean_type) == 'caso':
        session_attrs['reclamacion_numero_caso'] = clean_value

def _sync_document_aliases(session_attrs: Dict[str, str]):
    tipo = session_attrs.get('reclamacion_tipo_documento') or session_attrs.get('tipo_documento') or ''
    documento = session_attrs.get('reclamacion_documento') or session_attrs.get('documento_cliente') or ''
    if not _has_value(documento) and _low_ascii(tipo) == 'caso':
        documento = session_attrs.get('reclamacion_numero_caso', '')
    if _has_value(tipo):
        tipo = _normalize_document_type(tipo)
        session_attrs['reclamacion_tipo_documento'] = tipo
        session_attrs['tipo_documento'] = tipo
    if _has_value(documento):
        documento = _norm(documento)
        session_attrs['reclamacion_documento'] = documento
        session_attrs['documento_cliente'] = documento
    if _has_value(tipo) and _has_value(documento):
        session_attrs['reclamacion_cliente_identificado'] = 'true'

def _initialize_session_attrs(session_attrs: Dict[str, str]) -> Dict[str, str]:
    defaults = {'_closed': 'false', 'wants_close': 'false', 'agente': 'false', 'servicio': '', 'nivel_queja': '', 'tipoestadofinal': '', 'resumen_turno': '', 'origen_actual': '', 'origen_flujos': '', 'pregunta_general_detectada': 'false', 'consulta_entrega_detectada': 'false', 'consulta_factura': '', 'reclamacion_detectada': 'false', 'reclamacion_consulta': 'false', 'reclamacion_creacion': 'false', 'reclamacion_documento': '', 'reclamacion_tipo_documento': '', 'reclamacion_documento_pendiente': '', 'tipo_documento': '', 'documento_cliente': '', 'reclamacion_numero_caso': '', 'reclamacion_cliente_identificado': 'false', 'detalle_queja': '', 'telefono_cliente': '', 'nombre_cliente': '', 'lugar_queja': '', 'fecha_incidente': '', 'area_involucrada': '', 'persona_involucrada': '', ROUTE_ATTR: '', BEDROCK_SESSION_ATTR: '', 'bedrock_supervisor_active': 'false', 'bedrock_last_response': '', 'bedrock_error_count': '0', 'product_clarification_prompted': '', 'product_clarification_attempts': '0', 'branch_lookup_pending': 'false', 'branch_pending_query': '', 'branch_last_code': ''}
    for k, v in defaults.items():
        session_attrs.setdefault(k, v)
    _sync_document_aliases(session_attrs)
    return session_attrs

def _handle_main_menu_selection(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, recover_unmarked_first_turn: bool=False) -> Dict[str, Any] | None:
    if not _has_value(transcript):
        return None
    menu_pending = _low_ascii(session_attrs.get('menu_pending', '')) == 'true'
    option = _parse_main_menu_selection(transcript)
    if not option and _user_wants_agent(transcript):
        option = '5'
    if not menu_pending:
        if not (recover_unmarked_first_turn and option):
            return None
        session_attrs['menu_pending'] = 'true'
        session_attrs['menu_context_recovered'] = 'true'
        _emit_functional_metric('MainMenuContextRecovered', 'connect_first_turn')
    if not option:
        message = 'No entendí la opción. Por favor, di o marca un número del uno al cinco.'
        session_attrs['menu_pending'] = 'true'
        session_attrs['bedrock_last_response'] = message
        session_attrs['last_agent_response'] = message
        _emit_functional_metric('MainMenuSelectionUnrecognized', 'reprompt')
        return _build_elicit_intent_response(session_state, session_attrs, message)
    session_attrs.pop('menu_pending', None)
    _reset_intent_routing(session_attrs)
    _clear_q_routing_context(session_attrs)
    session_attrs[BEDROCK_SESSION_ATTR] = ''
    session_attrs.update({'_closed': 'false', 'wants_close': 'false', 'agente': 'false', 'representante': 'false', 'tipoestadofinal': '', 'resumen_turno': '', 'bedrock_error_count': '0'})
    session_attrs['menu_selection'] = option
    session_attrs['bedrock_last_response'] = ''
    session_attrs['last_agent_response'] = ''
    _emit_functional_metric('MainMenuSelectionResolved', f'option_{option}')
    if option == '1':
        message = 'Claro. ¿Qué información general deseas consultar?'
        _add_origin(session_attrs, 'preguntas_generales')
        session_attrs['servicio'] = 'informacion_general'
        session_attrs['pregunta_general_detectada'] = 'true'
        session_attrs['bedrock_last_response'] = message
        session_attrs['last_agent_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    if option == '2':
        message = 'Para consultar el estatus de tu pedido o entrega, por favor indícame tu número de factura.'
        _add_origin(session_attrs, 'status')
        _switch_to_bedrock_supervisor(session_attrs)
        session_attrs['servicio'] = 'estatus'
        session_attrs['consulta_entrega_detectada'] = 'true'
        session_attrs['bedrock_active_intent'] = 'consulta'
        session_attrs['initial_customer_message'] = 'consulta de estatus'
        session_attrs['bedrock_last_response'] = message
        session_attrs['last_agent_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    pending_intent = 'reclamaciones' if option == '3' else 'quejas'
    if option in {'3', '4'}:
        message = '¿La reclamación tiene que ver con un producto comprado en Plaza Lama?' if pending_intent == 'reclamaciones' else '¿La queja tiene que ver con un producto comprado en Plaza Lama?'
        _add_origin(session_attrs, pending_intent)
        session_attrs['servicio'] = pending_intent
        session_attrs['initial_customer_message'] = pending_intent
        session_attrs['pending_product_clarification'] = pending_intent
        session_attrs['product_clarification_prompted'] = pending_intent
        session_attrs['product_clarification_attempts'] = '0'
        session_attrs['bedrock_last_response'] = message
        session_attrs['last_agent_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    _add_origin(session_attrs, 'agente')
    session_attrs['representante'] = 'true'
    return _build_agent_transfer_close_response(session_state, session_attrs, 'Le estaré comunicando con un representante que podrá ayudarle.')

def _apply_complaint_fields_from_action_input(session_attrs: Dict[str, str], request_attrs: Dict[str, str]):
    values = _extract_fields_from_action_input(session_attrs, request_attrs)
    if not values:
        return
    for key, value in values.items():
        if key in {'nivel_criticidad', 'nivel_queja'}:
            session_attrs['nivel_queja'] = value
        else:
            session_attrs[key] = value
    if _has_value(values.get('servicio')):
        session_attrs['servicio'] = values['servicio']

def _apply_claim_fields(session_attrs: Dict[str, str], transcript: str, request_attrs: Dict[str, str]):
    low = _low_ascii(transcript)
    payload = _extract_action_input(session_attrs, request_attrs)
    action_group = _low_ascii(str(payload.get('actionGroupName', '')))
    api_path = _low_ascii(str(payload.get('apiPath', '')))
    is_claim_action = 'claims_management' in action_group or '/getclaim' in api_path or '/createclaim' in api_path or ('searchcustomercases' in api_path) or ('claim' in action_group)
    if is_claim_action:
        _add_origin(session_attrs, 'reclamaciones')
        session_attrs['reclamacion_detectada'] = 'true'
        dt = _get_action_body_value(payload, 'documentType')
        cd = _get_action_body_value(payload, 'customerDocument')
        if _has_value(dt) and _has_value(cd):
            _set_claim_document(session_attrs, dt, cd)
    if _matches_any(transcript, CLAIM_PATTERNS):
        _add_origin(session_attrs, 'reclamaciones')
        session_attrs['reclamacion_detectada'] = 'true'
    if _matches_any(transcript, STATUS_PATTERNS):
        _add_origin(session_attrs, 'status')
        session_attrs['consulta_entrega_detectada'] = 'true'
    if _is_explicit_general_route(transcript) and (not _is_bedrock_context_active(session_attrs)) and (not _is_bedrock_route(transcript)):
        _add_origin(session_attrs, 'preguntas_generales')
        session_attrs['pregunta_general_detectada'] = 'true'
    if _matches_any(transcript, COMPLAINT_PATTERNS):
        _add_origin(session_attrs, 'quejas')
    case_from_action = _get_action_body_value(payload, 'caseNumber')
    if _has_value(case_from_action):
        session_attrs['reclamacion_detectada'] = 'true'
        session_attrs['reclamacion_consulta'] = 'true'
        _set_claim_document(session_attrs, 'Caso', case_from_action)
        _add_origin(session_attrs, 'reclamaciones')
    case_from_text = _extract_case_number_from_text(transcript)
    if _has_value(case_from_text) and any((w in low for w in ['caso', 'numero', 'número', 'reclamacion', 'reclamación'])):
        session_attrs['reclamacion_detectada'] = 'true'
        _set_claim_document(session_attrs, 'Caso', case_from_text)
        _add_origin(session_attrs, 'reclamaciones')
    if any((p in low for p in ['consultar una reclamacion', 'consultar una reclamación', 'mi caso', 'numero de caso', 'número de caso'])):
        session_attrs['reclamacion_detectada'] = 'true'
        session_attrs['reclamacion_consulta'] = 'true'
        _add_origin(session_attrs, 'reclamaciones')
    if any((p in low for p in ['crear una reclamacion', 'crear una reclamación', 'nueva reclamacion', 'nueva reclamación'])):
        session_attrs['reclamacion_detectada'] = 'true'
        session_attrs['reclamacion_creacion'] = 'true'
        _add_origin(session_attrs, 'reclamaciones')
    for keyword, doc_type in [('cedula', 'Cedula'), ('rnc', 'RNC')]:
        doc = _extract_document_from_text(transcript, keyword)
        if _has_value(doc):
            session_attrs['reclamacion_detectada'] = 'true'
            _set_claim_document(session_attrs, doc_type, doc)
            _add_origin(session_attrs, 'reclamaciones')
    factura = _extract_document_from_text(transcript, 'factura')
    if _has_value(factura):
        if 'reclamacion' in low or 'reclamación' in low or session_attrs.get('reclamacion_detectada') == 'true' or (session_attrs.get('origen_actual') == 'reclamaciones'):
            session_attrs['reclamacion_detectada'] = 'true'
            _set_claim_document(session_attrs, 'Factura', factura)
            _add_origin(session_attrs, 'reclamaciones')
        else:
            session_attrs['consulta_factura'] = factura
            session_attrs['consulta_entrega_detectada'] = 'true'
            _add_origin(session_attrs, 'status')
    pasaporte = _extract_pasaporte_from_text(transcript)
    if _has_value(pasaporte):
        session_attrs['reclamacion_detectada'] = 'true'
        _set_claim_document(session_attrs, 'Pasaporte', pasaporte)
        _add_origin(session_attrs, 'reclamaciones')
    _sync_document_aliases(session_attrs)

def _get_canonical_branch_from_text(text: str) -> str:
    for branch_name, patterns in BRANCH_ALIASES.items():
        if _matches_any(text, patterns):
            return branch_name
    return ''

def _was_asking_for_branch_or_place(text: str) -> bool:
    t = _low_ascii(text)
    if 'area' in t or 'área' in t:
        return False
    return any((hint in t for hint in ['sucursal o lugar', 'en que sucursal', 'en que lugar', 'donde ocurrio', 'donde ocurrió', 'lugar ocurrio', 'lugar ocurrió', 'sucursal ocurrio', 'sucursal ocurrió', 'lugar o la fecha', 'lugar o fecha', 'lugar del incidente']))

def _was_asking_for_name(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in ['nombre completo', 'tu nombre', 'su nombre', 'comparte tu nombre', 'indica tu nombre']))

def _was_asking_for_phone(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in ['telefono de contacto', 'teléfono de contacto', 'numero de telefono', 'número de teléfono', 'tu telefono', 'tu teléfono', 'su telefono', 'su teléfono']))

def _was_asking_for_complaint_detail(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in ['describe brevemente que ocurrio', 'describe brevemente qué ocurrió', 'que ocurrio', 'qué ocurrió', 'cuentame que paso', 'cuéntame qué pasó', 'detalle de la queja', 'detalles de la queja', 'detalles de tu queja', 'detalles de su queja', 'describe la situacion', 'describe la situación', 'describir la situacion', 'describir la situación', 'situacion que te ha llevado', 'situación que te ha llevado']))

def _was_asking_for_incident_date(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in ['fecha en que sucedio', 'fecha en que sucedió', 'cuando paso', 'cuándo pasó', 'cuando sucedio', 'cuándo sucedió', 'cuando ocurrio', 'cuándo ocurrió', 'cuando fue', 'cuándo fue', 'hace cuanto ocurrio', 'hace cuánto ocurrió', 'fecha del incidente', 'fecha de incidente', 'fecha aproximada']))

def _was_asking_for_area(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in ['en que area', 'en qué área', 'area de la sucursal', 'área de la sucursal', 'seccion', 'sección', 'departamento', 'donde exactamente', 'dónde exactamente']))

def _was_asking_for_involved_person(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in ['persona involucrada', 'quien estuvo involucrado', 'quién estuvo involucrado', 'nombre o descripcion', 'nombre o descripción', 'identificar a la persona']))

def _was_asking_for_claim_document(text: str) -> bool:
    t = _low_ascii(text)
    return any((hint in t for hint in ['numero de factura', 'número de factura', 'cedula', 'cédula', 'rnc', 'pasaporte', 'numero de caso', 'número de caso']))

def _was_asking_for_status_invoice(last_agent_response: str) -> bool:
    t = _low_ascii(last_agent_response)
    return 'numero de factura' in t or 'número de factura' in t or 'indiqueme la factura' in t or ('indícame la factura' in t) or ('factura' in t and ('pedido' in t or 'entrega' in t or 'estado' in t))

def _apply_contextual_user_answer_fields(session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> None:
    if not _has_value(transcript) or not _is_bedrock_context_active(session_attrs):
        return
    if _was_asking_for_name(last_agent_response):
        name = _extract_name_from_text(transcript)
        if _has_value(name):
            session_attrs['nombre_cliente'] = name
        return
    if _was_asking_for_phone(last_agent_response):
        phone = _extract_phone_from_text(transcript)
        if _has_value(phone):
            session_attrs['telefono_cliente'] = phone
        return
    if _was_asking_for_complaint_detail(last_agent_response):
        session_attrs['detalle_queja'] = _norm(transcript)
        _add_origin(session_attrs, 'quejas')
        return
    if _was_asking_for_incident_date(last_agent_response):
        session_attrs['fecha_incidente'] = _norm(transcript)
        _add_origin(session_attrs, 'quejas')
        return
    if _was_asking_for_branch_or_place(last_agent_response):
        branch = _get_canonical_branch_from_text(transcript)
        session_attrs['lugar_queja'] = branch if _has_value(branch) else _norm(transcript)
        _add_origin(session_attrs, 'quejas')
        return
    if _was_asking_for_area(last_agent_response):
        session_attrs['area_involucrada'] = _norm(transcript)
        _add_origin(session_attrs, 'quejas')
        return
    if _was_asking_for_involved_person(last_agent_response):
        session_attrs['persona_involucrada'] = _norm(transcript)
        _add_origin(session_attrs, 'quejas')

def _is_explicit_general_route(text: str) -> bool:
    return _matches_any(text, GENERAL_PATTERNS) or _matches_any(text, BRANCH_GENERAL_INFO_PATTERNS) or _matches_any(text, VAGUE_GENERAL_START_PATTERNS)

def _is_bedrock_route(text: str) -> bool:
    return _matches_any(text, BEDROCK_ROUTE_PATTERNS)

def _is_bedrock_context_active(session_attrs: Dict[str, str]) -> bool:
    return session_attrs.get(ROUTE_ATTR) == ROUTE_BEDROCK_SUPERVISOR or session_attrs.get('bedrock_supervisor_active') == 'true'
DIRECT_RETRIEVE_PATTERNS = ['\\b(precio|precios|costo|costos|cuanto\\s+(cuesta|vale|es))\\b', '\\b(tienen|tiene|venden|busco|buscar|quiero|necesito|quisiera)\\b.*\\b(producto|televisor|tv|licuadora|nevera|refrigerador|estufa|lavadora|secadora|microonda|freidora|tostadora|plancha|aire|abanico|computadora|laptop|celular|soporte)\\b', '\\b(producto|televisor|tv|licuadora|nevera|refrigerador|estufa|lavadora|secadora|microonda|freidora|tostadora|plancha|aire\\s+acondicionado|abanico|computadora|laptop|celular|soporte)\\b', '\\b(disponible|disponibilidad|catalogo|categoria|marca|modelo|opci[oó]n(?:es)?)\\b', '\\b(promocion|promociones|oferta|ofertas|descuento|descuentos)\\b', '\\b(sucursal|sucursales|tienda|tiendas|horario|horarios|direccion|dirección|ubicacion|ubicación|donde\\s+queda|donde\\s+esta|dónde\\s+está|abre|abren|cierra|cierran)\\b']
GENERIC_CATALOG_AVAILABILITY_PATTERNS = ['\\b(?:(?:usted|ustedes)\\s+)?(?:venden|comercializan)\\s+(?:(?:el|la|los|las|un|una|unos|unas|algun|alguna)\\s+)?(?!(?:a|al|con|como|cuando|donde|en|para|por|que|el|la|los|las|un|una|unos|unas|algun|alguna|algo|nada|mucho|mucha|muchos|muchas|varios|varias|problemas?|preguntas?|dudas?|gente|personal|agentes?|ayuda|empleo|vacantes?|retrasos?|casos?|quejas?|reclamaciones?|reclamos?|facturas?|ordenes?|entregas?)\\b)[a-z0-9][a-z0-9-]{2,}\\b']
DIRECT_RETRIEVE_SUBJECT_PATTERNS = ['\\b(producto|televisor|tv|licuadora|nevera|refrigerador|estufa|lavadora|secadora|microonda|freidora|tostadora|plancha|aire\\s+acondicionado|abanico|computadora|laptop|celular|soporte)\\b', '\\b(sucursal|sucursales|tienda|tiendas|horario|horarios|direccion|dirección|ubicacion|ubicación|promocion|promociones|oferta|ofertas|descuento|descuentos)\\b']
HELP_MENU_PATTERNS = ['\\b(opci[oó]n(?:es)?|menu|menú|ayuda|repite|repita)\\b', '\\b(que|qué)\\s+(puedes|puede)\\s+hacer\\b', '\\b(en|de)\\s+que\\s+me\\s+puedes\\s+ayudar\\b', '\\b(que|qué)\\s+opci[oó]n(?:es)?\\s+(tengo|hay)\\b']
MORE_OPTIONS_PATTERNS = ['\\b(otra|otras|otro|otros)\\s+opci[oó]n', '\\b(que|qué)\\s+mas\\b', '\\bdame\\s+mas\\b', '\\bmas\\s+opci[oó]n(?:es)?\\b']
QUERY_STOPWORDS = {'quiero', 'quisiera', 'necesito', 'busco', 'buscar', 'saber', 'conocer', 'si', 'tienen', 'tiene', 'venden', 'hay', 'una', 'un', 'unos', 'unas', 'el', 'la', 'los', 'las', 'de', 'del', 'para', 'por', 'favor', 'me', 'puedes', 'puede', 'decir', 'dime', 'ver', 'revisar', 'consultar', 'precio', 'precios', 'costo', 'costos', 'cuanto', 'cuesta', 'vale', 'usted', 'ustedes', 'pregunta', 'ofrecen', 'manejan', 'comercializan'}
DIRECT_RETRIEVE_EXCLUDE_PATTERNS = [*CLAIM_PATTERNS, *COMPLAINT_PATTERNS, *STATUS_PATTERNS, *CONSULTA_FACTURA_PATTERNS, '\\b(numero|número)\\s+de\\s+(factura|orden|caso|reclamacion|reclamación)\\b', '\\b(algun\\s+|algún\\s+)?(numero|número)\\s+de\\s+telefono\\b', '\\b(garantia|garantía|devolucion|devolución|queja|reclamacion|reclamación|reclamo)\\b']

def _is_direct_retrieve_route(transcript: str, session_attrs: Dict[str, str]) -> bool:
    if not _has_value(transcript):
        return False
    if session_attrs.get('bedrock_active_intent') or session_attrs.get('pending_product_clarification'):
        return False
    if _is_bedrock_context_active(session_attrs):
        return False
    if _user_wants_close(transcript) or _user_wants_agent(transcript):
        return False
    if _matches_any(transcript, DIRECT_RETRIEVE_EXCLUDE_PATTERNS):
        return False
    if _matches_any(transcript, MORE_OPTIONS_PATTERNS) and _has_value(session_attrs.get('qconnect_last_query', '')):
        return True
    if _matches_any(transcript, HELP_MENU_PATTERNS) and (not _matches_any(transcript, DIRECT_RETRIEVE_SUBJECT_PATTERNS)):
        return True
    if _canonical_product_category(transcript):
        return True
    return _matches_any(transcript, DIRECT_RETRIEVE_PATTERNS) or _is_catalog_availability_request(transcript)

def _is_catalog_availability_request(transcript: str) -> bool:
    return _matches_any(transcript, GENERIC_CATALOG_AVAILABILITY_PATTERNS)

def _is_generic_help_menu_request(transcript: str) -> bool:
    return _matches_any(transcript, HELP_MENU_PATTERNS) and (not _matches_any(transcript, DIRECT_RETRIEVE_SUBJECT_PATTERNS))
BRANCH_STRONG_INFO_PATTERNS = ['\\b(sucursal|sucursales|locales|local|horario|horarios|direccion|dirección|ubicacion|ubicación)\\b', '\\b(donde\\s+queda|donde\\s+esta|dónde\\s+está|como\\s+llegar|abre|abren|cierra|cierran)\\b']
BRANCH_WEAK_INFO_PATTERNS = ['\\btiendas?\\b']
BRANCH_CITY_GROUPS = [('santiago', ['\\bsantiago(?:\\s+de\\s+los\\s+caballeros)?\\b'], {'PL04', 'PL16', 'PL91'}), ('santo_domingo_este', ['\\bsanto\\s+domingo\\s+este\\b', '\\bzona\\s+oriental\\b'], {'PL10', 'PL17'}), ('santo_domingo_oeste', ['\\bsanto\\s+domingo\\s+oeste\\b'], {'PL03'}), ('santo_domingo_norte', ['\\bsanto\\s+domingo\\s+norte\\b'], {'PL23', 'PL30'}), ('santo_domingo', ['\\bsanto\\s+domingo\\b', '\\bdistrito\\s+nacional\\b', '\\bcapital\\b'], {'PL01', 'PL03', 'PL08', 'PL10', 'PL11', 'PL12', 'PL17', 'PL19', 'PL22', 'PL23', 'PL30'})]
BRANCH_BRAND_PATTERNS = [('electrolama', ['\\belectro\\s*lama\\b']), ('super_lama', ['\\bsuper\\s+lama\\b']), ('plaza_lama', ['\\bplaza\\s+lama\\b'])]
LOCAL_HINTS = [('farmacia', ['\\bfarmacia\\b', '\\bhidalgos\\b', '\\bflamboyan\\b', '\\bvitasalud\\b']), ('claro', ['\\bclaro\\b']), ('altice', ['\\baltice\\b', '\\borange\\b']), ('viva', ['\\bviva\\b']), ('wind', ['\\bwind\\b']), ('vimenca', ['\\bvimenca\\b']), ('banreservas', ['\\bbanreservas\\b', '\\bbanco\\s+de\\s+reservas\\b', '\\breservas\\b']), ('banco popular', ['\\bbanco\\s+popular\\b', '\\bpopular\\b']), ('banco ademi', ['\\bademi\\b']), ('bhd', ['\\bbhd\\b', '\\bcajero\\b']), ('caribe express', ['\\bcaribe\\s+express\\b']), ('multiloto', ['\\bmultiloto\\b', '\\bmulti\\s*loto\\b']), ('edesur', ['\\bedesur\\b']), ('helados bon', ['\\bhelados?\\s+bon\\b']), ('tell solution', ['\\btell\\s+solution\\b']), ('admiral coffee', ['\\badmiral\\s+coffee\\b']), ('barra payan', ['\\bbarra\\s+payan\\b']), ('krispy kreme', ['\\bkrispy\\s+kreme\\b']), ('mail boxes', ['\\bmail\\s+boxes\\b']), ('optica vision', ['\\boptica\\b', '\\bóptica\\b', '\\bvision\\b', '\\bvisión\\b']), ('cooperativa medica', ['\\bcooperativa\\s+medica\\b', '\\bcooperativa\\s+médica\\b'])]
RAW_BRANCH_DATA_PATTERN = re.compile('(codigo_sucursal|nombre_sucursal|\\bPL\\d{2}\\b|^PL\\s*,\\s*TIENDA|PLAZA\\s+LAMA\\s+[A-Z0-9])', re.IGNORECASE)

def _phrase_in_text(text: str, phrase: str) -> bool:
    clean_phrase = _low_ascii(phrase)
    if not clean_phrase:
        return False
    pattern = '(?<![a-z0-9])' + re.escape(clean_phrase).replace('\\ ', '\\s+') + '(?![a-z0-9])'
    return re.search(pattern, text) is not None

def _requested_local_hint(transcript: str) -> str:
    for label, patterns in LOCAL_HINTS:
        if _matches_any(transcript, patterns):
            return label
    return ''

def _is_branch_info_query(transcript: str) -> bool:
    if not _has_value(transcript):
        return False
    if _matches_any(transcript, BRANCH_STRONG_INFO_PATTERNS):
        return True
    if _requested_local_hint(transcript) and _matches_any(transcript, ['\\bhorarios?\\b', '\\babre\\b', '\\bcierra\\b']):
        return True
    return _matches_any(transcript, BRANCH_WEAK_INFO_PATTERNS) and _matches_any(transcript, ['\\bplaza\\s+lama\\b', '\\belectro\\s*lama\\b', '\\bsuper\\s+lama\\b'])

def _branch_alias_score(record: Dict[str, Any], transcript: str) -> int:
    t = _low_ascii(transcript)
    score = 0
    if _phrase_in_text(t, record.get('code', '')):
        score = max(score, len(record.get('code', '')) + 20)
    for alias in record.get('aliases') or []:
        if _phrase_in_text(t, alias):
            score = max(score, len(_low_ascii(alias)))
    return score

def _requested_branch_brand(transcript: str) -> str:
    for brand, patterns in BRANCH_BRAND_PATTERNS:
        if _matches_any(transcript, patterns):
            return brand
    return ''

def _record_branch_brand(record: Dict[str, Any]) -> str:
    name = _low_ascii(record.get('name', ''))
    if name.startswith('electrolama'):
        return 'electrolama'
    if name.startswith('super lama'):
        return 'super_lama'
    if name.startswith('plaza lama'):
        return 'plaza_lama'
    return ''

def _branch_candidate_scope(transcript: str) -> tuple[List[Dict[str, Any]], bool]:
    records = list(BRANCH_DIRECTORY)
    requested_brand = _requested_branch_brand(transcript)
    if requested_brand:
        records = [record for record in records if _record_branch_brand(record) == requested_brand]
    location_matched = False
    for _, patterns, codes in BRANCH_CITY_GROUPS:
        if _matches_any(transcript, patterns):
            location_matched = True
            records = [record for record in records if record.get('code') in codes]
            break
    return (records, location_matched)

def _resolve_branch_candidates(transcript: str) -> List[Dict[str, Any]]:
    records, location_matched = _branch_candidate_scope(transcript)
    scored = []
    for record in records:
        score = _branch_alias_score(record, transcript)
        if score:
            scored.append((score, record))
    if scored:
        top_score = max((score for score, _ in scored))
        return [record for score, record in scored if score == top_score]
    if location_matched:
        return records
    return []

def _branch_candidate_names(candidates: List[Dict[str, Any]]) -> str:
    names = [record.get('name', '') for record in candidates if record.get('name')]
    if len(names) <= 5:
        return ', '.join(names)
    return ', '.join(names[:5]) + ' y otras sucursales'

def _branch_by_code(code: str) -> Dict[str, Any] | None:
    return next((record for record in BRANCH_DIRECTORY if record.get('code') == code), None)

def _is_last_branch_followup(transcript: str) -> bool:
    clean_transcript = re.sub('[^a-z0-9\\s]', ' ', _low_ascii(transcript))
    clean_transcript = re.sub('\\s+', ' ', clean_transcript).strip()
    return _matches_any(clean_transcript, ['^(si\\s+)?(quiero|quisiera|necesito)?\\s*(saber|consultar|conocer)?\\s*(el|su)?\\s*horarios?\\s*$', '^(si\\s+)?(quiero|quisiera|necesito)?\\s*(saber|consultar|conocer)?\\s*(la|su)?\\s*(direccion|ubicacion)\\s*$', '\\b(esa|esta|la\\s+misma)\\s+sucursal\\b'])

def _local_matches(local_name: str, local_hint: str) -> bool:
    local = _low_ascii(local_name)
    if local_hint == 'farmacia':
        return 'farmacia' in local
    if local_hint == 'altice':
        return 'altice' in local or 'orange' in local
    if local_hint == 'banreservas':
        return 'banreservas' in local or 'reservas' in local
    if local_hint == 'bhd':
        return 'bhd' in local
    if local_hint == 'multiloto':
        return 'multiloto' in local or 'multi loto' in local
    return local_hint in local

def _format_local_answer(record: Dict[str, Any], local_hint: str) -> str:
    locals_by_name = record.get('locals') or {}
    matches = [(name, hours) for name, hours in locals_by_name.items() if _local_matches(name, local_hint)]
    if not matches:
        return f"No puedo confirmar el horario de {local_hint} en {record['name']}. Puedo darte el horario general de la tienda si deseas."
    if len(matches) > 1:
        options = ', '.join((name for name, _ in matches[:4]))
        return f"En {record['name']} hay varias opciones: {options}. Cual deseas consultar?"
    local_name, hours = matches[0]
    return f"En {record['name']}, {local_name} tiene horario {hours}. Deseas consultar otra cosa?"

def _format_branch_answer(transcript: str, record: Dict[str, Any]) -> str:
    local_hint = _requested_local_hint(transcript)
    if local_hint:
        return _format_local_answer(record, local_hint)
    wants_address = _matches_any(transcript, ['\\bdireccion\\b', '\\bdirección\\b', '\\bubicacion\\b', '\\bubicación\\b', '\\bdonde\\s+queda\\b', '\\bcomo\\s+llegar\\b'])
    wants_hours = _matches_any(transcript, ['\\bhorarios?\\b', '\\babre\\b', '\\babren\\b', '\\bcierra\\b', '\\bcierran\\b'])
    address = _norm(record.get('address', ''))
    hours = _norm(record.get('hours', ''))
    if wants_address and wants_hours and address and hours:
        return f"{record['name']} esta en {address}. Su horario es {hours}. Deseas consultar otra cosa?"
    if wants_address and address:
        return f"{record['name']} esta en {address}. Deseas consultar otra cosa?"
    if wants_address and (not address):
        return f"No tengo una direccion confirmada para {record['name']}. Deseas consultar el horario?"
    if wants_hours and hours:
        return f"El horario de {record['name']} es {hours}. Deseas consultar otra cosa?"
    if wants_hours:
        return f"No puedo confirmar el horario de {record['name']}. Deseas consultar otra sucursal?"
    if address:
        return f"La sucursal es {record['name']}, ubicada en {address}. Deseas consultar el horario?"
    return f"La sucursal es {record['name']}. No tengo una direccion confirmada para esta sucursal."

def _handle_branch_info_lookup(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    if session_attrs.get('bedrock_active_intent') or session_attrs.get('pending_product_clarification') or _is_bedrock_context_active(session_attrs):
        return None
    is_info_query = _is_branch_info_query(transcript)
    lookup_pending = session_attrs.get('branch_lookup_pending') == 'true'
    pending_query = session_attrs.get('branch_pending_query', '') if lookup_pending else ''
    effective_transcript = _norm(f'{pending_query} {transcript}')
    candidates = _resolve_branch_candidates(effective_transcript)
    if not is_info_query and (not (lookup_pending and candidates)):
        return None
    local_hint = _requested_local_hint(effective_transcript)
    if not candidates and is_info_query and _is_last_branch_followup(transcript):
        last_branch = _branch_by_code(session_attrs.get('branch_last_code', ''))
        if last_branch:
            candidates = [last_branch]
    if not candidates:
        if local_hint:
            message = 'De cual sucursal deseas el horario de ese local?'
        elif _matches_any(transcript, ['\\bsucursales\\b', '\\btiendas\\b']):
            message = 'Tenemos varias sucursales. Puedo ayudarte con Duarte, Herrera, 27 de Febrero, Carretera Mella, Nicolas de Ovando, Santiago, La Romana, Bavaro y otras. Cual deseas consultar?'
        else:
            message = 'No encontre una sucursal con ese nombre. Puedes repetir la sucursal exacta?'
        session_attrs['branch_lookup_pending'] = 'true'
        if not pending_query:
            session_attrs['branch_pending_query'] = transcript
    elif len(candidates) > 1:
        names = _branch_candidate_names(candidates)
        message = f'Hay varias sucursales que coinciden: {names}. Cual deseas consultar?'
        session_attrs['branch_lookup_pending'] = 'true'
        if not pending_query:
            session_attrs['branch_pending_query'] = transcript
    else:
        branch = candidates[0]
        message = _format_branch_answer(effective_transcript, branch)
        session_attrs['branch_last_code'] = branch.get('code', '')
        session_attrs['branch_lookup_pending'] = 'false'
        session_attrs['branch_pending_query'] = ''
    _reset_intent_routing(session_attrs)
    _add_origin(session_attrs, 'preguntas_generales')
    session_attrs['pregunta_general_detectada'] = 'true'
    session_attrs['branch_lookup_handled'] = 'true'
    session_attrs['bedrock_last_response'] = message
    session_attrs['last_agent_response'] = message
    return _build_elicit_intent_response(session_state, session_attrs, message)

def _resolve_qconnect_query(transcript: str, session_attrs: Dict[str, str]) -> str:
    if _matches_any(transcript, MORE_OPTIONS_PATTERNS):
        last_query = session_attrs.get('qconnect_last_query', '')
        if _has_value(last_query):
            return last_query
    words = re.findall('[a-z0-9]+', _low_ascii(transcript))
    filtered = [word for word in words if word not in QUERY_STOPWORDS]
    return ' '.join(filtered)

def _qconnect_content_texts(response: Dict[str, Any]) -> List[str]:
    texts: List[str] = []
    for item in response.get('results') or []:
        text = _norm(item.get('contentText', ''))
        if text:
            texts.append(text)
    return texts

def _retrieve_qconnect_texts(query: str) -> List[str]:
    clean_query = _norm(query)
    if not clean_query:
        _emit_functional_metric('QConnectEmptyQueryBlocked', 'retrieve_guard')
        return []
    try:
        response = qconnect_client.retrieve(assistantId=QCONNECT_ASSISTANT_ID, retrievalQuery=clean_query, retrievalConfiguration={'knowledgeSource': {'assistantAssociationIds': [QCONNECT_ASSOCIATION_ID]}})
    except Exception:
        _emit_functional_metric('QConnectRetrieveError', 'retrieve_api')
        raise
    return _qconnect_content_texts(response)

def _field_from_content(content: str, label: str) -> str:
    pattern = f'{re.escape(label)}:\\s*([^\\n.]*)'
    match = re.search(pattern, content, flags=re.IGNORECASE)
    return _norm(match.group(1) if match else '')

def _short_product_name(name: str) -> str:
    clean = re.sub('\\s+', ' ', _norm(name)).strip()
    return clean[:72].rstrip()
PRODUCT_CATEGORY_RULES = [('\\blavadoras?\\b', '\\blavadora\\b'), ('\\blicuadoras?\\b', '\\blicuadora\\b'), ('\\b(neveras?|refrigeradores?)\\b', '\\b(nevera|refrigerador|nev)\\b'), ('\\b(televisores?|tv|teles?)\\b', '\\b(televisor|tv)\\b'), ('\\b(estufas?|cocinas?|fogones?)\\b', '\\b(estufa|cocina|fogon)\\b'), ('\\bsecadoras?\\b', '\\bsecadora\\b'), ('\\bmicroondas?\\b', '\\bmicroonda\\b'), ('\\b(freidoras?|air\\s*fryers?)\\b', '\\b(freidora|air\\s*fryer)\\b'), ('\\btostadoras?\\b', '\\btostadora\\b'), ('\\bplanchas?\\b', '\\bplancha\\b'), ('\\baires?(\\s+acondicionados?)?\\b', '\\b(aire|a/a)\\b'), ('\\b(abanicos?|ventiladores?)\\b', '\\b(abanico|ventilador)\\b'), ('\\b(computadoras?|laptops?|notebooks?|pcs?)\\b', '\\b(computadora|laptop|notebook|pc)\\b'), ('\\b(celulares?|telefonos?|smartphones?)\\b', '\\b(celular|telefono|smartphone)\\b'), ('\\baudifonos?\\b', '\\baudifono\\b'), ('\\btablets?\\b', '\\btablet\\b'), ('\\bbatidoras?\\b', '\\bbatidora\\b'), ('\\baspiradoras?\\b', '\\baspiradora\\b'), ('\\b(camas?|sofas?|sillones?|comedores?|muebles?|colchones?)\\b', '\\b(cama|sofa|sillon|comedor|mueble|colchon)\\b'), ('\\b(bocinas?|parlantes?)\\b', '\\b(bocina|parlante)\\b'), ('\\b(congeladores?|freezers?)\\b', '\\b(congelador|freezer)\\b')]
PRODUCT_BRANDS = {'american', 'black', 'bose', 'comfortstar', 'cuisinart', 'daewoo', 'dimension', 'dimensions', 'electrolux', 'frigidaire', 'general', 'havit', 'hisense', 'indurama', 'lg', 'mabe', 'maxell', 'oster', 'panasonic', 'polar', 'samsung', 'sankey', 'sharp', 'sony', 'tcl', 'tecnomaster', 'toshiba', 'whirlpool', 'windmere', 'windwere'}
BROAD_PRODUCT_TERMS = {'catalogo', 'catalogos', 'electrodomestico', 'electrodomesticos', 'producto', 'productos', 'algo', 'comprar', 'compra'}
PROMOTION_QUERY_PATTERNS = ['\\bpromociones?\\b', '\\bofertas?\\b', '\\bdescuentos?\\b']
PROMOTION_MONTHS = {'ENE': 1, 'JAN': 1, 'FEB': 2, 'MAR': 3, 'ABR': 4, 'APR': 4, 'MAY': 5, 'JUN': 6, 'JUL': 7, 'AGO': 8, 'AUG': 8, 'SEP': 9, 'SET': 9, 'OCT': 10, 'NOV': 11, 'DIC': 12, 'DEC': 12}

def _canonical_product_category(query: str) -> str:
    normalized = _low_ascii(query)
    for query_pattern, name_pattern in PRODUCT_CATEGORY_RULES:
        if re.search(query_pattern, normalized):
            return name_pattern
    return ''

def _normalize_product_retrieval_query(query: str) -> str:
    normalized = _low_ascii(query)
    normalized = re.sub('\\b(y|que|cuales?|cuestan?|valen?|disponibles?|precios?|costos?|productos?|marcas?|modelos?|opciones?|catalogos?|products?|brands?|models?|options?|catalog)\\b', ' ', normalized)
    size_units = '(?:pies?|ft|pulgadas?|pulg|lb|libras?|kg|btu)'
    normalized = re.sub(f'\\b(neveras?|refrigeradores?|televisores?|lavadoras?|aires?)\\s+(?=\\d+\\s*{size_units}\\b)', '\\1 de ', normalized)
    normalized = re.sub('[^a-z0-9]+', ' ', normalized)
    return _norm(normalized)

def _is_broad_product_query(query: str) -> bool:
    normalized = _low_ascii(query)
    words = set(re.findall('[a-z0-9]+', normalized))
    has_category = bool(_canonical_product_category(normalized))
    has_brand = bool(words & PRODUCT_BRANDS)
    has_number = any((any((ch.isdigit() for ch in word)) for word in words))
    return bool(words) and words <= BROAD_PRODUCT_TERMS and (not (has_category or has_brand or has_number))

def _parse_product_record(content: str, index: int) -> Dict[str, Any] | None:
    if not _low_ascii(content).startswith('producto:'):
        return None
    name = _field_from_content(content, 'Producto')
    normalized_name = _low_ascii(name)
    if not name or re.match('^(x{2,}|mat\\s+modelo\\b)', normalized_name):
        return None
    price = _field_from_content(content, 'Precio')
    price_match = re.search('Precio:\\s*([\\d][\\d.,]*)', content, flags=re.IGNORECASE)
    price_value = int(re.sub('\\D', '', price_match.group(1))) if price_match else 0
    normalized_content = _low_ascii(content)
    available = 'no disponible en ninguna sucursal' not in normalized_content and re.search('\\bdisponible en (la|las) sucursal', normalized_content) is not None
    if not available or price_value in {0, 99999}:
        return None
    return {'name': name, 'name_ascii': normalized_name, 'brand_ascii': _low_ascii(_field_from_content(content, 'Marca')), 'price': price, 'price_value': price_value, 'index': index}

def _query_size_constraints(query: str) -> List[tuple[str, str]]:
    return re.findall('\\b(\\d{1,5})\\s*(pies?|ft|pulgadas?|pulg|lb|libras?|kg|btu)\\b', _low_ascii(query))

def _matches_size_constraints(name: str, constraints: List[tuple[str, str]]) -> bool:
    for number, unit in constraints:
        if unit.startswith('pie') or unit == 'ft':
            pattern = f'\\b{re.escape(number)}\\s*(?:pies?|ft)\\b'
        elif unit.startswith('pulg'):
            pattern = f'\\b{re.escape(number)}\\b'
        elif unit in {'lb', 'libra', 'libras'}:
            pattern = f'\\b{re.escape(number)}\\s*(?:lb|libras?)\\b'
        else:
            pattern = f'\\b{re.escape(number)}\\s*{re.escape(unit)}\\b'
        if re.search(pattern, name) is None:
            return False
    return True

def _query_model_tokens(query: str) -> List[str]:
    tokens = []
    for token in re.findall('\\b[a-z0-9-]+\\b', _low_ascii(query)):
        if not (any((ch.isalpha() for ch in token)) and any((ch.isdigit() for ch in token))):
            continue
        if re.fullmatch('\\d+(?:ft|lb|kg|btu|k)', token):
            continue
        tokens.append(token)
    return tokens

def _select_available_products(query: str, contents: List[str]) -> List[Dict[str, Any]]:
    category_pattern = _canonical_product_category(query)
    query_words = re.findall('[a-z0-9]+', _low_ascii(query))
    requested_brands = [word for word in query_words if word in PRODUCT_BRANDS]
    size_constraints = _query_size_constraints(query)
    model_tokens = _query_model_tokens(query)
    generic_subject_terms = []
    if not category_pattern:
        generic_subject_terms = [word for word in query_words if len(word) >= 3 and word not in BROAD_PRODUCT_TERMS and (word not in requested_brands) and (not any((ch.isdigit() for ch in word)))]
    constrained_numbers = {number for number, _ in size_constraints}
    standalone_numbers = [word for word in query_words if word.isdigit() and word not in constrained_numbers]
    products: List[Dict[str, Any]] = []
    seen = set()
    for index, content in enumerate(contents):
        product = _parse_product_record(content, index)
        if product is None:
            continue
        name = product['name_ascii']
        searchable = f"{name} {product['brand_ascii']}"
        if category_pattern and re.search(category_pattern, name) is None:
            continue
        if requested_brands and (not all((brand in searchable for brand in requested_brands))):
            continue
        if generic_subject_terms and (not all((re.search(f'\\b{re.escape(term)}\\b', searchable) for term in generic_subject_terms))):
            continue
        if model_tokens and (not all((token in searchable for token in model_tokens))):
            continue
        if standalone_numbers and (not all((re.search(f'\\b{re.escape(number)}\\b', name) for number in standalone_numbers))):
            continue
        if not _matches_size_constraints(name, size_constraints):
            continue
        key = _low_ascii(product['name'])
        if key in seen:
            continue
        seen.add(key)
        products.append(product)
    wants_largest = _matches_any(query, ['\\b(mas\\s+grande|mayor|grande)\\b'])
    if wants_largest:

        def size_value(product: Dict[str, Any]) -> int:
            values = [int(value) for value in re.findall('\\b(\\d{2,3})\\b', product['name_ascii'])]
            return max(values) if values else 0
        products.sort(key=lambda product: (-size_value(product), product['price_value'], product['index']))
    else:
        products.sort(key=lambda product: (product['price_value'], product['index']))
    return products

def _product_summary(product: Dict[str, Any]) -> str:
    name = _short_product_name(product['name'])
    price = product['price']
    return f'{name} por {price}' if price else name

def _format_product_answer(products: List[Dict[str, Any]], offset: int, followup: bool) -> str:
    selected = products[offset:offset + 2]
    if not selected:
        if followup:
            return 'No encontré más opciones disponibles para esa búsqueda. ¿Quieres buscar otro producto?'
        return 'No pude confirmar una opción disponible para esa búsqueda. ¿Quieres probar otra marca o característica?'
    summaries = [_product_summary(product) for product in selected]
    if len(summaries) == 1:
        return f'Encontré {summaries[0]}. ¿Quieres que busque otra opción?'
    return f'Encontré {summaries[0]} y {summaries[1]}. ¿Quieres otra opción?'

def _format_catalog_lookup_fallback(query: str) -> str:
    subject = _norm(query)[:64].rstrip()
    if subject:
        return f'No encontré información para confirmar la disponibilidad actual de {subject}. ¿Puedes repetir el nombre del producto o consultar otro?'
    return 'No pude entender qué producto buscas. ¿Puedes repetir el nombre del producto?'

def _is_promotion_request(text: str) -> bool:
    return _matches_any(text, PROMOTION_QUERY_PATTERNS)

def _promotion_subject_query(text: str) -> str:
    normalized = _low_ascii(text)
    normalized = re.sub('\\b(promociones?|ofertas?|descuentos?|vigentes?|actuales?|tienen?|hay|para|en|de|con|alguna?s?)\\b', ' ', normalized)
    return _normalize_product_retrieval_query(normalized)

def _is_specific_promotion_request(text: str) -> bool:
    if not _is_promotion_request(text):
        return False
    subject = _promotion_subject_query(text)
    words = set(re.findall('[a-z0-9]+', subject))
    return bool(_canonical_product_category(subject) or words & PRODUCT_BRANDS)

def _parse_promotion_date(value: str) -> date | None:
    match = re.fullmatch('\\s*(\\d{1,2})-([A-Za-z]{3})-(\\d{2,4})\\s*', value)
    if not match:
        return None
    day, month_code, year = match.groups()
    month = PROMOTION_MONTHS.get(month_code.upper())
    if month is None:
        return None
    year_number = int(year)
    if year_number < 100:
        year_number += 2000
    try:
        return date(year_number, month, int(day))
    except ValueError:
        return None

def _parse_promotion_record(content: str, index: int, today: date) -> Dict[str, Any] | None:
    if not _low_ascii(content).startswith('promocion:'):
        return None
    normalized = _low_ascii(content)
    if 'estado: incluido en promo' not in normalized or 'estado: excluido de promo' in normalized:
        return None
    validity = re.search('Vigencia:\\s*desde\\s+([0-9A-Za-z-]+)\\s+hasta\\s+([0-9A-Za-z-]+)', content, flags=re.IGNORECASE)
    if not validity:
        return None
    start_date = _parse_promotion_date(validity.group(1))
    end_date = _parse_promotion_date(validity.group(2))
    if start_date is None or end_date is None or (not start_date <= today <= end_date):
        return None
    promotion_type = _field_from_content(content, 'Tipo de promoción')
    raw_value = _field_from_content(content, 'Valor o porcentaje')
    number_match = re.search('\\d[\\d.,]*', raw_value)
    if not number_match:
        return None
    number = number_match.group(0)
    normalized_type = _low_ascii(promotion_type)
    if normalized_type == 'percentagediscount':
        benefit = f'{number} por ciento de descuento'
    elif normalized_type == 'newprice':
        benefit = f'un precio promocional de {number} pesos dominicanos'
    else:
        return None
    name = _field_from_content(content, 'Promoción')
    if not name:
        return None
    return {'name': name, 'name_ascii': _low_ascii(name), 'benefit': benefit, 'end_date': end_date, 'index': index}

def _select_current_promotions(query: str, contents: List[str], today: date | None=None) -> List[Dict[str, Any]]:
    current_date = today or date.today()
    category_pattern = _canonical_product_category(query)
    query_words = re.findall('[a-z0-9]+', _low_ascii(query))
    requested_brands = [word for word in query_words if word in PRODUCT_BRANDS]
    size_constraints = _query_size_constraints(query)
    model_tokens = _query_model_tokens(query)
    promotions: List[Dict[str, Any]] = []
    seen = set()
    for index, content in enumerate(contents):
        promotion = _parse_promotion_record(content, index, current_date)
        if promotion is None:
            continue
        name = promotion['name_ascii']
        if category_pattern and re.search(category_pattern, name) is None:
            continue
        if requested_brands and (not all((brand in name for brand in requested_brands))):
            continue
        if model_tokens and (not all((token in name for token in model_tokens))):
            continue
        if not _matches_size_constraints(name, size_constraints):
            continue
        if name in seen:
            continue
        seen.add(name)
        promotions.append(promotion)
    promotions.sort(key=lambda item: (item['end_date'], item['index']))
    return promotions

def _format_promotion_answer(promotions: List[Dict[str, Any]]) -> str:
    if not promotions:
        return 'No pude confirmar una promoción vigente para esa búsqueda en este momento. ¿Quieres que busque productos disponibles?'
    promotion = promotions[0]
    return f"Encontré una promoción vigente para {_short_product_name(promotion['name'])}, con {promotion['benefit']}. ¿Quieres consultar otra?"

def _format_qconnect_retrieve_answer(transcript: str, contents: List[str]) -> str:
    if not contents:
        return 'No puedo confirmarlo con la informacion disponible. Deseas consultar otra cosa?'
    product_summaries = []
    seen = set()
    products = _select_available_products(transcript, contents)
    for product in products:
        summary = _product_summary(product)
        key = _low_ascii(summary)
        if summary and key not in seen:
            seen.add(key)
            product_summaries.append(summary)
        if len(product_summaries) == 2:
            break
    if product_summaries:
        if len(product_summaries) == 1:
            return f'Encontré {product_summaries[0]}. Quieres que busque otra opcion?'
        return f'Encontré {product_summaries[0]} y {product_summaries[1]}. Quieres otra opcion?'
    if any((RAW_BRANCH_DATA_PATTERN.search(content) for content in contents[:3])):
        return 'No puedo confirmarlo con la informacion disponible. Puedes indicarme la sucursal exacta?'
    clean = re.sub('\\s+', ' ', contents[0]).strip()
    if len(clean) > 230:
        clean = clean[:227].rstrip(' ,.;') + '...'
    if not clean.endswith(('.', '?', '!')):
        clean += '.'
    return f'{clean} Deseas consultar otra cosa?'

def _handle_direct_qconnect_retrieve(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    branch_response = _handle_branch_info_lookup(session_state, session_attrs, transcript)
    if branch_response is not None:
        return branch_response
    if not _is_direct_retrieve_route(transcript, session_attrs):
        return None
    catalog_availability_request = _is_catalog_availability_request(transcript)
    has_followup_query = _matches_any(transcript, MORE_OPTIONS_PATTERNS) and _has_value(session_attrs.get('qconnect_last_query', '')) and (session_attrs.get('qconnect_context_active') == 'true') and (session_attrs.get('qconnect_context_kind') == 'product')
    query = ''
    if _is_generic_help_menu_request(transcript) and (not has_followup_query):
        message = 'Puedo ayudarte con productos, precios, disponibilidad, promociones, sucursales, horarios y servicios de Plaza Lama. Que deseas consultar?'
        _reset_intent_routing(session_attrs)
        _add_origin(session_attrs, 'preguntas_generales')
        session_attrs['pregunta_general_detectada'] = 'true'
        session_attrs['bedrock_last_response'] = message
        session_attrs['last_agent_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    try:
        if _is_promotion_request(transcript):
            session_attrs['qconnect_context_active'] = 'false'
            session_attrs['qconnect_context_kind'] = 'promotion'
            if not _is_specific_promotion_request(transcript):
                message = '¿Para qué producto deseas consultar promociones?'
            else:
                query = _promotion_subject_query(transcript)
                contents = _retrieve_qconnect_texts(f'promociones {query}')
                promotions = _select_current_promotions(query, contents)
                message = _format_promotion_answer(promotions)
                session_attrs['qconnect_direct_retrieve_count'] = str(len(contents))
                session_attrs['qconnect_last_query'] = query
                pass
        else:
            if has_followup_query:
                query = session_attrs['qconnect_last_query']
                try:
                    offset = int(session_attrs.get('qconnect_result_offset', '0')) + 2
                except ValueError:
                    offset = 2
            else:
                query = _normalize_product_retrieval_query(_resolve_qconnect_query(transcript, session_attrs))
                offset = 0
            if not _has_value(query):
                if _matches_any(transcript, ['\\bprecios?\\b', '\\bcostos?\\b', '\\bcuanto\\b']):
                    message = '¿De qué producto deseas conocer el precio?'
                elif _matches_any(transcript, ['\\bdisponib', '\\btienen\\b', '\\bvenden\\b']):
                    message = '¿Qué producto deseas consultar para verificar disponibilidad?'
                else:
                    message = '¿Qué producto deseas consultar? Por ejemplo, televisor, nevera o lavadora.'
                session_attrs['qconnect_context_active'] = 'false'
                session_attrs['qconnect_context_kind'] = 'product'
                session_attrs.pop('qconnect_last_query', None)
                session_attrs.pop('qconnect_result_offset', None)
                _emit_functional_metric('QConnectEmptyQueryBlocked', 'normalized_empty')
                _reset_intent_routing(session_attrs)
                _add_origin(session_attrs, 'preguntas_generales')
                session_attrs['pregunta_general_detectada'] = 'true'
                session_attrs['bedrock_last_response'] = message
                session_attrs['last_agent_response'] = message
                return _build_elicit_intent_response(session_state, session_attrs, message)
            is_product_request = bool(_canonical_product_category(query) or _canonical_product_category(transcript) or _is_broad_product_query(query) or catalog_availability_request or has_followup_query)
            if is_product_request and _is_broad_product_query(query):
                message = '¿Qué tipo de producto buscas, por ejemplo televisor, nevera o lavadora?'
                session_attrs['qconnect_context_active'] = 'false'
                session_attrs['qconnect_context_kind'] = 'product'
            elif is_product_request:
                contents = _retrieve_qconnect_texts(query)
                products = _select_available_products(query, contents)
                if not products:
                    contents.extend(_retrieve_qconnect_texts(f'{query} disponible'))
                    products = _select_available_products(query, contents)
                if catalog_availability_request and (not products):
                    _emit_functional_metric('QConnectCatalogNoMatch', 'no_current_inventory')
                    message = _format_catalog_lookup_fallback(query)
                else:
                    message = _format_product_answer(products, offset, has_followup_query)
                session_attrs['qconnect_direct_retrieve_count'] = str(len(contents))
                session_attrs['qconnect_last_query'] = query
                session_attrs['qconnect_result_offset'] = str(offset)
                session_attrs['qconnect_context_active'] = 'true'
                session_attrs['qconnect_context_kind'] = 'product'
                pass
            else:
                contents = _retrieve_qconnect_texts(query)
                message = _format_qconnect_retrieve_answer(transcript, contents)
                session_attrs['qconnect_direct_retrieve_count'] = str(len(contents))
                session_attrs['qconnect_last_query'] = query
                session_attrs['qconnect_context_active'] = 'false'
                session_attrs['qconnect_context_kind'] = 'other'
    except Exception as e:
        pass
        message = _format_catalog_lookup_fallback(query) if catalog_availability_request else 'No puedo confirmarlo con la informacion disponible. Deseas consultar otra cosa?'
        session_attrs['qconnect_direct_retrieve_error'] = str(e)[:180]
        session_attrs['qconnect_context_active'] = 'false'
    _reset_intent_routing(session_attrs)
    _add_origin(session_attrs, 'preguntas_generales')
    session_attrs['pregunta_general_detectada'] = 'true'
    session_attrs['bedrock_last_response'] = message
    session_attrs['last_agent_response'] = message
    return _build_elicit_intent_response(session_state, session_attrs, message)

def _force_intent(session_state: Dict[str, Any], intent_name: str, fulfilled: bool=False) -> None:
    current_intent = session_state.get('intent') or {}
    slots = current_intent.get('slots') or {}
    session_state['intent'] = {'name': intent_name, 'state': 'Fulfilled' if fulfilled else 'InProgress', 'confirmationState': 'None', 'slots': slots}

def _searching_message(transcript: str) -> str:
    t = _norm(transcript)
    if _matches_any(t, ['\\bhorarios?\\b', '\\babren?\\b', '\\bcierran?\\b', '\\bhora\\s+de\\b', '\\batienden?\\b', '\\bhorario\\b']):
        return 'Déjame consultar los horarios, un momento por favor...'
    if _matches_any(t, ['\\bubicaci', '\\bdireccion\\b', '\\bdonde\\s+queda\\b', '\\bcomo\\s+llegar\\b', '\\bdonde\\s+est', '\\bdireccion\\b']):
        return 'Permítame verificar esa información de ubicación, un momento...'
    if _matches_any(t, ['\\bprecios?\\b', '\\bcostos?\\b', '\\bcuanto\\s+(cuesta|vale|es)\\b', '\\bofertas?\\b', '\\bdescuento\\b']):
        return 'Estoy consultando esa información, un momento por favor...'
    if _matches_any(t, ['\\btienen\\b', '\\bvenden\\b', '\\bdisponib', '\\bcatalog', '\\bproductos?\\b']):
        return 'Déjame verificar esa información en nuestro sistema, un momento...'
    return 'Permítame un momento, estoy buscando esa información para usted...'

def _build_delegate_response(session_state: Dict[str, Any], session_attrs: Dict[str, str], message: str | None=None) -> Dict[str, Any]:
    if message:
        request_id = _norm(session_attrs.get('_current_originating_request_id', ''))
        previous_id = _norm(session_attrs.get('_delegate_message_request_id', ''))
        if request_id and request_id == previous_id:
            message = None
            _emit_functional_metric('DuplicateDelegateMessageSuppressed', 'same_request')
        elif request_id:
            session_attrs['_delegate_message_request_id'] = request_id
    _force_intent(session_state, INTENT_AMAZON_Q, fulfilled=False)
    session_state['sessionAttributes'] = session_attrs
    session_state['dialogAction'] = {'type': 'Delegate'}
    response: Dict[str, Any] = {'sessionState': session_state}
    if message:
        response['messages'] = [{'contentType': 'PlainText', 'content': _strip_all_tags(message)}]
    pass
    return response

def _build_elicit_intent_response(session_state: Dict[str, Any], session_attrs: Dict[str, str], message: str) -> Dict[str, Any]:
    clean_message = _strip_all_tags(message)
    if not clean_message:
        clean_message = '¿En qué más puedo ayudarte?'
        _emit_functional_metric('EmptyElicitIntentRecovered', 'missing_message')
    session_state['sessionAttributes'] = session_attrs
    session_state['dialogAction'] = {'type': 'ElicitIntent'}
    response: Dict[str, Any] = {'sessionState': session_state, 'messages': [{'contentType': 'PlainText', 'content': clean_message}]}
    pass
    return response

def _build_close_response(session_state: Dict[str, Any], session_attrs: Dict[str, str], message: str='') -> Dict[str, Any]:
    clean_message = _strip_all_tags(message) or 'Gracias por comunicarse con Plaza Lama. Que tenga buen día.'
    _force_intent(session_state, INTENT_CERRAR, fulfilled=True)
    session_attrs.update({'agente': 'false', 'wants_close': 'true', '_closed': 'true', 'tipoestadofinal': 'cierre_cliente', 'resumen_turno': clean_message, 'bedrock_last_response': clean_message, ROUTE_ATTR: ROUTE_CLOSED, 'bedrock_supervisor_active': 'false', 'pregunta_general_detectada': 'false'})
    _add_origin(session_attrs, 'cierre')
    session_state['sessionAttributes'] = session_attrs
    session_state['dialogAction'] = {'type': 'Close'}
    response = {'sessionState': session_state, 'messages': [{'contentType': 'PlainText', 'content': clean_message}]}
    pass
    return response

def _build_agent_transfer_close_response(session_state: Dict[str, Any], session_attrs: Dict[str, str], message: str='') -> Dict[str, Any]:
    clean_message = _strip_all_tags(message) or 'Le estare comunicando con un representante para que pueda ayudarle.'
    current_intent = session_state.get('intent') or {}
    intent_name = current_intent.get('name') or INTENT_AMAZON_Q
    _force_intent(session_state, intent_name, fulfilled=True)
    session_attrs.update({'agente': 'true', 'wants_close': 'false', '_closed': 'false', 'tipoestadofinal': 'agente', 'resumen_turno': clean_message, 'bedrock_last_response': clean_message, ROUTE_ATTR: ROUTE_AGENT_TRANSFER, 'bedrock_supervisor_active': 'false'})
    session_state['sessionAttributes'] = session_attrs
    session_state['dialogAction'] = {'type': 'Close'}
    response = {'sessionState': session_state, 'messages': [{'contentType': 'PlainText', 'content': clean_message}]}
    pass
    return response

def _build_fast_complaint_response(session_state: Dict[str, Any], session_attrs: Dict[str, str], message: str) -> Dict[str, Any]:
    _switch_to_bedrock_supervisor(session_attrs)
    _add_origin(session_attrs, 'quejas')
    session_attrs['servicio'] = 'queja'
    session_attrs['bedrock_last_response'] = message
    return _build_elicit_intent_response(session_state, session_attrs, message)

def _close_if_agent_terminal_action_detected(session_state: Dict[str, Any], session_attrs: Dict[str, str], message: str='', transfer_tag: str='') -> Dict[str, Any] | None:
    normalized_message = _strip_message_tags(message, strip_control_tags=False)
    explicit_transfer = _low_ascii(transfer_tag or _extract_transfer_tag(normalized_message))
    explicit_close = _extract_close_tag(normalized_message)
    clean_message = _strip_all_tags(normalized_message)
    if session_attrs.get('agente') == 'true' or explicit_transfer == 'agente' or _agent_is_handoff(clean_message):
        if explicit_transfer == 'agente':
            _emit_functional_metric('ControlTransferDetected', 'explicit_tag')
        elif _agent_is_handoff(clean_message):
            _emit_functional_metric('LegacyTransferFallback', 'compatibility_phrase')
        return _build_agent_transfer_close_response(session_state, session_attrs, clean_message)
    if explicit_close or _agent_is_close(clean_message):
        if explicit_close:
            _emit_functional_metric('ControlCloseDetected', 'explicit_tag')
        else:
            _emit_functional_metric('LegacyCloseFallback', 'compatibility_phrase')
        return _build_close_response(session_state, session_attrs, clean_message)
    return None

def _close_if_agent_handoff_detected(session_state: Dict[str, Any], session_attrs: Dict[str, str], message: str='', transfer_tag: str='') -> Dict[str, Any] | None:
    return _close_if_agent_terminal_action_detected(session_state, session_attrs, message, transfer_tag)

def _close_if_customer_close_already_detected(session_state: Dict[str, Any], session_attrs: Dict[str, str]) -> Dict[str, Any] | None:
    if session_attrs.get('_closed') == 'true' or session_attrs.get('wants_close') == 'true' or session_attrs.get(ROUTE_ATTR) == ROUTE_CLOSED or (session_attrs.get('tipoestadofinal') == 'cierre_cliente'):
        return _build_close_response(session_state, session_attrs, session_attrs.get('bedrock_last_response') or session_attrs.get('resumen_turno') or 'Gracias por comunicarse con Plaza Lama. Que tenga buen día.')
    return None

def _extract_amazon_q_response(session_attrs: Dict[str, str], request_attrs: Dict[str, str]) -> str:
    return _norm(request_attrs.get(Q_RESPONSE_KEY) or session_attrs.get(Q_RESPONSE_KEY) or '')

def _handle_amazon_q_response_callback(session_state: Dict[str, Any], session_attrs: Dict[str, str], request_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    q_response = _extract_amazon_q_response(session_attrs, request_attrs)
    q_session_arn = _norm(session_attrs.get('x-amz-lex:q-in-connect:session-arn', ''))
    q_conv_status = session_attrs.get('x-amz-lex:q-in-connect:conversation-status', '')
    if not _has_value(transcript) and _has_value(q_session_arn):
        session_attrs[ROUTE_ATTR] = ROUTE_AMAZON_Q
        if _has_value(q_response):
            terminal_response = _close_if_agent_terminal_action_detected(session_state, session_attrs, q_response)
            if terminal_response is not None:
                return terminal_response
            session_attrs['pregunta_general_detectada'] = 'true'
            session_attrs['bedrock_last_response'] = q_response
            return _build_elicit_intent_response(session_state, session_attrs, q_response)
        if q_conv_status == 'PROCESSING':
            return _build_delegate_response(session_state, session_attrs)
        return None
    if not _has_value(transcript) and _has_value(q_response) and (session_attrs.get(ROUTE_ATTR) == ROUTE_AMAZON_Q):
        terminal_response = _close_if_agent_terminal_action_detected(session_state, session_attrs, q_response)
        if terminal_response is not None:
            return terminal_response
        session_attrs['pregunta_general_detectada'] = 'true'
        session_attrs['bedrock_last_response'] = q_response
        return _build_elicit_intent_response(session_state, session_attrs, q_response)
    return None

def _safe_bedrock_session_id(event: Dict[str, Any], session_attrs: Dict[str, str]) -> str:
    existing = session_attrs.get(BEDROCK_SESSION_ATTR, '')
    if _has_value(existing):
        return existing
    raw = event.get('sessionId') or event.get('requestAttributes', {}).get('x-amz-lex:connect-originating-request-id') or event.get('sessionState', {}).get('originatingRequestId') or event.get('inputTranscript') or 'session'
    raw = f'{BEDROCK_SESSION_PREFIX}-{raw}'
    safe = re.sub('[^A-Za-z0-9._:-]', '-', raw)[:100]
    if len(safe) < 2:
        safe = f'{BEDROCK_SESSION_PREFIX}-session'
    session_attrs[BEDROCK_SESSION_ATTR] = safe
    return safe

def _build_intent_agent_input(user_text: str, last_agent_response: str='', session_attrs: Dict[str, str] | None=None, active_intent: str='') -> str:
    user_text = _norm(user_text)
    session_attrs = session_attrs or {}
    control_instruction = '[CONTROL DE CONVERSACION: responde siempre en espanol. Si debes transferir al cliente, incluye exactamente [TRANSFER:AGENTE]. Si la conversacion termino y no haras otra pregunta, incluye exactamente [CLOSE]. No uses esos marcadores en ningun otro caso.]'
    if not _has_value(_norm(last_agent_response)):
        initial_msg = _norm(session_attrs.get('initial_customer_message', ''))
        msg = user_text or initial_msg
        return f'{control_instruction}\n[El cliente fue derivado aqui para gestionar: {active_intent}]\n{msg}'
    return f'{control_instruction}\n{user_text}'

def _invoke_intent_agent(event: Dict[str, Any], session_attrs: Dict[str, str], user_text: str, last_agent_response: str='') -> str:
    active_intent = session_attrs.get('bedrock_active_intent', '')
    agent_config = INTENT_AGENT_MAP.get(active_intent)
    if agent_config is None:
        return ''
    agent_id, agent_alias_id = agent_config
    session_id = _safe_bedrock_session_id(event, session_attrs)
    input_text = _build_intent_agent_input(user_text, last_agent_response, session_attrs, active_intent)
    response = bedrock_intent_runtime.invoke_agent(agentId=agent_id, agentAliasId=agent_alias_id, sessionId=session_id, inputText=input_text, enableTrace=False, endSession=False)
    message = _read_bedrock_agent_completion(response)
    if not _has_value(message):
        message = 'No pude completar la consulta en este momento. Deseas intentar nuevamente o hablar con un representante?'
    session_attrs['bedrock_last_response'] = message
    return message

def _is_bedrock_default_parser_error(error: Exception) -> bool:
    if not isinstance(error, ClientError):
        return False
    details = error.response.get('Error') or {}
    code = _low_ascii(str(details.get('Code', '')))
    message = _low_ascii(str(details.get('Message', '')))
    return code == 'validationexception' and 'default parser' in message and ('parse' in message or 'parser' in message)

def _bedrock_parser_failover_response(error: Exception, session_state: Dict[str, Any], session_attrs: Dict[str, str]) -> Dict[str, Any] | None:
    if not _is_bedrock_default_parser_error(error):
        return None
    count = int(session_attrs.get('bedrock_error_count', '0') or '0') + 1
    session_attrs['bedrock_error_count'] = str(count)
    session_attrs['bedrock_parser_failure'] = 'true'
    _emit_functional_metric('BedrockParserFailure', 'default_parser_validation')
    pass
    return _build_agent_transfer_close_response(session_state, session_attrs, 'No pude completar la gestion automaticamente. Le estare comunicando con un representante para ayudarle.')
EXPLICIT_INTENT_SWITCH_PHRASES = {'quejas': ['tengo una queja', 'tengo otra queja', 'quiero poner una queja', 'quiero hacer una queja', 'quiero registrar una queja', 'necesito poner una queja'], 'reclamaciones': ['tengo una reclamacion', 'tengo otra reclamacion', 'quiero hacer una reclamacion', 'quiero poner una reclamacion', 'quiero reclamar', 'tengo un reclamo']}

def _detect_explicit_intent_switch(transcript: str, current_intent: str, last_agent_response: str='') -> str:
    if not _has_value(transcript):
        return ''
    t = _low_ascii(transcript)
    if current_intent != 'consulta' and _matches_any(transcript, CONSULTA_FACTURA_PATTERNS):
        claim_document_reply = current_intent == 'reclamaciones' and _was_asking_for_claim_document(last_agent_response) and (not _matches_any(transcript, STATUS_PATTERNS))
        if claim_document_reply:
            return ''
        return 'consulta'
    for intent, phrases in EXPLICIT_INTENT_SWITCH_PHRASES.items():
        if intent == current_intent:
            continue
        if any((phrase in t for phrase in phrases)):
            return intent
    return ''

def _wants_explicit_general_escape(transcript: str) -> bool:
    if not _has_value(transcript):
        return False
    return _matches_any(transcript, VAGUE_GENERAL_START_PATTERNS) or _matches_any(transcript, EXPLICIT_NEW_REQUEST_PATTERNS)

def _resolve_active_intent(session_attrs: Dict[str, str], session_state: Dict[str, Any], transcript: str) -> None:
    """Asigna bedrock_active_intent (o pending_product_clarification) si aún no hay uno."""
    if session_attrs.get('bedrock_active_intent'):
        return
    if session_attrs.get('pending_product_clarification'):
        return
    if _user_wants_agent(transcript):
        return
    if session_attrs.get(ROUTE_ATTR) == ROUTE_AMAZON_Q:
        return
    lex_intent = (session_state.get('intent') or {}).get('name', '')
    lex_intent_lower = lex_intent.lower()
    if lex_intent_lower in LEX_INTENT_ROUTING:
        detected = lex_intent_lower
    elif _has_value(transcript) and _matches_any(transcript, CONSULTA_FACTURA_PATTERNS):
        detected = 'consulta'
    elif _has_value(transcript) and _is_explicit_general_route(transcript):
        detected = 'general'
    elif _has_value(transcript):
        detected = _classify_with_nova(transcript)
    else:
        detected = 'general'
    if detected in LEX_INTENT_ROUTING:
        _add_origin(session_attrs, detected)
        if _has_value(transcript):
            session_attrs['initial_customer_message'] = transcript
        if detected == 'consulta':
            session_attrs['bedrock_active_intent'] = detected
            session_attrs[ROUTE_ATTR] = ROUTE_BEDROCK_SUPERVISOR
            session_attrs['bedrock_supervisor_active'] = 'true'
        else:
            session_attrs['pending_product_clarification'] = detected
        pass

def _get_product_clarification_question(intent: str) -> str:
    if intent == 'reclamaciones':
        return '¿La reclamacion tiene que ver con un producto comprado en Plaza Lama?'
    return '¿La queja tiene que ver con un producto comprado en Plaza Lama?'

def _handle_product_clarification_pending(event: Dict[str, Any], session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> Dict[str, Any] | None:
    pending_intent = session_attrs.get('pending_product_clarification', '')
    if not pending_intent:
        return None
    clarification_q = _get_product_clarification_question(pending_intent)
    current_prompt = _strip_all_tags(session_attrs.get('bedrock_last_response', ''))
    prompt_already_asked = session_attrs.get('product_clarification_prompted') == pending_intent or _was_product_clarification_question(current_prompt)
    if not prompt_already_asked:
        q_from_transcript = _quick_product_clarification_prompt(transcript)
        clarification_q = q_from_transcript or clarification_q
        session_attrs['bedrock_last_response'] = clarification_q
        session_attrs['last_agent_response'] = clarification_q
        session_attrs['product_clarification_prompted'] = pending_intent
        session_attrs['product_clarification_attempts'] = '0'
        return _build_elicit_intent_response(session_state, session_attrs, clarification_q)
    if _is_yes_to_product_clarification(transcript):
        resolved = 'reclamaciones'
    elif _is_no_to_product_clarification(transcript):
        resolved = 'quejas'
    else:
        attempts = int(session_attrs.get('product_clarification_attempts', '0') or '0') + 1
        session_attrs['product_clarification_attempts'] = str(attempts)
        if attempts >= 2:
            session_attrs.pop('pending_product_clarification', None)
            session_attrs.pop('product_clarification_prompted', None)
            session_attrs.pop('product_clarification_attempts', None)
            return _build_agent_transfer_close_response(session_state, session_attrs, 'No pude confirmar el tipo de solicitud. Le estare comunicando con un representante para ayudarle.')
        session_attrs['bedrock_last_response'] = clarification_q
        session_attrs['last_agent_response'] = clarification_q
        session_attrs['product_clarification_prompted'] = pending_intent
        return _build_elicit_intent_response(session_state, session_attrs, clarification_q)
    _clear_q_routing_context(session_attrs)
    session_attrs['bedrock_active_intent'] = resolved
    session_attrs.pop('pending_product_clarification', None)
    session_attrs.pop('product_clarification_prompted', None)
    session_attrs.pop('product_clarification_attempts', None)
    session_attrs[ROUTE_ATTR] = ROUTE_BEDROCK_SUPERVISOR
    session_attrs['bedrock_supervisor_active'] = 'true'
    initial_msg = _norm(session_attrs.get('initial_customer_message', ''))
    try:
        message = _invoke_intent_agent(event, session_attrs, initial_msg, last_agent_response='')
        session_attrs['bedrock_error_count'] = '0'
    except Exception as e:
        pass
        parser_failover = _bedrock_parser_failover_response(e, session_state, session_attrs)
        if parser_failover is not None:
            return parser_failover
        count = int(session_attrs.get('bedrock_error_count', '0') or '0') + 1
        session_attrs['bedrock_error_count'] = str(count)
        message = 'Para ayudarle con su reclamacion, por favor indiqueme su numero de factura, cedula, RNC, pasaporte o numero de caso.' if resolved == 'reclamaciones' else 'Entiendo, vamos a revisar tu queja. Por favor, comparte tu nombre completo.'
    clean_message = _strip_all_tags(message)
    if _agent_completed_task_by_patterns(clean_message):
        _reset_intent_routing(session_attrs)
    session_attrs['bedrock_last_response'] = clean_message
    session_attrs['last_agent_response'] = clean_message
    transfer = _extract_transfer_tag(message)
    response = _close_if_agent_terminal_action_detected(session_state, session_attrs, message, transfer)
    return response if response is not None else _build_elicit_intent_response(session_state, session_attrs, clean_message)

def _handle_product_clarification_answer(event: Dict[str, Any], session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> Dict[str, Any] | None:
    if not _was_product_clarification_question(last_agent_response):
        return None
    if _is_no_to_product_clarification(transcript):
        _mark_complaint_route(session_attrs)
        message = 'Entiendo, vamos a revisarlo. Por favor, comparte tu nombre completo.'
        session_attrs['bedrock_last_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    if _is_yes_to_product_clarification(transcript):
        _mark_claim_route(session_attrs)
        if _has_value(session_attrs.get('reclamacion_documento', '')):
            return _build_agent_transfer_close_response(session_state, session_attrs, 'Gracias por la informacion. Te comunicare con un representante para dar seguimiento a tu reclamacion.')
        message = 'Claro, te ayudo con eso. Por favor, indícame tu número de factura, cédula, RNC, pasaporte o número de caso.'
        session_attrs['bedrock_last_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    return None

def _complete_complaint_with_supervisor(event: Dict[str, Any], session_state: Dict[str, Any], session_attrs: Dict[str, str], last_agent_response: str) -> Dict[str, Any]:
    detail = session_attrs.get('detalle_queja', '')
    priority = 'alto' if _looks_high_priority_complaint(detail) else 'bajo'
    supervisor_input = f"Continúa el flujo de quejas de Plaza Lama con estos datos ya recopilados. No vuelvas a pedir un dato que ya esté presente. Si falta un dato obligatorio, pregunta únicamente ese dato. Si ya hay datos suficientes, registra el caso usando la herramienta disponible y responde breve al cliente.\n\nservicio: queja\nnombre_cliente: {session_attrs.get('nombre_cliente', '')}\ntelefono_cliente: {session_attrs.get('telefono_cliente', '')}\ndetalle_queja: {detail}\nlugar_queja: {session_attrs.get('lugar_queja', '')}\nfecha_incidente: {session_attrs.get('fecha_incidente', '')}\narea_involucrada: {session_attrs.get('area_involucrada', '')}\npersona_involucrada: {session_attrs.get('persona_involucrada', '')}\nnivel_criticidad: {priority}"
    try:
        message = _invoke_intent_agent(event, session_attrs, supervisor_input, last_agent_response)
    except Exception as e:
        pass
        parser_failover = _bedrock_parser_failover_response(e, session_state, session_attrs)
        if parser_failover is not None:
            return parser_failover
        message = 'Gracias por la información. Vamos a canalizar tu caso para que sea gestionado lo antes posible.'
    clean_message = _strip_all_tags(message)
    session_attrs['bedrock_last_response'] = clean_message
    response = _close_if_agent_terminal_action_detected(session_state, session_attrs, message)
    return response if response is not None else _build_elicit_intent_response(session_state, session_attrs, clean_message)

def _handle_fast_basic_complaint_flow(event: Dict[str, Any], session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> Dict[str, Any] | None:
    if not _has_value(transcript):
        return None
    if _is_simple_complaint_start(transcript) and (not _has_value(last_agent_response)):
        return _build_fast_complaint_response(session_state, session_attrs, 'La queja tiene que ver con un producto comprado en Plaza Lama?')
    if _is_direct_complaint_start(transcript) and (not _has_value(last_agent_response)) and (not _is_direct_claim_start(transcript)):
        session_attrs['detalle_queja'] = _norm(transcript)
        return _build_fast_complaint_response(session_state, session_attrs, 'Para poder ayudarte con tu queja, podrias compartirme tu nombre completo?')
    if _is_direct_claim_start(transcript) and (not _has_value(last_agent_response)):
        _mark_claim_route(session_attrs)
        message = 'Para ayudarle con su reclamacion, por favor indiqueme su numero de factura, cedula, RNC, pasaporte o numero de caso.'
        session_attrs['bedrock_last_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    if _was_product_clarification_question(last_agent_response):
        if _is_no_to_product_clarification(transcript):
            return _build_fast_complaint_response(session_state, session_attrs, 'Para poder ayudarte con tu queja, podrias compartirme tu nombre completo?')
        if _is_yes_to_product_clarification(transcript):
            _mark_claim_route(session_attrs)
            message = 'Para ayudarle con su reclamacion, por favor indiqueme su numero de factura, cedula, RNC, pasaporte o numero de caso.'
            session_attrs['bedrock_last_response'] = message
            return _build_elicit_intent_response(session_state, session_attrs, message)
    if not _is_bedrock_context_active(session_attrs) or session_attrs.get('servicio') != 'queja':
        return None
    if _was_asking_for_name(last_agent_response):
        name = _extract_name_from_text(transcript)
        if _has_value(name):
            session_attrs['nombre_cliente'] = name
            return _build_fast_complaint_response(session_state, session_attrs, 'Para poder ayudarte con tu queja, podrias compartirme tu numero de telefono de contacto?')
    if _was_asking_for_phone(last_agent_response):
        phone = _extract_phone_from_text(transcript)
        if _has_value(phone):
            session_attrs['telefono_cliente'] = phone
            if _has_value(session_attrs.get('detalle_queja', '')):
                return _build_fast_complaint_response(session_state, session_attrs, 'En que sucursal o lugar ocurrio?')
            return _build_fast_complaint_response(session_state, session_attrs, 'Para poder ayudarte con tu queja, podrias describir brevemente que ocurrio?')
    if _was_asking_for_complaint_detail(last_agent_response):
        session_attrs['detalle_queja'] = _norm(transcript)
        return _build_fast_complaint_response(session_state, session_attrs, 'En que sucursal o lugar ocurrio?')
    if _was_asking_for_branch_or_place(last_agent_response):
        branch = _get_canonical_branch_from_text(transcript)
        session_attrs['lugar_queja'] = branch if _has_value(branch) else _norm(transcript)
        return _build_fast_complaint_response(session_state, session_attrs, 'Recuerdas la fecha en que sucedio?')
    if _was_asking_for_incident_date(last_agent_response):
        session_attrs['fecha_incidente'] = _norm(transcript)
        detail = session_attrs.get('detalle_queja', '')
        session_attrs['nivel_queja'] = '4-5' if _looks_high_priority_complaint(detail) else '1-2'
        return _build_agent_transfer_close_response(session_state, session_attrs, 'Gracias por la informacion. Te comunicare con un representante para dar seguimiento a tu queja.')
    if _was_asking_for_area(last_agent_response):
        session_attrs['area_involucrada'] = _norm(transcript)
        detail = session_attrs.get('detalle_queja', '')
        if _mentions_store_personnel(detail):
            return _build_fast_complaint_response(session_state, session_attrs, 'Podrias indicarme el nombre o descripcion de la persona involucrada?')
        return _complete_complaint_with_supervisor(event, session_state, session_attrs, last_agent_response)
    if _was_asking_for_involved_person(last_agent_response):
        session_attrs['persona_involucrada'] = _norm(transcript)
        return _complete_complaint_with_supervisor(event, session_state, session_attrs, last_agent_response)
    return None

def _handle_fast_claim_document_flow(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> Dict[str, Any] | None:
    if not _has_value(transcript):
        return None
    if not (session_attrs.get('bedrock_active_intent') == 'reclamaciones' or session_attrs.get('reclamacion_detectada') == 'true'):
        return None
    pending_document = session_attrs.get('reclamacion_documento_pendiente', '')
    if _has_value(pending_document):
        document_type = ''
        for candidate, patterns in {'Factura': ['\\bfactura\\b'], 'Cedula': ['\\bcedula\\b'], 'RNC': ['\\brnc\\b'], 'Pasaporte': ['\\bpasaporte\\b'], 'Caso': ['\\b(?:caso|numero\\s+de\\s+caso)\\b']}.items():
            if _matches_any(transcript, patterns):
                document_type = candidate
                break
        if not document_type:
            message = 'No pude confirmar el tipo de documento. Indica si es factura, cédula, RNC, pasaporte o número de caso.'
            session_attrs['bedrock_last_response'] = message
            session_attrs['last_agent_response'] = message
            return _build_elicit_intent_response(session_state, session_attrs, message)
        _set_claim_document(session_attrs, document_type, pending_document)
        session_attrs['reclamacion_documento_pendiente'] = ''
        _mark_claim_route(session_attrs)
        return _build_agent_transfer_close_response(session_state, session_attrs, 'Gracias por la información. Te comunicaré con un representante para dar seguimiento a tu reclamación.')
    if _has_value(session_attrs.get('reclamacion_documento', '')):
        _mark_claim_route(session_attrs)
        return _build_agent_transfer_close_response(session_state, session_attrs, 'Gracias por la información. Te comunicaré con un representante para dar seguimiento a tu reclamación.')
    if _was_asking_for_claim_document(last_agent_response) and _low_ascii(transcript) in {'si', 'sí', 'claro', 'ok'}:
        message = 'Por favor indiqueme su numero de factura, cedula, RNC, pasaporte o numero de caso.'
        session_attrs['bedrock_last_response'] = message
        session_attrs['last_agent_response'] = message
        return _build_elicit_intent_response(session_state, session_attrs, message)
    document = _extract_loose_claim_document(transcript)
    if not _has_value(document):
        return None
    session_attrs['reclamacion_documento_pendiente'] = document
    message = f"¿El número {' '.join(document)} corresponde a una factura, cédula, RNC, pasaporte o número de caso?"
    session_attrs['bedrock_last_response'] = message
    session_attrs['last_agent_response'] = message
    return _build_elicit_intent_response(session_state, session_attrs, message)

def _close_claim_if_document_ready(session_state: Dict[str, Any], session_attrs: Dict[str, str], last_agent_response: str) -> Dict[str, Any] | None:
    if not _has_value(session_attrs.get('reclamacion_documento', '')):
        return None
    if not (session_attrs.get('reclamacion_detectada') == 'true' or session_attrs.get('origen_actual') == 'reclamaciones' or _was_product_clarification_question(last_agent_response) or _was_asking_for_claim_document(last_agent_response)):
        return None
    _mark_claim_route(session_attrs)
    return _build_agent_transfer_close_response(session_state, session_attrs, 'Gracias por la informacion. Te comunicare con un representante para dar seguimiento a tu reclamacion.')

def _handle_fast_status_flow(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> Dict[str, Any] | None:
    if not _has_value(transcript):
        return None
    if session_attrs.get('origen_actual') == 'reclamaciones' or session_attrs.get('reclamacion_detectada') == 'true' or _is_direct_claim_start(transcript) or _matches_any(transcript, COMPLAINT_PATTERNS):
        return None
    is_status_turn = session_attrs.get('origen_actual') == 'status' or session_attrs.get('consulta_entrega_detectada') == 'true' or _matches_any(transcript, STATUS_PATTERNS)
    if not is_status_turn:
        return None
    factura = session_attrs.get('consulta_factura', '')
    if not _has_value(factura) and _was_asking_for_status_invoice(last_agent_response):
        factura = _extract_document_from_text(transcript, 'factura') or _extract_loose_claim_document(transcript)
        if _has_value(factura):
            session_attrs['consulta_factura'] = factura
    _switch_to_bedrock_supervisor(session_attrs)
    _add_origin(session_attrs, 'status')
    session_attrs['consulta_entrega_detectada'] = 'true'
    if _has_value(session_attrs.get('consulta_factura', '')):
        return _build_agent_transfer_close_response(session_state, session_attrs, 'Gracias por la informacion. Te comunicare con un representante para revisar el estado de tu pedido.')
    message = 'Para revisar el estado de tu pedido o entrega, por favor indicame tu numero de factura.'
    session_attrs['bedrock_last_response'] = message
    return _build_elicit_intent_response(session_state, session_attrs, message)

def _close_if_user_declines_after_help(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> Dict[str, Any] | None:
    if _is_negative_after_help(transcript) and _looks_like_help_question(last_agent_response):
        session_attrs['_closed'] = 'true'
        session_attrs['wants_close'] = 'true'
        return _build_close_response(session_state, session_attrs, 'Gracias por comunicarse con Plaza Lama. Que tenga buen día.')
    return None

def _handle_agent_request(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    if not _user_wants_agent(transcript):
        return None
    _add_origin(session_attrs, 'agente')
    return _build_agent_transfer_close_response(session_state, session_attrs, 'Le estare comunicando con un representante para que pueda ayudarle.')

def _handle_otros_route(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    if not _is_otros_menu(transcript):
        return None
    _add_origin(session_attrs, 'agente')
    session_attrs['representante'] = 'true'
    return _build_agent_transfer_close_response(session_state, session_attrs, 'Le estare comunicando con un representante que le podrá ayudar.')

def _handle_user_close(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    if not _user_wants_close(transcript):
        return None
    return _build_close_response(session_state, session_attrs, 'Gracias por comunicarse con Plaza Lama. Que tenga buen dia.')

def _handle_general_route(session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str) -> Dict[str, Any] | None:
    if not _has_value(transcript) or _is_bedrock_context_active(session_attrs):
        return None
    if _is_explicit_general_route(transcript) and (not _is_bedrock_route(transcript)):
        _switch_to_amazon_q(session_attrs)
        session_attrs['pregunta_general_detectada'] = 'true'
        _add_origin(session_attrs, 'preguntas_generales')
        return _build_delegate_response(session_state, session_attrs, _searching_message(transcript))
    return None

def _handle_bedrock_route(event: Dict[str, Any], session_state: Dict[str, Any], session_attrs: Dict[str, str], transcript: str, last_agent_response: str) -> Dict[str, Any] | None:
    should_use_bedrock = session_attrs.get(ROUTE_ATTR) == ROUTE_BEDROCK_SUPERVISOR or session_attrs.get('bedrock_supervisor_active') == 'true' or _is_bedrock_route(transcript)
    if not should_use_bedrock or not _has_value(transcript):
        return None
    _switch_to_bedrock_supervisor(session_attrs)
    try:
        message = _invoke_intent_agent(event, session_attrs, transcript, last_agent_response)
        session_attrs['bedrock_error_count'] = '0'
    except Exception as e:
        pass
        parser_failover = _bedrock_parser_failover_response(e, session_state, session_attrs)
        if parser_failover is not None:
            return parser_failover
        count = int(session_attrs.get('bedrock_error_count', '0') or '0') + 1
        session_attrs['bedrock_error_count'] = str(count)
        message = 'No pude completar la consulta en este momento. ¿Deseas intentar nuevamente o hablar con un representante?'
    transfer = _extract_transfer_tag(message)
    clean_message = _strip_all_tags(message)
    if _agent_completed_task_by_patterns(clean_message):
        _reset_intent_routing(session_attrs)
    session_attrs['bedrock_last_response'] = clean_message
    session_attrs['last_agent_response'] = clean_message
    response = _close_if_agent_terminal_action_detected(session_state, session_attrs, message, transfer)
    return response if response is not None else _build_elicit_intent_response(session_state, session_attrs, clean_message)
