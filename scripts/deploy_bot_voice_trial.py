"""Enable Pedro voice replies on the existing private identity trial only."""
import argparse
import json
from pathlib import Path

import boto3
import cfnlint.api
from deploy_identity_voice_trial import template, package, deploy
from deploy_semantic_trial import executable, snapshots_needed


def main():
    parser=argparse.ArgumentParser()
    for key in ('profile','account','main-stack'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    session=boto3.Session(profile_name=args.profile,region_name='us-east-1')
    assert session.client('sts').get_caller_identity()['Account']==args.account
    cf,s3,lamb=(session.client(name) for name in ('cloudformation','s3','lambda'))
    document=template(cf,args.main_stack)
    bucket=document['Resources']['ProcessorFunction']['Properties']['Code']['S3Bucket']
    files,config=executable(lamb,cf,args.main_stack,'ProcessorFunction')
    env=config['Environment']['Variables']
    assert env.get('VOICE_BASELINE_MODULE')=='production_baseline'
    assert env.get('VOICE_SINGLE_TURN_USER_IDS') and 'production_baseline.py' in files
    backups=snapshots_needed(lamb,cf,args.main_stack,document,('ProcessorFunction',))
    if backups:
        deploy(cf,s3,bucket,args.main_stack,document,backups)
    document=template(cf,args.main_stack)
    files['app.py']=(Path(__file__).resolve().parents[1]/'src/processor/app.py').read_bytes()
    props=document['Resources']['ProcessorFunction']['Properties']
    props['Code']=package(s3,bucket,files)
    props['Environment']['Variables']['WHATSAPP_BOT_VOICE_ENABLED']='true'
    document['Resources']['BotVoiceTrialPolicy']={
        'Type':'AWS::IAM::Policy','Properties':{
            'PolicyName':'BotVoiceTrial','Roles':[config['Role'].rsplit('/',1)[-1]],
            'PolicyDocument':{'Version':'2012-10-17','Statement':[
                {'Effect':'Allow','Action':'polly:SynthesizeSpeech','Resource':'*'},
                {'Effect':'Allow','Action':'connect:GetContactAttributes',
                 'Resource':f"arn:aws:connect:us-east-1:{args.account}:instance/{env['CONNECT_INSTANCE_ID']}/contact/*"}]}}}
    findings=cfnlint.api.lint(json.dumps(document),regions=['us-east-1'])
    print(json.dumps({'lint_findings':[x.rule.id for x in findings]}),flush=True)
    assert not any(x.rule.id.startswith('E') for x in findings)
    deploy(cf,s3,bucket,args.main_stack,document,{'ProcessorFunction','BotVoiceTrialPolicy'})


if __name__=='__main__':main()
