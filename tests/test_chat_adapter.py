import importlib.util
import copy
import json
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("chat_adapter", Path(__file__).parents[1] / "src/chat_adapter/app.py")
adapter = importlib.util.module_from_spec(spec)
with patch("boto3.client"):
    spec.loader.exec_module(adapter)


def test_short_yes_keeps_branch_and_pending_question():
    event = {"inputTranscript": "sí", "sessionState": {"sessionAttributes": {
        "branch_last_code": "PL_TEST", "chat_pending_action": "branch_hours"}}}
    assert adapter.prepare(event)["inputTranscript"] == "horario de PL_TEST"
    assert event["inputTranscript"] == "sí"


def test_explicit_close_overrides_catalog_receipt_and_handoff_state():
    for text in ['finalizar','Finalizar.','quiero finalizar','cerrar el chat',
                 'Por favor, terminaR la conversación','finalizar, gracias']:
        event={'inputTranscript':text,'sessionState':{'sessionAttributes':{
            'chat_semantic_product':'televisor','chat_catalog_options':'[]',
            'agente':'true','chat_receipt_confirm_pending':'true'},
            'intent':{'name':'AmazonQinConnect','slots':{}}}}
        with patch.object(adapter,'semantic_trial',return_value=True), patch.object(adapter,'persist_context',side_effect=lambda r,e:r), patch.object(adapter,'semantic_product') as model, patch.object(adapter,'receipt_context') as receipt:
            result=adapter.lambda_handler(event,None)
        assert result['sessionState']['dialogAction']=={'type':'Close'}
        assert result['sessionState']['intent']['name']=='Cerrar'
        assert result['sessionState']['intent']['state']=='Fulfilled'
        attrs=result['sessionState']['sessionAttributes']
        assert attrs['agente']=='false' and attrs['_closed']=='true'
        assert 'chat_catalog_options' not in attrs
        assert '[plantilla]' not in result['messages'][0]['content']
        model.assert_not_called(); receipt.assert_not_called()


def test_close_does_not_match_negation_purchase_or_incident_description():
    for text in ['no quiero finalizar','finalizar mi compra','quiero cerrar un caso',
                 'al finalizar la compra falló','gracias','no cierres el chat',
                 'quiero finalizar y consultar un pedido']:
        assert adapter.explicit_chat_close({'inputTranscript':text}) is None


def test_nontrial_does_not_enter_new_close_handler():
    with patch.object(adapter,'semantic_trial',return_value=False), patch.object(adapter,'explicit_chat_close') as close, patch.object(adapter,'prepare',return_value={}), patch.object(adapter,'receipt_context',return_value={}), patch.object(adapter,'persist_context',return_value={}):
        adapter.lambda_handler({'inputTranscript':'finalizar'},None)
    close.assert_not_called()


def test_yes_without_pending_question_is_not_reinterpreted():
    event = {"inputTranscript": "sí", "sessionState": {"sessionAttributes": {"branch_last_code": "PL_TEST"}}}
    assert adapter.prepare(event)["inputTranscript"] == "sí"


def semantic_result(data):
    return {'output':{'message':{'content':[{'text':json.dumps(data)}]}}}


def test_semantic_vague_product_asks_without_retrieval():
    event = {'inputTranscript':'Información sobre producto','sessionState':{'sessionAttributes':{}}}
    with patch.dict(adapter.os.environ,{'CHAT_SEMANTIC_MODEL_ID':'test'}), patch.object(adapter.semantic_client,'converse',return_value=semantic_result(
            {'intent':'generic_product','product':'','brand':'','features':''})):
        response = adapter.semantic_product(event)
    assert '¿Qué producto buscas?' in response['messages'][0]['content']
    assert not event.get('_semantic_product')


def test_semantic_rejects_invented_product():
    event = {'inputTranscript':'Información sobre producto','sessionState':{'sessionAttributes':{}}}
    with patch.dict(adapter.os.environ,{'CHAT_SEMANTIC_MODEL_ID':'test'}), patch.object(adapter.semantic_client,'converse',return_value=semantic_result(
            {'intent':'product_search','product':'televisor','brand':'LG','features':''})):
        response = adapter.semantic_product(event)
    assert 'No pude interpretar' in response['messages'][0]['content']
    assert not event.get('_semantic_product')


