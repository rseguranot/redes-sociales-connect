"""Generate a separate production stack from reviewed chat resources and flow."""
import json
from pathlib import Path
import yaml


class Intrinsics(yaml.SafeLoader):
    pass


def intrinsic(loader, tag, node):
    value = loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node)
    return {"Ref" if tag == "Ref" else "Fn::" + tag: value}


Intrinsics.add_multi_constructor("!", intrinsic)
ROOT = Path(__file__).resolve().parents[1]


def build():
    template = json.loads((ROOT / "connect/chat-isolated.json").read_text(encoding="utf-8"))
    template["Description"] = "Production WhatsApp AI, independent of voice and test Lex resources"
    params = template["Parameters"]
    for key, pattern in {
        "QueueArn": r"^arn:aws:connect:.*:instance/.*/queue/.*$",
        "HoursArn": r"^arn:aws:connect:.*:instance/.*/operating-hours/.*$",
        "AiAgentArn": r"^arn:aws:wisdom:.*:ai-agent/.*$",
        "AlarmTopicArn": r"^arn:aws:sns:.*$",
    }.items():
        params[key] = {"Type": "String", "AllowedPattern": pattern}
    params["FlowName"] = {"Type": "String", "Default": "00 PROD WhatsApp AI - Atención", "MinLength": 1}
    params["NoTransferSocialUserId"] = {"Type": "String", "MinLength": 1,
        "Description": "Stable social user ID allowed to test handoff without reaching an agent"}
    for key in ("NoTransferPhoneNumber1", "NoTransferPhoneNumber2"):
        params[key] = {"Type": "String", "AllowedPattern": r"^[0-9]{7,15}$",
            "Description": "Explicit test phone allowed to suppress agent transfer"}
    resources = template["Resources"]
    resources["ChatAlias"]["Properties"]["BotAliasName"] = "whatsapp_chat_prod"
    resources["BusinessHook"]["Properties"]["Environment"]["Variables"].update({
        "APP_ENV": "chat-prod", "BEDROCK_SESSION_PREFIX": "chat-prod"})
    adapter = resources["ChatAdapter"]["Properties"]
    adapter["Environment"]["Variables"]["CONTACT_CONTEXT_INSTANCE_ID"] = {
        "Fn::Select": [1, {"Fn::Split": ["instance/", {"Ref": "ConnectInstanceArn"}]}]}
    adapter["Policies"][0]["Statement"].append({"Effect": "Allow",
        "Action": "connect:UpdateContactAttributes",
        "Resource": {"Fn::Sub": "${ConnectInstanceArn}/contact/*"}})
    for name in ["ChatAdapter", "BusinessHook"]:
        resources[name]["Properties"]["ReservedConcurrentExecutions"] = 20
        for suffix, metric, threshold in [("Errors", "Errors", 1), ("Throttles", "Throttles", 1)]:
            resources[name + suffix + "Alarm"] = {"Type": "AWS::CloudWatch::Alarm", "Properties": {
                "AlarmDescription": "Production chat " + metric,
                "Namespace": "AWS/Lambda", "MetricName": metric,
                "Dimensions": [{"Name": "FunctionName", "Value": {"Ref": name}}],
                "Statistic": "Sum", "Period": 60, "EvaluationPeriods": 1,
                "Threshold": threshold, "ComparisonOperator": "GreaterThanOrEqualToThreshold",
                "AlarmActions": [{"Ref": "AlarmTopicArn"}],
                "TreatMissingData": "notBreaching"}}
    main = yaml.load((ROOT / "template.yaml").read_text(encoding="utf-8"), Loader=Intrinsics)
    raw = main["Resources"]["DevelopmentAiContactFlow"]["Properties"]["Content"]["Fn::Sub"]
    flow = json.loads(raw)
    discarded = {"TransferMessage"}
    flow["Actions"] = [a for a in flow["Actions"] if a["Identifier"] not in discarded]
    actions = {a["Identifier"]: a for a in flow["Actions"]}
    for action in flow["Actions"]:
        transitions = action.get("Transitions", {})
        for transition in [transitions] + transitions.get("Conditions", []) + transitions.get("Errors", []):
            if transition.get("NextAction") == "TransferMessage":
                transition["NextAction"] = "MarkHandoff"
    actions["EnableLogging"]["Parameters"]["FlowLoggingBehavior"] = "Disabled"
    actions["SetWorkingQueue"]["Parameters"]["QueueId"] = "${QueueArn}"
    actions["CreateAiSession"]["Parameters"]["WisdomAssistantArn"] = "${AssistantArn}"
    actions["AiBot"]["Parameters"]["LexV2Bot"]["AliasArn"] = "${ChatAlias.Arn}"
    actions["AiBot"]["Parameters"]["LexSessionAttributes"] = {
        "x-amz-lex:q-in-connect:ai-agent-arn": "${AiAgentArn}",
        "social_connect_contact_id": "$.ContactId",
        "social_input_source": "$.Attributes.social_input_source",
        "social_reply_preference": "$.Attributes.social_reply_preference"}
    menu = json.loads(actions["AiBot"]["Parameters"]["Text"])
    menu["whatsapp_outbound"]["interactive"]["body"]["text"] = (
        "Gracias por comunicarse con Plaza Lama, la Súper Tienda. "
        "Soy su asistente virtual. Elija una opción o escriba su consulta.")
    actions["AiBot"]["Parameters"]["Text"] = json.dumps(menu, ensure_ascii=False)
    actions["CaptureAiOutcome"]["Parameters"]["Attributes"] = {
        "flujo": "$.Lex.SessionAttributes.origen_actual",
        "representante": "$.Lex.SessionAttributes.agente",
        "social_context_status": "$.Lex.SessionAttributes.social_context_status"}
    # Do not let an absent optional capture attribute prevent human routing.
    actions["CheckHandoff"]["Parameters"]["ComparisonValue"] = "$.Lex.SessionAttributes.agente"
    actions["CheckNoTransferIdentity"]["Parameters"]["ComparisonValue"] = "$.Attributes.social_user_id"
    actions["CheckNoTransferIdentity"]["Transitions"] = {
        "NextAction": "CheckNoTransferPhone1",
        "Conditions": [{"NextAction": "PersonalTestGreeting", "Condition": {
            "Operator": "Equals", "Operands": ["${NoTransferSocialUserId}"]}}],
        "Errors": [{"NextAction": "CheckNoTransferPhone1", "ErrorType": "NoMatchingCondition"}],
    }
    actions["PersonalTestGreeting"]["Parameters"]["Text"] = (
        "Prueba completada. Esta conversación finalizará sin transferirse a un representante.")
    actions["MarkTestComplete"]["Parameters"]["Attributes"].update({
        "social_handoff_requested": "true", "representante": "true"})
    flow["Actions"].extend([
        {"Identifier": "CheckNoTransferPhone1", "Type": "Compare",
         "Parameters": {"ComparisonValue": "$.Attributes.social_phone"},
         "Transitions": {"NextAction": "CheckNoTransferPhone2", "Conditions": [
             {"NextAction": "PersonalTestGreeting", "Condition": {
                 "Operator": "Equals", "Operands": ["${NoTransferPhoneNumber1}"]}}],
             "Errors": [{"NextAction": "CheckNoTransferPhone2", "ErrorType": "NoMatchingCondition"}]}},
        {"Identifier": "CheckNoTransferPhone2", "Type": "Compare",
         "Parameters": {"ComparisonValue": "$.Attributes.social_phone"},
         "Transitions": {"NextAction": "CheckHours", "Conditions": [
             {"NextAction": "PersonalTestGreeting", "Condition": {
                 "Operator": "Equals", "Operands": ["${NoTransferPhoneNumber2}"]}}],
             "Errors": [{"NextAction": "CheckHours", "ErrorType": "NoMatchingCondition"}]}},
    ])
    actions["CheckHours"]["Parameters"]["HoursOfOperationId"] = "${HoursArn}"
    for condition in actions["AiBot"]["Transitions"]["Conditions"]:
        if condition["Condition"]["Operands"][0].lower() == "agentehumano":
            condition["NextAction"] = "CheckNoTransferIdentity"
    actions["MarkHandoff"]["Parameters"]["Attributes"].update({
        "social_handoff_requested": "true", "representante": "true"})
    actions["ClosedMessage"]["Parameters"]["Text"] = (
        "En este momento no estamos dentro del horario de atención de representantes. "
        "Su conversación queda registrada. Por favor, vuelva a escribirnos durante nuestro horario de atención.")
    actions["AiErrorMessage"]["Parameters"]["Text"] = (
        "No pude continuar la atención automática. Intentaré comunicarle con un representante.")
    actions["MarkError"]["Transitions"] = {"NextAction": "CheckNoTransferIdentity",
        "Errors": [{"NextAction": "CheckNoTransferIdentity", "ErrorType": "NoMatchingError"}]}
    for error in actions["TransferToQueue"]["Transitions"]["Errors"]:
        error["NextAction"] = "QueueUnavailable"
    flow["Actions"].append({"Identifier": "QueueUnavailable", "Type": "MessageParticipant",
        "Parameters": {"Text": "No fue posible conectar con la cola de atención en este momento. Su conversación queda registrada. Por favor, intente nuevamente más tarde."},
        "Transitions": {"NextAction": "Disconnect", "Errors": [{"NextAction": "Disconnect", "ErrorType": "NoMatchingError"}]}})
    resources["ProductionContactFlow"] = {"Type": "AWS::Connect::ContactFlow",
        "DependsOn": "ConnectChatAssociation", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
        "Properties": {"InstanceArn": {"Ref": "ConnectInstanceArn"}, "Name": {"Ref": "FlowName"},
            "Description": "Production WhatsApp AI and real agent handoff with persisted contact context",
            "State": "ACTIVE", "Type": "CONTACT_FLOW",
            "Content": {"Fn::Sub": json.dumps(flow, ensure_ascii=False)}}}
    template["Outputs"]["ProductionContactFlowArn"] = {"Value": {"Fn::GetAtt": ["ProductionContactFlow", "ContactFlowArn"]}}
    return template


def main():
    output = ROOT / "connect/chat-production.json"
    output.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Generated production chat template; no deployment performed.")


if __name__ == "__main__":
    main()
