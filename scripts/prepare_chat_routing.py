"""Prepare one-parameter routing change; never execute it or disclose allowlists."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser()
    for name in ("profile", "region", "account", "main-stack", "chat-stack"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--rollback-file", required=True, type=Path)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if session.client("sts").get_caller_identity()["Account"] != args.account:
        raise ValueError("Wrong AWS account")
    cfn = session.client("cloudformation")
    source = cfn.describe_stacks(StackName=args.chat_stack)["Stacks"][0]
    target = cfn.describe_stacks(StackName=args.main_stack)["Stacks"][0]
    if source["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"} or target["StackStatus"] != "UPDATE_COMPLETE":
        raise ValueError("Both stacks must be stable")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in source["Outputs"]}
    params = {p["ParameterKey"]: p["ParameterValue"] for p in target["Parameters"]}
    if params.get("CreateDevelopmentAiContactFlow") != "true":
        raise ValueError("No managed test flow")
    if not params.get("DevelopmentNoTransferSocialUserId"):
        raise ValueError("Missing protected test identity")
    if not any(value for key, value in params.items() if key.startswith("Development") and
               any(token in key for token in ("UserIds", "PhoneNumbers", "Usernames", "SenderAssetIds"))):
        raise ValueError("Missing test allowlist")
    key = "DevelopmentAiBotAliasArn"
    if params[key] == outputs["ChatAliasArn"]:
        raise ValueError("Routing already uses isolated chat")
    args.rollback_file.parent.mkdir(parents=True, exist_ok=True)
    rollback = {"stack": args.main_stack, "parameter": key,
                "previous": params[key], "next": outputs["ChatAliasArn"]}
    if args.rollback_file.exists():
        if json.loads(args.rollback_file.read_text(encoding="utf-8")) != rollback:
            raise ValueError("Refusing to overwrite a different rollback record")
    else:
        args.rollback_file.write_text(json.dumps(rollback), encoding="utf-8")
    update = [{"ParameterKey": name, "ParameterValue": outputs["ChatAliasArn"]}
              if name == key else {"ParameterKey": name, "UsePreviousValue": True} for name in params]
    change_name = "route-isolated-chat-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    result = cfn.create_change_set(StackName=args.main_stack, ChangeSetName=change_name,
        ChangeSetType="UPDATE", UsePreviousTemplate=True, Parameters=update,
        Capabilities=["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"])
    print(json.dumps({"change_set": result["Id"], "changed_parameter": key,
        "other_parameters_preserved": len(params) - 1, "protected_identity_configured": True}))


if __name__ == "__main__":
    main()
