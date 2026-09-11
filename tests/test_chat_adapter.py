import importlib.util
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
