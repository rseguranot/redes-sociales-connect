"""Code-only adapter patch; preserve runtime configuration and business functions."""
import argparse
import json
from pathlib import Path

import boto3
import cfnlint.api
from deploy_identity_voice_trial import template, package, deploy
from deploy_semantic_trial import snapshots_needed, executable


def main():
    parser = argparse.ArgumentParser()
    for key in ('profile', 'account', 'main-stack', 'chat-stack'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name='us-east-1')
    assert session.client('sts').get_caller_identity()['Account'] == args.account
    cf, s3, lamb = (session.client(name) for name in ('cloudformation', 's3', 'lambda'))
    main_doc = template(cf, args.main_stack)
    bucket = main_doc['Resources']['ProcessorFunction']['Properties']['Code']['S3Bucket']
    document = template(cf, args.chat_stack)
    backups = snapshots_needed(lamb, cf, args.chat_stack, document, ('ChatAdapter',))
    if backups:
        deploy(cf, s3, bucket, args.chat_stack, document, backups)
    document = template(cf, args.chat_stack)
    files, _ = executable(lamb, cf, args.chat_stack, 'ChatAdapter')
    files['app.py'] = (Path(__file__).resolve().parents[1] / 'src/chat_adapter/app.py').read_bytes()
    code = package(s3, bucket, files)
    document['Resources']['ChatAdapter']['Properties']['CodeUri'] = f"s3://{bucket}/{code['S3Key']}"
    findings = cfnlint.api.lint(json.dumps(document), regions=['us-east-1'])
    print(json.dumps({'lint_findings': [f.rule.id for f in findings]}), flush=True)
    assert not any(f.rule.id.startswith('E') for f in findings), 'Template lint errors'
    dependencies = {'AliasPolicy', 'ConnectChatAssociation', 'LexPermission'}
    deploy(cf, s3, bucket, args.chat_stack, document,
           {'ChatAdapter', 'ChatAlias', 'ProductionContactFlow'} | dependencies,
           stable_dependencies=dependencies)


if __name__ == '__main__':
    main()