def test_semantic_options_preserve_grounded_product():
    event = {'inputTranscript':'Ver opciones','sessionState':{'sessionAttributes':{
        'chat_semantic_product':'televisor','chat_semantic_brand':'LG'}}}
    with patch.dict(adapter.os.environ,{'CHAT_SEMANTIC_MODEL_ID':'test'}), patch.object(adapter.semantic_client,'converse',return_value=semantic_result(
            {'intent':'product_options','product':'televisor','brand':'LG','features':''})):
        assert adapter.semantic_product(event) is None
    assert event['inputTranscript']=='precio televisores LG'
    assert event['_semantic_product']


def test_catalog_presentation_uses_only_returned_records():
    event = {'_semantic_product':True,'sessionState':{'sessionAttributes':{'chat_semantic_product':'TV'}}}
    response = {'sessionState':{'sessionAttributes':{'chat_catalog_options':json.dumps([
        {'name':'TV TEST A','price':'RD$ 10'},{'name':'TV TEST B','price':'RD$ 20'}])}},
        'messages':[{'contentType':'PlainText','content':'ignore this generated prose'}]}
    result = adapter.adapt(response,event)
    content = result['messages'][0]['content']
    assert '[plantilla]' in content and '[opcion] Ver producto 2' in content
    assert 'TV TEST A' in content and 'ignore this' not in content


def test_catalog_empty_never_invents_options():
    result = adapter.adapt({'sessionState':{'sessionAttributes':{}},'messages':[]},
                          {'_semantic_product':True,'sessionState':{'sessionAttributes':{}}})
    assert 'No encontré opciones verificables' in result['messages'][0]['content']


def test_trial_cannot_be_enabled_by_lex_attribute_alone():
    with patch.dict(adapter.os.environ,{'CHAT_SEMANTIC_MODEL_ID':'test'}):
        assert not adapter.semantic_trial({'sessionState':{'sessionAttributes':{'chat_semantic_trial':'true'}}})


def test_contact_binding_survives_business_attribute_replacement():
    cid='00000000-0000-0000-0000-000000000001'
    event={'sessionState':{'sessionAttributes':{'social_connect_contact_id':cid}}}
    with patch.dict(adapter.os.environ,{'CONTACT_CONTEXT_INSTANCE_ID':'test'}), patch.object(adapter.contact_client,'update_contact_attributes'):
        result=adapter.persist_context({'sessionState':{'sessionAttributes':{}}},event)
    assert result['sessionState']['sessionAttributes']['social_connect_contact_id']==cid


def test_semantic_store_question_discards_product_state():
    event={'inputTranscript':'Qué sucursales tienen en Santiago?', 'sessionState':{'sessionAttributes':{
        'chat_semantic_product':'televisor','chat_product_active':'true','chat_product_brand':'LG'}}}
    with patch.dict(adapter.os.environ,{'CHAT_SEMANTIC_MODEL_ID':'test'}), patch.object(adapter.semantic_client,'converse',return_value=semantic_result({'intent':'store_information'})):
        assert adapter.semantic_product(event) is None
    assert event['inputTranscript'].startswith('Sucursales: ')
    assert 'chat_product_active' not in event['sessionState']['sessionAttributes']


def test_catalog_body_fits_whatsapp_and_options_match_visible_records():
    event={'_semantic_product':True,'sessionState':{'sessionAttributes':{}}}
    response={'sessionState':{'sessionAttributes':{'chat_catalog_options':json.dumps([
        {'name':'X'*160,'price':'P'*60} for _ in range(5)])}}}
    result=adapter.adapt(response,event)
    text=result['messages'][0]['content']
    assert len(text.split('[opcion]')[0])<1024
    assert text.count('[opcion]')==4
    assert len(json.loads(result['sessionState']['sessionAttributes']['chat_catalog_options']))==4


def test_status_after_authored_invoice_help_discards_stale_lex_handoff():
    event = {"inputTranscript": "Quiero consultar el estatus de mi pedido", "sessionState": {
        "intent": {"name": "Escalate", "state": "Fulfilled", "slots": {}},
        "sessionAttributes": {"last_agent_response": "El número está debajo del código de barras.",
                              "agente": "true"}}}
    prepared = adapter.prepare(event)
    attrs = prepared['sessionState']['sessionAttributes']
    assert prepared['sessionState']['intent']['name'] == 'AmazonQinConnect'
    assert attrs['bedrock_active_intent'] == 'consulta'
    assert 'last_agent_response' not in attrs and 'agente' not in attrs


