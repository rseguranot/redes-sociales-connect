"""Production flow invariants; no AWS calls or customer data."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("production_builder", ROOT / "scripts/build_production_chat_template.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_generated_template_matches_source():
    assert json.loads((ROOT / "connect/chat-production.json").read_text(encoding="utf-8")) == builder.build()


def test_all_transitions_resolve_and_test_suppression_is_scoped():
    template = builder.build()
    flow = json.loads(template["Resources"]["ProductionContactFlow"]["Properties"]["Content"]["Fn::Sub"])
    actions = {a["Identifier"]: a for a in flow["Actions"]}
    assert flow["StartAction"] in actions
    assert {"PersonalTestGreeting", "CheckNoTransferIdentity", "CheckNoTransferPhone1",
            "CheckNoTransferPhone2", "MarkTestComplete"} <= actions.keys()
    for action in actions.values():
        transitions = action.get("Transitions", {})
        for transition in [transitions] + transitions.get("Conditions", []) + transitions.get("Errors", []):
            if "NextAction" in transition:
                assert transition["NextAction"] in actions
    human = [c for c in actions["AiBot"]["Transitions"]["Conditions"]
             if c["Condition"]["Operands"][0].lower() == "agentehumano"]
    assert human and all(c["NextAction"] == "CheckNoTransferIdentity" for c in human)
    assert actions["MarkHandoff"]["Transitions"]["NextAction"] == "TransferToQueue"
    assert actions["CheckHandoff"]["Parameters"]["ComparisonValue"] == "$.Lex.SessionAttributes.agente"
    assert actions["AiBot"]["Parameters"]["LexSessionAttributes"]["social_connect_contact_id"] == "$.ContactId"
    assert actions["CheckNoTransferIdentity"]["Parameters"]["ComparisonValue"] == "$.Attributes.social_user_id"
    assert actions["CheckNoTransferPhone1"]["Parameters"]["ComparisonValue"] == "$.Attributes.social_phone"
    assert actions["CheckNoTransferPhone2"]["Parameters"]["ComparisonValue"] == "$.Attributes.social_phone"
    assert actions["CheckNoTransferPhone2"]["Transitions"]["NextAction"] == "CheckHours"
    assert actions["MarkTestComplete"]["Transitions"]["NextAction"] == "Disconnect"
    assert actions["MarkError"]["Transitions"]["NextAction"] == "CheckNoTransferIdentity"


def test_production_is_separate_and_contact_write_is_scoped():
    resources = builder.build()["Resources"]
    assert resources["ChatAlias"]["Properties"]["BotAliasName"] == "whatsapp_chat_prod"
    assert resources["BusinessHook"]["Properties"]["Environment"]["Variables"]["APP_ENV"] == "chat-prod"
    statements = resources["ChatAdapter"]["Properties"]["Policies"][0]["Statement"]
    writes = [s for s in statements if s["Action"] == "connect:UpdateContactAttributes"]
    assert writes == [{"Effect": "Allow", "Action": "connect:UpdateContactAttributes",
                       "Resource": {"Fn::Sub": "${ConnectInstanceArn}/contact/*"}}]
