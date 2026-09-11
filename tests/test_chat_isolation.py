"""Offline structural and privacy regression checks for the independent bot."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_chat_template_owns_bot_and_business_hook():
    t = json.loads((ROOT / "connect/chat-isolated.json").read_text(encoding="utf-8"))
    r = t["Resources"]
    assert r["ChatBot"]["Type"] == "AWS::Lex::Bot"
    assert r["ChatAlias"]["Properties"]["BotId"] == {"Ref": "ChatBot"}
    assert r["BusinessHook"]["Properties"]["CodeUri"] == "../src/chat_business/"
    assert "BusinessHookArn" not in t["Parameters"]
    assert "BotId" not in t["Parameters"]
    assert "ConversationLogSettings" not in r["ChatAlias"]["Properties"]
    assert r["ChatAdapter"]["Properties"]["Environment"]["Variables"]["BUSINESS_HOOK_ARN"] == {
        "Fn::Sub": "${BusinessHook.Arn}:chat"}


def test_business_source_never_logs_conversations():
    for file in (ROOT / "src/chat_business").glob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for item in tree.body:
            if isinstance(item, ast.FunctionDef) and item.name == "_emit_functional_metric":
                continue
            for node in ast.walk(item):
                assert not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == "print"), file.name


def test_business_identifiers_are_configuration_not_source_defaults():
    tree = ast.parse((ROOT / "src/chat_business/config.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ast.unparse(node.func) == "os.environ.get" and node.args:
                assert not str(node.args[0].value).endswith("_ID")


def test_business_permissions_do_not_copy_voice_administrator_access():
    t = json.loads((ROOT / "connect/chat-isolated.json").read_text(encoding="utf-8"))
    statements = t["Resources"]["BusinessHook"]["Properties"]["Policies"][0]["Statement"]
    assert {s["Action"] for s in statements} == {
        "wisdom:Retrieve", "kms:Decrypt", "bedrock:InvokeAgent", "bedrock:InvokeModel"}
    assert all(s["Resource"] != "*" for s in statements)
