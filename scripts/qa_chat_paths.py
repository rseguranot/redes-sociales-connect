"""Non-reporting Lex regression probes. WhatsApp E2E must be tested separately."""
import argparse
import json
import re
import uuid
import unicodedata

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--stack", required=True)
    parser.add_argument("--scenario", choices=["name", "branches", "menu"], required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)["Stacks"][0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    _, bot, alias = outputs["ChatAliasArn"].rsplit("/", 2)
    scenarios = {
        "name": {"name": ["Tengo una queja", "no", "Prueba QA No Procesar"]},
        "branches": {branch: ["horario de " + branch, "Ver dirección", "Otra consulta"]
                     for branch in ["Duarte", "Herrera", "27 de Febrero", "Carretera Mella",
                                    "Nicolás de Ovando", "Santiago", "La Romana", "Bávaro"]},
        "menu": {"switch": ["Tengo una queja", "no", "menú", "Información general", "Promociones"]},
    }
    client = session.client("lexv2-runtime")
    for name, messages in scenarios[args.scenario].items():
        sid = "chat-qa-" + uuid.uuid4().hex
        for index, text in enumerate(messages):
            result = client.recognize_text(botId=bot, botAliasId=alias,
                localeId="es_US", sessionId=sid, text=text)
            state = result.get("sessionState", {})
            answer = "\n".join(m.get("content", "") for m in result.get("messages", []))
            answer = re.sub(r"\+?\d[\d ()-]{8,}\d", "[telefono]", answer)
            norm = "".join(c for c in unicodedata.normalize("NFKD", answer.lower())
                           if not unicodedata.combining(c))
            if args.scenario == "branches":
                assert state.get("dialogAction", {}).get("type") != "Close", name
                assert ["lunes", "esta en", "[opcion] informacion general"][index] in norm, name
            if args.scenario == "name" and index == 2:
                assert "telefono" in norm, "Name reply did not advance to contact phone"
            if args.scenario == "menu" and index == 4:
                assert state.get("dialogAction", {}).get("type") != "Close"
                assert "queja" not in norm
            print(json.dumps({"scenario": name, "step": index + 1,
                "action": state.get("dialogAction", {}).get("type"),
                "name_captured": bool(state.get("sessionAttributes", {}).get("nombre_cliente")),
                "response": answer}, ensure_ascii=True), flush=True)
    print("QA_SCENARIO_COMPLETE", args.scenario)


if __name__ == "__main__":
    main()
