"""Entry point del Lambda — solo contiene lambda_handler."""
from typing import Any, Dict
import json
from config import ROUTE_ATTR, ROUTE_AMAZON_Q, SEARCH_RESPONSE_KEY
from utils import _norm, _has_value, _strip_message_tags
from handlers import _initialize_session_attrs, _resolve_active_intent, _handle_user_close, _close_if_customer_close_already_detected, _close_if_agent_terminal_action_detected, _handle_amazon_q_response_callback, _apply_complaint_fields_from_action_input, _apply_contextual_user_answer_fields, _apply_claim_fields, _handle_product_clarification_pending, _handle_main_menu_selection, _handle_agent_request, _handle_otros_route, _handle_explicit_service_intent, _handle_bedrock_route, _handle_general_route, _build_delegate_response, _build_elicit_intent_response, _switch_to_amazon_q, _add_origin, _detect_explicit_intent_switch, _wants_explicit_general_escape, _reset_intent_routing, _close_if_user_declines_after_help, _build_agent_transfer_close_response, _handle_fast_basic_complaint_flow, _handle_fast_claim_document_flow, _handle_fast_status_flow, _close_claim_if_document_ready, _is_bedrock_context_active, _is_bedrock_route, _searching_message, _handle_direct_qconnect_retrieve, ROUTE_BEDROCK_SUPERVISOR, EXPLICIT_INTENT_SWITCH_PHRASES

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if event.get('source') == 'aws.events' or event.get('detail-type') == 'Scheduled Event':
        pass
        return {'statusCode': 200}
    pass
    transcript = _norm(event.get('inputTranscript', ''))
    raw_transcript = _norm(event.get('rawInputTranscript', ''))
    if not _has_value(transcript) and _has_value(raw_transcript):
        transcript = raw_transcript
    session_state = event.get('sessionState') or {}
    session_attrs = session_state.get('sessionAttributes') or {}
    request_attrs = event.get('requestAttributes') or {}
    recover_unmarked_first_turn = str(request_attrs.get('x-amz-lex:channels:platform', '')).lower() == 'connect' and '_closed' not in session_attrs and ('menu_selection' not in session_attrs)
    session_attrs = _initialize_session_attrs(session_attrs)
    originating_request_id = _norm(request_attrs.get('x-amz-lex:connect-originating-request-id') or session_state.get('originatingRequestId') or '')
    if originating_request_id:
        session_attrs['_current_originating_request_id'] = originating_request_id
    else:
        session_attrs.pop('_current_originating_request_id', None)
    response = _handle_main_menu_selection(session_state, session_attrs, transcript, recover_unmarked_first_turn=recover_unmarked_first_turn)
    if response is not None:
        return response
    response = _handle_agent_request(session_state, session_attrs, transcript)
    if response is not None:
        return response
    response = _handle_otros_route(session_state, session_attrs, transcript)
    if response is not None:
        return response
    raw_last_agent_response = _norm(request_attrs.get(SEARCH_RESPONSE_KEY) or session_attrs.get(SEARCH_RESPONSE_KEY) or session_attrs.get('last_agent_response') or session_attrs.get('bedrock_last_response') or '')
    last_agent_response = _strip_message_tags(raw_last_agent_response)
    pass
    pass
    response = _handle_user_close(session_state, session_attrs, transcript)
    if response is not None:
        return response
    response = _close_if_user_declines_after_help(session_state, session_attrs, transcript, last_agent_response)
    if response is not None:
        return response
    response = _close_if_customer_close_already_detected(session_state, session_attrs)
    if response is not None:
        return response
    response = _close_if_agent_terminal_action_detected(session_state, session_attrs, raw_last_agent_response)
    if response is not None:
        return response
    response = _handle_amazon_q_response_callback(session_state, session_attrs, request_attrs, transcript)
    if response is not None:
        return response
    _apply_complaint_fields_from_action_input(session_attrs, request_attrs)
    _apply_contextual_user_answer_fields(session_attrs, transcript, last_agent_response)
    _apply_claim_fields(session_attrs, transcript, request_attrs)
    response = _handle_fast_claim_document_flow(session_state, session_attrs, transcript, last_agent_response)
    if response is not None:
        return response
    if session_attrs.get('pending_product_clarification'):
        response = _handle_product_clarification_pending(event, session_state, session_attrs, transcript, last_agent_response)
        if response is not None:
            return response
    response = _handle_explicit_service_intent(session_state, session_attrs, transcript)
    if response is not None:
        return response
    raw_last_agent_response = _norm(request_attrs.get(SEARCH_RESPONSE_KEY) or session_attrs.get(SEARCH_RESPONSE_KEY) or session_attrs.get('last_agent_response') or session_attrs.get('bedrock_last_response') or '')
    last_agent_response = _strip_message_tags(raw_last_agent_response)
    response = _handle_direct_qconnect_retrieve(session_state, session_attrs, transcript)
    if response is not None:
        return response
    _resolve_active_intent(session_attrs, session_state, transcript)
    if session_attrs.get('pending_product_clarification'):
        response = _handle_product_clarification_pending(event, session_state, session_attrs, transcript, last_agent_response)
        if response is not None:
            return response
    if session_attrs.get('bedrock_active_intent'):
        if not _has_value(transcript):
            msg = last_agent_response or 'Hola, en que puedo ayudarte?'
            session_attrs['bedrock_last_response'] = msg
            return _build_elicit_intent_response(session_state, session_attrs, msg)
        current_intent = session_attrs.get('bedrock_active_intent', '')
        new_intent = _detect_explicit_intent_switch(transcript, current_intent, last_agent_response)
        if new_intent:
            _reset_intent_routing(session_attrs)
            _add_origin(session_attrs, new_intent)
            session_attrs['initial_customer_message'] = transcript
            if new_intent == 'consulta':
                session_attrs['bedrock_active_intent'] = new_intent
                session_attrs[ROUTE_ATTR] = ROUTE_BEDROCK_SUPERVISOR
                session_attrs['bedrock_supervisor_active'] = 'true'
            else:
                session_attrs['pending_product_clarification'] = new_intent
                question = '¿La queja tiene que ver con un producto comprado en Plaza Lama?' if new_intent == 'quejas' else '¿La reclamación tiene que ver con un producto comprado en Plaza Lama?'
                session_attrs['bedrock_last_response'] = question
                session_attrs['last_agent_response'] = question
                session_attrs['product_clarification_prompted'] = new_intent
                return _build_elicit_intent_response(session_state, session_attrs, question)
        elif _wants_explicit_general_escape(transcript) and current_intent != 'consulta':
            _reset_intent_routing(session_attrs)
            _switch_to_amazon_q(session_attrs)
            session_attrs['pregunta_general_detectada'] = 'true'
            _add_origin(session_attrs, 'preguntas_generales')
            return _build_delegate_response(session_state, session_attrs, _searching_message(transcript))
        response = _handle_bedrock_route(event, session_state, session_attrs, transcript, last_agent_response)
        if response is not None:
            return response
        return _build_elicit_intent_response(session_state, session_attrs, last_agent_response or 'Hola, en que puedo ayudarte?')
    if not _has_value(transcript):
        if _has_value(last_agent_response):
            session_attrs['bedrock_last_response'] = last_agent_response
            return _build_elicit_intent_response(session_state, session_attrs, last_agent_response)
        q_conv_status = session_attrs.get('x-amz-lex:q-in-connect:conversation-status', '')
        if session_attrs.get(ROUTE_ATTR) == ROUTE_AMAZON_Q:
            if q_conv_status == 'READY':
                return _build_elicit_intent_response(session_state, session_attrs, '')
            return _build_delegate_response(session_state, session_attrs)
        return _build_elicit_intent_response(session_state, session_attrs, 'Hola, en que puedo ayudarte?')
    response = _handle_general_route(session_state, session_attrs, transcript)
    if response is not None:
        return response
    _switch_to_amazon_q(session_attrs)
    return _build_delegate_response(session_state, session_attrs, _searching_message(transcript))
