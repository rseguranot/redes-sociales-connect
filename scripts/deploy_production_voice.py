"""Promote only WhatsApp transport/presentation; preserve trial business routing."""
import argparse
import json
from pathlib import Path

import boto3
import cfnlint.api
from deploy_identity_voice_trial import template, package, deploy
from deploy_semantic_trial import executable, snapshots_needed


def main():
    parser = argparse.ArgumentParser()
    for key in ('profile', 'account', 'main-stack', 'chat-stack'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name='us-east-1')
    assert session.client('sts').get_caller_identity()['Account'] == args.account
    cf, s3, lamb = (session.client(name) for name in ('cloudformation', 's3', 'lambda'))
    root = Path(__file__).resolve().parents[1]
    main_doc = template(cf, args.main_stack)
    bucket = main_doc['Resources']['ProcessorFunction']['Properties']['Code']['S3Bucket']
    assert 'BotVoiceTrialPolicy' in main_doc['Resources'], 'Existing approved TTS permission required'
    for stack, logicals in ((args.chat_stack, ('ChatAdapter',)),
                            (args.main_stack, ('ProcessorFunction', 'MediaFunction'))):
        doc = template(cf, stack)
        backups = snapshots_needed(lamb, cf, stack, doc, logicals)
        if backups:
            deploy(cf, s3, bucket, stack, doc, backups)
        doc = template(cf, stack)
        for logical in logicals:
            files, config = executable(lamb, cf, stack, logical)
            source = 'src/chat_adapter/app.py' if logical == 'ChatAdapter' else 'src/processor/app.py'
            files['app.py'] = (root / source).read_bytes()
            props = doc['Resources'][logical]['Properties']
            env = props['Environment']['Variables']
            code = package(s3, bucket, files)
            if logical == 'ChatAdapter':
                props['CodeUri'] = f"s3://{bucket}/{code['S3Key']}"
                env['CHAT_PRESENTATION_ALL_WHATSAPP'] = 'true'
            else:
                assert config['Environment']['Variables'].get('VOICE_BASELINE_MODULE') == 'production_baseline'
                assert 'production_baseline.py' in files
                props['Code'] = code
                env['VOICE_ALL_PRODUCTION_USERS'] = 'true'
                if logical == 'ProcessorFunction':
                    env['WHATSAPP_BOT_VOICE_ENABLED'] = 'true'
        findings = cfnlint.api.lint(json.dumps(doc), regions=['us-east-1'])
        print(json.dumps({'stack':stack, 'lint_findings':[x.rule.id for x in findings]}), flush=True)
        assert not any(x.rule.id.startswith('E') for x in findings)
        dependencies = {'AliasPolicy', 'ConnectChatAssociation', 'LexPermission'} if stack == args.chat_stack else set()
        allowed = set(logicals) | dependencies
        if stack == args.chat_stack:
            allowed |= {'ChatAlias', 'ProductionContactFlow'}
        deploy(cf, s3, bucket, stack, doc, allowed, stable_dependencies=dependencies)


if __name__ == '__main__':
    main()
