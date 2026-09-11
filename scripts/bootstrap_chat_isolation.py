"""One-time, read-only AWS export and mechanical migration for isolated chat.

Never deploys. Writes sanitized reusable source/template and a private parameter
file. Requires an explicit numeric source Lambda version and existing Lex version.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import zipfile
import io

import boto3
from botocore.paginate import Paginator
from samtranslator.yaml_helper import yaml_parse


class Sanitize(ast.NodeTransformer):
    def __init__(self):
        self.in_metrics = False

    def visit_FunctionDef(self, node):
        previous = self.in_metrics
        self.in_metrics = node.name == "_emit_functional_metric"
        result = self.generic_visit(node)
        self.in_metrics = previous
        return result

    def visit_Expr(self, node):
        if (not self.in_metrics and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "print"):
            return ast.copy_location(ast.Pass(), node)
        return self.generic_visit(node)

    def visit_Call(self, node):
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and ast.unparse(node.func.value) == "os.environ" and node.args
                and isinstance(node.args[0], ast.Constant)
                and str(node.args[0].value).endswith("_ID")):
            return ast.copy_location(ast.Subscript(value=node.func.value,
                slice=node.args[0], ctx=ast.Load()), node)
        return self.generic_visit(node)


def convert_schema(value, schema, root):
    if "$ref" in schema:
        schema = root["definitions"][schema["$ref"].split("/")[-1]]
    if isinstance(value, list):
        return [convert_schema(v, schema.get("items", {}), root) for v in value]
    if not isinstance(value, dict):
        return value
    props = schema.get("properties", {})
    if not props:
        return value
    result = {}
    for key, item in value.items():
        target = {"intentName": "Name", "messageGroups": "MessageGroupsList"}.get(key)
        if key == "active" and "IsActive" in props:
            target = "IsActive"
        target = target or next((k for k in props if k.lower() == key.lower()), None)
        if target not in props:
            raise ValueError("Unsupported exported Lex field: " + key)
        result[target] = convert_schema(item, props[target], root)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--source-hook", required=True)
    parser.add_argument("--source-bot", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--connect-instance", required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    if not re.search(r":\d+$", args.source_hook):
        raise ValueError("Source hook must use an immutable numeric version")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if session.client("sts").get_caller_identity()["Account"] != args.account:
        raise ValueError("Wrong AWS account")
    repo = Path(__file__).resolve().parents[1]
    target = repo / "src/chat_business"
    fn = session.client("lambda").get_function(FunctionName=args.source_hook)
    with urllib.request.urlopen(fn["Code"]["Location"], timeout=30) as response:
        archive = response.read()
    # The signed URL is never printed or persisted.
    bundle = zipfile.ZipFile(io.BytesIO(archive))
    if bundle.testzip() is not None:
        raise ValueError("Invalid source archive")
    allowed = {"config.py", "utils.py", "handlers.py", "lambda_function.py", "branch_directory.py"}
    if set(bundle.namelist()) - allowed:
        raise ValueError("Unexpected files in source bundle")
    env = dict(fn["Configuration"].get("Environment", {}).get("Variables", {}))
    config_tree = ast.parse(bundle.read("config.py").decode("utf-8-sig"))
    for node in ast.walk(config_tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and ast.unparse(node.func) == "os.environ.get" and len(node.args) > 1
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[1], ast.Constant)):
            env.setdefault(node.args[0].value, node.args[1].value)
    target.mkdir(exist_ok=True)
    for name in sorted(allowed):
        tree = Sanitize().visit(ast.parse(bundle.read(name).decode("utf-8-sig")))
        code = ast.unparse(ast.fix_missing_locations(tree)) + "\n"
        compile(code, name, "exec")
        if re.search(r"arn:aws:|\b\d{12}\b|[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}", code):
            raise ValueError("Operational identifier remains in " + name)
        output = target / name
        if output.exists() and output.read_text(encoding="utf-8") != code:
            raise ValueError("Refusing to overwrite modified chat source: " + name)
        output.write_text(code, encoding="utf-8")

    cfn = session.client("cloudformation")
    lex = session.client("lexv2-models")
    schema = json.loads(cfn.describe_type(Type="RESOURCE", TypeName="AWS::Lex::Bot")["Schema"])
    locale_schema = schema["definitions"]["BotLocale"]
    intent_schema = locale_schema["properties"]["Intents"]["items"]
    intents = []
    assistant = ""
    keep = {"intentName", "description", "sampleUtterances", "parentIntentSignature",
            "dialogCodeHook", "fulfillmentCodeHook", "initialResponseSetting",
            "intentClosingSetting", "intentConfirmationSetting", "qInConnectIntentConfiguration"}
    # Lex list_intents has no bundled paginator in this SDK version.
    paginator = Paginator(lex.list_intents,
        {"input_token": "nextToken", "output_token": "nextToken", "result_key": "intentSummaries"},
        lex.meta.service_model.operation_model("ListIntents"))
    for page in paginator.paginate(botId=args.source_bot,
            botVersion=args.source_version, localeId="es_US"):
        for summary in page["intentSummaries"]:
            raw = lex.describe_intent(botId=args.source_bot, botVersion=args.source_version,
                                      localeId="es_US", intentId=summary["intentId"])
            fields = {k: v for k, v in raw.items() if k in keep and v != ""}
            item = convert_schema(fields, intent_schema, schema)
            if "QInConnectIntentConfiguration" in item:
                config = item["QInConnectIntentConfiguration"]["QInConnectAssistantConfiguration"]
                assistant = config["AssistantArn"]
                config["AssistantArn"] = {"Ref": "AssistantArn"}
            intents.append(item)
    if not assistant:
        raise ValueError("Missing assistant")
    template = yaml_parse((repo / "connect/chat-adapter.yaml").read_text(encoding="utf-8"))
    params = template["Parameters"]
    del params["BotId"], params["BotVersion"], params["BusinessHookArn"]
    params["AssistantArn"] = {"Type": "String", "AllowedPattern": "^arn:aws:wisdom:.*:assistant/.*$"}
    params["AssistantKmsKeyArn"] = {"Type": "String", "AllowedPattern": "^arn:aws:kms:.*:key/.*$"}
    env = {k: str(v) for k, v in env.items() if k.endswith("_ID") or k == "AMAZON_Q_INTENT_NAME"}
    env["QCONNECT_ASSISTANT_ID"] = assistant.split("/")[-1]
    variables = {"APP_ENV": "chat-test", "BEDROCK_SESSION_PREFIX": "chat-only"}
    values = {"AssistantArn": assistant, "ConnectInstanceArn": args.connect_instance}
    for key, value in env.items():
        pname = "Config" + "".join(s.title() for s in key.split("_"))
        params[pname] = {"Type": "String", "MinLength": 1}
        variables[key] = {"Ref": pname}
        values[pname] = value
    iam = session.client("iam")
    role = fn["Configuration"]["Role"].split("/")[-1]
    for page in iam.get_paginator("list_role_policies").paginate(RoleName=role):
        for name in page["PolicyNames"]:
            doc = iam.get_role_policy(RoleName=role, PolicyName=name)["PolicyDocument"]
            for st in doc.get("Statement", []):
                actions = st.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                if "wisdom:Retrieve" in actions:
                    for ks in doc["Statement"]:
                        if ks.get("Action") == "kms:Decrypt":
                            values["AssistantKmsKeyArn"] = ks["Resource"]
    if "AssistantKmsKeyArn" not in values:
        raise ValueError("Missing scoped KMS key")
    resources = template["Resources"]
    agent_arns = [{"Fn::Sub": "arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:agent-alias/${" +
                   "ConfigBedrock" + name + "AgentId}/${ConfigBedrock" + name + "AgentAliasId}"}
                  for name in ("Quejas", "Reclamaciones", "Consulta")]
    resources["BusinessHook"] = {"Type": "AWS::Serverless::Function", "Properties": {
        "CodeUri": "../src/chat_business/", "Handler": "lambda_function.lambda_handler",
        "Runtime": "python3.14", "Architectures": ["arm64"], "Timeout": 40, "MemorySize": 512,
        "AutoPublishAlias": "chat", "Environment": {"Variables": variables},
        "Policies": [{"Statement": [
            {"Effect": "Allow", "Action": "wisdom:Retrieve", "Resource": {"Ref": "AssistantArn"}},
            {"Effect": "Allow", "Action": "kms:Decrypt", "Resource": {"Ref": "AssistantKmsKeyArn"}},
            {"Effect": "Allow", "Action": "bedrock:InvokeAgent", "Resource": agent_arns},
            {"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": {
                "Fn::Sub": "arn:${AWS::Partition}:bedrock:${AWS::Region}::foundation-model/amazon.nova-micro-v1:0"}}
        ]}]}}
    resources["BusinessLogs"] = {"Type": "AWS::Logs::LogGroup", "DeletionPolicy": "Retain",
        "UpdateReplacePolicy": "Retain", "Properties": {"LogGroupName": {"Fn::Sub": "/aws/lambda/${BusinessHook}"}, "RetentionInDays": 30}}
    own_hook = {"Fn::Sub": "${BusinessHook.Arn}:chat"}
    resources["ChatAdapter"]["Properties"]["Environment"]["Variables"]["BUSINESS_HOOK_ARN"] = own_hook
    resources["ChatAdapter"]["Properties"]["Policies"][0]["Statement"][0]["Resource"] = own_hook
    resources["ChatAdapter"]["DependsOn"] = "BusinessHookAliaschat"
    resources["BotRole"] = {"Type": "AWS::IAM::Role", "Properties": {
        "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
            "Principal": {"Service": "lexv2.amazonaws.com"}, "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": {"Ref": "AWS::AccountId"}},
                          "ArnLike": {"aws:SourceArn": {"Fn::Sub": "arn:${AWS::Partition}:lex:${AWS::Region}:${AWS::AccountId}:bot/*"}}}}]},
        "Policies": [{"PolicyName": "ScopedChatAssistant", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["wisdom:CreateSession", "wisdom:GetAssistant"],
             "Resource": [{"Ref": "AssistantArn"}, {"Fn::Sub": "${AssistantArn}/*"}]},
            {"Effect": "Allow", "Action": ["wisdom:SendMessage", "wisdom:GetNextMessage"],
             "Resource": {"Fn::Sub": "arn:${AWS::Partition}:wisdom:${AWS::Region}:${AWS::AccountId}:session/${ConfigQconnectAssistantId}/*"}},
            {"Effect": "Allow", "Action": ["kms:Decrypt", "kms:GenerateDataKey"], "Resource": {"Ref": "AssistantKmsKeyArn"}}
        ]}}]}}
    resources["ChatBot"] = {"Type": "AWS::Lex::Bot", "Properties": {
        "Name": {"Fn::Sub": "${AWS::StackName}-bot"}, "RoleArn": {"Fn::GetAtt": ["BotRole", "Arn"]},
        "DataPrivacy": {"ChildDirected": False}, "IdleSessionTTLInSeconds": 900,
        "AutoBuildBotLocales": True, "Description": "Independent WhatsApp chat bot; voice is not modified",
        "BotLocales": [{"LocaleId": "es_US", "NluConfidenceThreshold": 0.4, "Intents": intents}]}}
    resources["ChatVersion"] = {"Type": "AWS::Lex::BotVersion", "Properties": {
        "BotId": {"Ref": "ChatBot"}, "Description": "Independent chat baseline",
        "BotVersionLocaleSpecification": [{"LocaleId": "es_US", "BotVersionLocaleDetails": {"SourceBotVersion": "DRAFT"}}]}}
    resources["ChatAlias"]["Properties"]["BotId"] = {"Ref": "ChatBot"}
    resources["ChatAlias"]["Properties"]["BotVersion"] = {"Fn::GetAtt": ["ChatVersion", "BotVersion"]}
    resources["ConnectChatAssociation"] = {"Type": "AWS::Connect::IntegrationAssociation",
        "DependsOn": "AliasPolicy", "Properties": {"InstanceId": {"Ref": "ConnectInstanceArn"},
        "IntegrationArn": {"Fn::GetAtt": ["ChatAlias", "Arn"]}, "IntegrationType": "LEX_BOT"}}
    template["Description"] = "Independent Lex and Lambda business hook for allowlisted WhatsApp chat tests"
    template["Outputs"]["ChatBotId"] = {"Description": "Independent chat bot", "Value": {"Ref": "ChatBot"}}
    template["Outputs"]["BusinessHookArn"] = {"Description": "Chat-owned business hook alias", "Value": own_hook}
    (repo / "connect/chat-isolated.json").write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    args.private_output.write_text(json.dumps([{ "ParameterKey": k, "ParameterValue": v} for k, v in values.items()], indent=2), encoding="utf-8")
    print(json.dumps({"files": len(allowed), "intents": len(intents), "source_sha256": hashlib.sha256(archive).hexdigest(), "resources": len(resources)}))


if __name__ == "__main__":
    main()
