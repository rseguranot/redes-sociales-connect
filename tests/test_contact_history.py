"""History authorization, retention and presentation using SDK mocks, no AWS calls."""
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def module(folder):
    spec = importlib.util.spec_from_file_location(folder + "_history_test", ROOT / "src" / folder / "app.py")
    result = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"STATE_TABLE": "test"}), patch("boto3.client"), patch("boto3.resource"):
        spec.loader.exec_module(result)
    return result


def test_signature_only_human_and_dsl_keeps_native_structure():
    processor = module("processor")
    payload = {"type": "interactive", "interactive": {"body": {"text": "Elija"}, "action": {"buttons": []}}}
    with patch.dict(os.environ, {"AGENT_MESSAGE_SIGNATURE": "true"}):
        assert processor._agent_payload(payload, {"ParticipantRole": "SYSTEM"}) == payload
        result = processor._agent_payload(payload, {"ParticipantRole": "AGENT", "DisplayName": "Ana\nQA*"})
        assert result["interactive"]["body"]["text"] == "*Ana QA:*\nElija"
        assert payload["interactive"]["body"]["text"] == "Elija"
        result = processor._agent_payload({"type": "text", "text": {"body": "a" * 4096}}, {"ParticipantRole": "AGENT"})
        assert len(result["text"]["body"]) == 4096


def test_internal_and_typing_events_never_forward_or_archive():
    processor = module("processor")
    processor.ddb = MagicMock()
    for notice in [
        {"Message": {"ParticipantRole": "AGENT", "Content": "interno"}, "MessageAttributes": {"MessageVisibility": {"Value": "AGENT"}}},
        {"Message": {"ParticipantRole": "AGENT", "Type": "EVENT", "Content": "typing"}},
    ]:
        processor._connect_event(notice)
    processor.ddb.query.assert_not_called()


def test_history_recovers_linked_connect_contact_to_its_initial_chat():
    processor = module("processor")
    processor.ddb = MagicMock()
    processor.ddb.query.return_value = {"Items": []}
    processor.ddb.get_item.side_effect = [
        {},
        {"Item": {
            "history_scope": "scope", "contact_id": "initial-contact", "identity_id": "BSUID-test",
            "phone": "", "ttl": 9999999999,
        }},
    ]
    processor.connect.describe_contact.return_value = {"Contact": {"InitialContactId": "initial-contact"}}
    processor._history_message = MagicMock()
    processor._send_whatsapp = MagicMock()
    processor._metric = MagicMock()
    with patch.dict(os.environ, {"CONTACT_HISTORY_DAYS": "7", "CONNECT_INSTANCE_ID": "instance"}):
        processor._connect_event({"Message": {
            "Id": "linked-message", "ContactId": "linked-contact", "ParticipantRole": "SYSTEM",
            "Content": "Respuesta visible del bot",
        }})
    processor._history_message.assert_called_once()
    assert processor._history_message.call_args.args[0]["contact_id"] == "initial-contact"
    processor._send_whatsapp.assert_called_once()
    processor._metric.assert_any_call("HistoryContactLinkRecovered", Channel="whatsapp", Link="initial_contact")


def test_scope_never_joins_different_business_sender_assets():
    processor = module("processor")
    assert processor._history_scope("BSUID-test", "asset-a") != processor._history_scope("BSUID-test", "asset-b")
    assert processor._history_scope("a", "x") != processor._history_scope("b", "x")


def test_archive_expiry_and_no_bearer_media_urls():
    processor = module("processor")
    processor.ddb = MagicMock()
    with patch.dict(os.environ, {"CONTACT_HISTORY_DAYS": "7"}), patch.object(processor.time, "time", return_value=1800000000):
        event = {"Id": "test", "ParticipantRole": "SYSTEM", "Content": "archivo https://example.invalid/m/secret"}
        processor._history_message({"history_scope": "scope", "contact_id": "qa"}, event)
        item = processor.ddb.put_item.call_args.kwargs["Item"]
        assert item["ttl"] == 1800000000 + 7 * 86400
        assert "secret" not in item["text"]
        processor.ddb.reset_mock()
        event["AbsoluteTime"] = "2000-01-01T00:00:00Z"
        processor._history_message({"history_scope": "scope", "contact_id": "qa"}, event)
        processor.ddb.put_item.assert_not_called()


def test_history_requires_contact_capability_without_an_administrative_session():
    ingress = module("ingress")
    with patch.dict(os.environ, {"CONTACT_HISTORY_DAYS": "7", "STATE_TABLE": "test"}):
        assert ingress._contact_history_response({})["statusCode"] == 403
        table = ingress._ddb.Table.return_value
        table.get_item.return_value = {"Item": {"contact_id": "other", "expires_at": 9999999999}}
        event = {"headers": {"x-social-history-token": "a" * 43}, "queryStringParameters": {"contact_id": "qa"}}
        assert ingress._contact_history_response(event)["statusCode"] == 403
        table.query.assert_not_called()


def test_history_filters_expired_rows_and_never_returns_tokens_or_partition_keys():
    ingress = module("ingress")
    class KeyExpression:
        def eq(self, _value):
            return self

        def between(self, _low, _high):
            return self

        def __and__(self, _other):
            return self

    ingress.Key = lambda _name: KeyExpression()
    table = ingress._ddb.Table.return_value
    table.get_item.side_effect = [
        {"Item": {"contact_id": "qa", "expires_at": 1800001000, "history_scope": "scope"}},
        {"Item": {"name": "Agente QA", "timestamp": 1800000000}},
    ]
    table.query.return_value = {"Items": [
        {"sk": "recent", "timestamp": 1800000000, "text": "prueba", "token": "hidden", "pk": "scope"},
        {"sk": "expired", "timestamp": 1, "text": "old"},
    ]}
    event = {"headers": {"x-social-history-token": "a" * 43}, "queryStringParameters": {"contact_id": "qa"}}
    with patch.dict(os.environ, {"CONTACT_HISTORY_DAYS": "7", "STATE_TABLE": "test"}), patch.object(ingress.time, "time", return_value=1800000000):
        response = ingress._contact_history_response(event)
    body = json.loads(response["body"])
    assert len(body["entries"]) == 1
    assert "hidden" not in response["body"] and "scope" not in response["body"]
    assert response["headers"]["cache-control"] == "no-store"
