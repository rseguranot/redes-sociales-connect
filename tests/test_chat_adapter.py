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
