import importlib.util
import copy
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


def test_yes_without_pending_question_is_not_reinterpreted():
    event = {"inputTranscript": "sí", "sessionState": {"sessionAttributes": {"branch_last_code": "PL_TEST"}}}
    assert adapter.prepare(event)["inputTranscript"] == "sí"


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