def test_menu_clears_service_context_but_preserves_connect_identity():
    attrs = {"bedrock_active_intent": "quejas", "nombre_cliente": "Test",
             "pending_product_clarification": "quejas", "routing_mode": "bedrock_supervisor",
             "bedrock_supervisor_session_id": "old-topic", "social_user_id": "test-user",
             "x-amz-lex:q-in-connect:ai-agent-arn": "test-agent", "menu_pending": "true"}
    response = adapter.product_context(turn("menú", attrs))
    result = response["sessionState"]["sessionAttributes"]
    assert "bedrock_active_intent" not in result and "nombre_cliente" not in result
    assert "pending_product_clarification" not in result and "routing_mode" not in result
    assert result["bedrock_supervisor_session_id"] != "old-topic"
    assert result["social_user_id"] == "test-user"
    assert result["x-amz-lex:q-in-connect:ai-agent-arn"] == "test-agent"
    assert result["menu_pending"] == "false"


def test_interactive_followup_keeps_branch():
    event = {"inputTranscript": "Ver dirección", "sessionState": {"sessionAttributes": {"branch_last_code": "PL_TEST"}}}
    assert adapter.prepare(event)["inputTranscript"] == "dirección de PL_TEST"


def test_confirmation_uses_dsl():
    text = adapter.present("¿La queja tiene que ver con un producto comprado en Plaza Lama?", {})
    assert text.startswith("[plantilla]\n")
    assert "[opcion] Sí\n[opcion] No" in text


def test_hours_offer_records_pending_question():
    attrs = {"branch_last_code": "PL_TEST"}
    text = adapter.present("La sucursal está en la avenida. ¿Deseas consultar el horario?", attrs)
    assert attrs["chat_pending_action"] == "branch_hours"
    assert "[opcion] Ver horario" in text


def test_expired_promotion_does_not_present_discount_as_current():
    text = adapter.present("Promoción: Ejemplo. Vigencia: desde 16-MAR-26 hasta 23-MAR-26.", {})
    assert "ya venció" in text


def test_preserve_authored_dsl():
    text = "[plantilla]\n[informacion] Hola\n[opcion] Sí"
    assert adapter.present(text, {}) == text


def test_handoff_close_is_not_turned_into_buttons():
    response = {"sessionState": {"dialogAction": {"type": "Close"}},
                "messages": [{"contentType": "PlainText", "content": "Le comunicaré con un representante."}]}
    assert adapter.adapt(response, {})["messages"][0]["content"] == "Le comunicaré con un representante."


def test_document_confirmation_preserves_leading_zeroes_and_has_buttons():
    text = adapter.present("Documento de prueba: 000-1234567-8. ¿Es correcto?", {})
    assert "000-1234567-8" in text
    assert "[pregunta]\n¿Es correcto?\n[opcion] Sí\n[opcion] No" in text


def test_unambiguous_confirmation_phrase_is_contextual():
    attrs = {"bedrock_last_response": "Documento de prueba: QA. ¿Es correcto?"}
    assert adapter.prepare(turn("Sí, es correcto.", attrs))["inputTranscript"] == "Sí"
    assert adapter.prepare(turn("Sí, es correcto."))["inputTranscript"] == "Sí, es correcto."
    correction = "Sí, pero cambia el documento a QA2"
    assert adapter.prepare(turn(correction, attrs))["inputTranscript"] == correction
    assert adapter.prepare(turn("No", attrs))["inputTranscript"] == "No"


def test_case_lookup_switches_invoice_context_without_changing_identity():
    attrs = {"bedrock_active_intent": "consulta", "social_user_id": "qa",
             "bedrock_supervisor_session_id": "old-invoice"}
    result = adapter.prepare(turn("Quiero consultar el caso 00001234.", attrs))
    updated = result["sessionState"]["sessionAttributes"]
    assert updated["bedrock_active_intent"] == "reclamaciones"
    assert updated["social_user_id"] == "qa"
    assert updated["bedrock_supervisor_session_id"] != "old-invoice"
    assert result["inputTranscript"].endswith("número de caso 00001234")
    for text in ["No quiero consultar el caso 00001234", "Consultar factura 00001234", "Hablar con un agente del caso 00001234"]:
        assert adapter.prepare(turn(text, attrs))["inputTranscript"] == text


