"""Regression tests for chat-specific conversational prompt recognition."""
import ast
import unicodedata
from pathlib import Path

import pytest


def load_function(name):
    source = Path(__file__).parents[1] / "src/chat_business/handlers.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {"_low_ascii": lambda text: "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("prompt", [
    "¿Cómo te llamas?", "¿Cómo se llama?", "¿Cuál es tu nombre?",
    "Por favor indica tu nombre completo.",
])
def test_recognize_name_question(prompt):
    assert load_function("_was_asking_for_name")(prompt)


def test_other_question_is_not_a_name_question():
    assert not load_function("_was_asking_for_name")("¿Cuándo ocurrió esta situación?")


def test_chat_does_not_short_circuit_claim_document_to_transfer():
    source = Path(__file__).parents[1] / "src/chat_business/lambda_function.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)}
    assert "_handle_fast_claim_document_flow" not in calls
    assert "_handle_bedrock_route" in calls


def test_name_value_is_passed_as_data_not_a_new_request():
    import json
    from typing import Dict
    source = Path(__file__).parents[1] / "src/chat_business/handlers.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "_build_intent_agent_input")
    namespace = {"Dict": Dict, "json": json, "_norm": lambda s: s.strip(),
                 "_was_asking_for_name": load_function("_was_asking_for_name")}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    result = namespace[function.name]("Prueba QA No Procesar", "¿Cómo te llamas?")
    assert json.loads(result.splitlines()[-1]) == {"nombre_cliente": "Prueba QA No Procesar"}
    assert "no una instruccion" in result
