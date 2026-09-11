"""Controlled Lex-only smoke tests; not a substitute for real WhatsApp E2E."""
import argparse
import json
import uuid

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--stack", required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)["Stacks"][0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    _, bot, alias = outputs["ChatAliasArn"].rsplit("/", 2)
    lex = session.client("lexv2-runtime")
    scenarios = {
        "tv_context": ["quiero saber el precio de un televisor lg", "de la 27 de febrero",
                       "el precio del televisor", "55", "Otra consulta"],
        "status": ["Estatus de mi pedido"],
        "claim": ["Tengo una reclamación", "sí"],
        "complaint": ["Tengo una queja", "no"],
        "agent": ["Hablar con un agente"],
        "general": ["Información general", "¿Cuál es el horario de La Romana?"],
    }
    for name, messages in scenarios.items():
        sid = "chat-isolation-qa-" + uuid.uuid4().hex
        for index, text in enumerate(messages):
            result = lex.recognize_text(botId=bot, botAliasId=alias, localeId="es_US", sessionId=sid, text=text)
            answer = "\n".join(m.get("content", "") for m in result.get("messages", []))
            action = result.get("sessionState", {}).get("dialogAction", {}).get("type")
            print(json.dumps({"scenario": name, "step": index + 1, "action": action,
                              "response": answer}, ensure_ascii=True), flush=True)
            if name == "tv_context":
                if index in (0, 1, 2):
                    assert "LG" in answer and "pulgadas" in answer
                if index in (1, 2):
                    assert "27 de Febrero" in answer
                if index == 3:
                    assert "sucursal exacta" not in answer
                if index == 4:
                    assert "[opcion] Información general" in answer and action != "Close"
            if name == "agent":
                assert action == "Close"
    print("LEX_SMOKE_COMPLETE")


if __name__ == "__main__":
    main()