def test_complete_new_topic_resets_stale_expected_field():
    attrs = {"bedrock_active_intent": "consulta", "consulta_factura": "pending",
             "bedrock_supervisor_session_id": "old", "social_user_id": "qa"}
    result = adapter.prepare(turn("Quiero saber el horario de la sucursal Herrera", attrs))
    updated = result["sessionState"]["sessionAttributes"]
    assert "bedrock_active_intent" not in updated
    assert "consulta_factura" not in updated
    assert updated["bedrock_supervisor_session_id"] != "old"
    assert updated["social_user_id"] == "qa"


def test_ambiguous_multi_topic_phrase_does_not_force_reset():
    attrs = {"bedrock_active_intent": "consulta", "bedrock_supervisor_session_id": "same"}
    result = adapter.prepare(turn("Necesito la dirección de entrega de mi pedido", attrs))
    assert result["sessionState"]["sessionAttributes"]["bedrock_supervisor_session_id"] == "same"


def test_reply_preference_can_switch_between_voice_and_text():
    voice = adapter.prepare(turn("Respóndeme con una nota de voz", {"social_reply_preference": "text"}))
    assert voice["sessionState"]["sessionAttributes"]["social_reply_preference"] == "audio"
    written = adapter.prepare(turn("Mejor respóndeme por escrito", voice["sessionState"]["sessionAttributes"]))
    assert written["sessionState"]["sessionAttributes"]["social_reply_preference"] == "text"


def test_open_question_does_not_get_yes_no_buttons():
    text = adapter.present("Puedo ayudarte. ¿Cuál es tu nombre?", {})
    assert "\n\n¿Cuál" in text
    assert "[plantilla]" not in text


def test_mobile_format_preserves_bullets_italics_and_identifiers():
    text = "**Resultado**\n\n- Caso 00001234\n- _Solo prueba_\n\n¿Algo más?"
    assert adapter.readable_text(text) == text.replace("**", "*")


def test_voice_case_repetition_becomes_one_bold_identifier():
    text = "Registrado. Su número de caso es 0 0 0 0 1 2 3 4. Le repito, su número de caso es 0 0 0 0 1 2 3 4. ¿Algo más?"
    assert adapter.readable_text(text) == "Registrado.\n\nNúmero de caso: *00001234*.\n\n¿Algo más?"
    different = text.replace("Le repito, su número de caso es 0 0 0 0 1 2 3 4", "Le repito, su número de caso es 0 0 0 0 1 2 3 5")
    assert "Le repito" in adapter.readable_text(different)


def test_closed_response_formats_without_offering_buttons():
    response = {"sessionState": {"dialogAction": {"type": "Close"}},
                "messages": [{"contentType": "PlainText", "content": "**Gracias**. ¿Es correcto?"}]}
    result = adapter.adapt(response, {})["messages"][0]["content"]
    assert result == "*Gracias*.\n\n¿Es correcto?"
    assert "[plantilla]" not in result


def test_contact_capture_is_allowlisted_and_never_replaces_meta_identity():
    response = {"sessionState": {"sessionAttributes": {
        "nombre_cliente": "Prueba QA", "telefono_cliente": "2025550100",
        "detalle_queja": "Detalle ficticio", "agente": "true",
        "social_phone": "provider-value", "token": "secret", "case_id": "email-hash"}}}
    captured = adapter.collected_context(response, turn("Representante"))
    assert captured["social_collected_name"] == "Prueba QA"
    assert captured["social_collected_phone"] == "2025550100"
    assert captured["social_handoff_requested"] == "true"
    assert captured["social_collected_data_source"] == "conversation_unverified"
    assert not {"social_phone", "token", "social_case_number"} & captured.keys()


def test_contact_capture_bounds_untrusted_text():
    response = {"sessionState": {"sessionAttributes": {"detalle_queja": "x" * 50000}}}
    assert len(adapter.collected_context(response, turn("x" * 10000))["social_request_detail"]) == 1200


def test_persistence_uses_only_configured_instance_and_flow_contact():
    contact = "00000000-0000-0000-0000-000000000001"
    event = turn("Prueba QA", {"social_connect_contact_id": contact})
    response = {"sessionState": {"sessionAttributes": {"nombre_cliente": "Prueba QA"}}}
    with patch.dict(adapter.os.environ, {"CONTACT_CONTEXT_INSTANCE_ID": "configured-instance"}), patch.object(adapter, "contact_client") as client:
        adapter.persist_context(response, event)
        args = client.update_contact_attributes.call_args.kwargs
        assert args["InstanceId"] == "configured-instance" and args["InitialContactId"] == contact
        assert args["Attributes"]["social_collected_name"] == "Prueba QA"
        assert response["sessionState"]["sessionAttributes"]["social_context_status"] == "persisted"


def test_lex_probe_does_not_write_a_contact():
    with patch.dict(adapter.os.environ, {"CONTACT_CONTEXT_INSTANCE_ID": "configured-instance"}), patch.object(adapter, "contact_client") as client:
        adapter.persist_context({}, turn("Hola"))
        client.update_contact_attributes.assert_not_called()


def turn(text, attrs=None):
    return {"inputTranscript": text, "sessionState": {"sessionAttributes": copy.deepcopy(attrs or {})}}


def test_real_tv_branch_price_sequence_keeps_goal():
    first = turn("quiero saber el precio de un televisor lg")
    answer = adapter.product_context(first)
    assert "pulgadas" in answer["messages"][0]["content"]
    attrs = answer["sessionState"]["sessionAttributes"]
    second = turn("de la 27 de febrero", attrs)
    answer = adapter.product_context(second)
    assert "LG" in answer["messages"][0]["content"]
    assert "27 de Febrero" in answer["messages"][0]["content"]
    assert "horario" not in answer["messages"][0]["content"]
    third = turn("el precio del televisor", answer["sessionState"]["sessionAttributes"])
    answer = adapter.product_context(third)
    assert "LG" in answer["messages"][0]["content"]
    assert "27 de Febrero" in answer["messages"][0]["content"]
    fourth = turn("55", answer["sessionState"]["sessionAttributes"])
    assert adapter.product_context(fourth) is None
    assert fourth["inputTranscript"] == "precio televisores LG 55 pulgadas"
    assert fourth["rawInputTranscript"] == fourth["inputTranscript"]


def test_tv_unknown_size_can_search_options():
    first = turn("quiero un televisor LG")
    answer = adapter.product_context(first)
    second = turn("Ver opciones", answer["sessionState"]["sessionAttributes"])
    assert adapter.product_context(second) is None
    assert second["inputTranscript"] == "precio televisores LG"


def test_product_request_with_size_does_not_ask_again():
    event = turn("precio de un televisor LG de 55 pulgadas")
    assert adapter.product_context(event) is None
    assert event["inputTranscript"] == "precio televisores LG 55 pulgadas"


def test_brand_and_size_corrections_replace_old_values():
    attrs = {"chat_product_active": "true", "chat_product_brand": "LG", "chat_product_size": "55"}
    event = turn("mejor Samsung de 65 pulgadas", attrs)
    assert adapter.product_context(event) is None
    assert event["inputTranscript"] == "precio televisores SAMSUNG 65 pulgadas"


def test_branch_number_is_not_screen_size():
    event = turn("27 de febrero", {"chat_product_active": "true", "chat_product_brand": "LG"})
    answer = adapter.product_context(event)
    assert "chat_product_size" not in answer["sessionState"]["sessionAttributes"]


def test_topic_changes_and_handoff_are_not_product_searches():
    for text in ["Hablar con un agente", "Tengo una queja del televisor", "Adiós",
                 "horario de la 27 de febrero", "precio de una nevera", "cancelar"]:
        event = turn(text, {"chat_product_active": "true", "chat_product_brand": "LG"})
        assert adapter.product_context(event) is None
        assert event["inputTranscript"] == text
        assert "chat_product_active" not in event["sessionState"]["sessionAttributes"]


def test_menu_and_new_query_do_not_invoke_business_transfer():
    for text in ["menú", "Otra consulta", "otro producto"]:
        event = turn(text, {"chat_product_active": "true", "chat_product_brand": "LG"})
        answer = adapter.product_context(event)
        assert answer["sessionState"]["dialogAction"]["type"] == "ElicitIntent"
        assert answer["messages"][0]["content"].count("[opcion]") == 5
        assert "chat_product_brand" not in answer["sessionState"]["sessionAttributes"]


def test_product_response_never_claims_branch_stock():
    event = turn("precio televisores LG", {"chat_product_active": "true", "chat_product_branch": "Herrera"})
    answer = adapter.adapt({"messages": [{"contentType": "PlainText", "content":
        "No puedo confirmarlo. Puedes indicarme la sucursal exacta?"}]}, event)
    content = answer["messages"][0]["content"]
    assert "sucursal exacta" not in content
    assert "requieren confirmación" in content
    assert "Herrera" in content


def test_product_session_fields_survive_business_hook_response():
    event = turn("precio televisores LG", {"chat_product_active": "true", "chat_product_brand": "LG"})
    answer = adapter.adapt({"messages": []}, event)
    assert answer["sessionState"]["sessionAttributes"]["chat_product_brand"] == "LG"


def test_specific_tv_model_and_technology_are_not_discarded():
    event = turn("quiero el precio del televisor LG OLED C4 de 55 pulgadas")
    assert adapter.product_context(event) is None
    assert event["inputTranscript"] == "precio televisores LG 55 pulgadas C4 OLED"


def test_short_size_with_preposition():
    event = turn("de 55", {"chat_product_active": "true", "chat_product_brand": "LG"})
    assert adapter.product_context(event) is None
    assert event["inputTranscript"] == "precio televisores LG 55 pulgadas"


def test_general_information_is_chat_owned():
    answer = adapter.product_context(turn("Información general"))
    assert answer["sessionState"]["dialogAction"]["type"] == "ElicitIntent"
    assert "[opcion] Consultar producto" in answer["messages"][0]["content"]


def test_status_internal_note_is_not_customer_copy():
    content = adapter.present("El cliente quiere consultar el estado de su pedido, pero necesito la factura.", {})
    assert "El cliente" not in content
    assert "número de factura" in content


def test_claim_replaces_invoice_slots_and_callback():
    event = turn('Esta es la factura para hacer una reclamación. La nevera no funciona.',
                 {'bedrock_active_intent': 'consulta', 'consulta_factura': 'pending'})
    event['sessionState']['intent'] = {'name':'consulta','slots':{'factura':{'value':{'interpretedValue':'bad'}}}}
    event['requestAttributes'] = {'x-amz-lex:bedrock-agent-search-response':'stale'}
    result = adapter.prepare(event)
    assert result['sessionState']['sessionAttributes']['bedrock_active_intent'] == 'reclamaciones'
    assert result['sessionState']['intent']['slots'] == {}
    assert not result['requestAttributes']


def test_receipt_ocr_confirms_barcode_candidate_not_tax_identifier():
    event = turn('Transcripción: FACTURA ITBIS e-NCF E310009999999 RNC 00000000000 99990000111122')
    response = adapter.receipt_context(event)
    attrs = response['sessionState']['sessionAttributes']
    assert attrs['chat_receipt_candidate'] == '99990000111122'
    assert 'código de barras' in response['messages'][0]['content']
    assert '[opcion] Sí' in response['messages'][0]['content']
    assert 'consulta_factura' not in attrs
    confirmation = adapter.receipt_context(turn('Sí', attrs))
    assert confirmation['sessionState']['sessionAttributes']['chat_receipt_confirmed'] == '99990000111122'


def test_receipt_rejects_ambiguous_candidates_and_explains_real_location():
    response = adapter.receipt_context(turn('Transcripción: FACTURA 99990000111122 99990000111123'))
    assert 'chat_receipt_candidate' not in response['sessionState']['sessionAttributes']
    response = adapter.receipt_context(turn('Envíame un modelo del número de factura'))
    assert 'código de barras' in response['messages'][0]['content']
    assert 'INV-' not in response['messages'][0]['content']


def test_branch_in_complaint_detail_does_not_abandon_complaint():
    result = adapter.prepare(turn('Ocurrió en la sucursal Herrera', {'bedrock_active_intent':'quejas'}))
    assert result['sessionState']['sessionAttributes']['bedrock_active_intent'] == 'quejas'
