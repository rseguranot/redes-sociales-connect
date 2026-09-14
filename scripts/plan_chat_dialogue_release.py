"""Prepare, validate and review code-only change sets. Never executes a change set."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import boto3
import cfnlint.api
from deploy_identity_voice_trial import template, package
from deploy_semantic_trial import executable


def main():
    parser=argparse.ArgumentParser()
    for key in ('profile','account','main-stack','chat-stack','guard'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--phase',choices=['both','chat','main'],default='both')
    args=parser.parse_args()
    session=boto3.Session(profile_name=args.profile,region_name='us-east-1')
    assert session.client('sts').get_caller_identity()['Account']==args.account
    cf,s3,lamb=(session.client(x) for x in ('cloudformation','s3','lambda'))
    root=Path(__file__).resolve().parents[1]
    main_doc=template(cf,args.main_stack)
    bucket=main_doc['Resources']['ProcessorFunction']['Properties']['Code']['S3Bucket']
    for stack,logicals in [(args.chat_stack,['ChatAdapter']),(args.main_stack,['ProcessorFunction','MediaFunction'])]:
        if args.phase=='chat' and stack!=args.chat_stack:continue
        if args.phase=='main' and stack!=args.main_stack:continue
        state=cf.describe_stacks(StackName=stack)['Stacks'][0]
        assert state['StackStatus']=='UPDATE_COMPLETE', 'Concurrent stack operation; stop'
        original=template(cf,stack)
        original_bytes=json.dumps(original,ensure_ascii=True,sort_keys=True).encode()
        original_hash=hashlib.sha256(original_bytes).hexdigest()
        rollback_key='chat-production/dialogue-release/rollback-'+original_hash+'.json'
        s3.put_object(Bucket=bucket,Key=rollback_key,Body=original_bytes,ContentType='application/json')
        doc=json.loads(original_bytes)
        for logical in logicals:
            files,configuration=executable(lamb,cf,stack,logical)
            # Keep the original full package as content-addressed rollback evidence.
            package(s3,bucket,files)
            source='src/chat_adapter/app.py' if logical=='ChatAdapter' else 'src/processor/app.py'
            files['app.py']=(root/source).read_bytes()
            props=doc['Resources'][logical]['Properties'];code=package(s3,bucket,files)
            if logical=='ChatAdapter':
                props['CodeUri']=f"s3://{bucket}/{code['S3Key']}"
                props['Environment']['Variables']['CHAT_DIALOGUE_SAFETY_ENABLED']='true'
            else:
                assert 'production_baseline.py' in files
                props['Code']=code
        assert all(doc['Resources'][k]==v for k,v in original['Resources'].items() if k not in logicals)
        encoded=json.dumps(doc,ensure_ascii=True).encode()
        findings=cfnlint.api.lint(encoded.decode(),regions=['us-east-1'])
        print(json.dumps({'stack':stack,'lint_rules':[x.rule.id for x in findings]}),flush=True)
        assert not any(x.rule.id.startswith('E') for x in findings)
        guarded=subprocess.run([args.guard,'validate','--payload','--output-format','json','--show-summary','none'],
            input=json.dumps({'rules':[(root/'connect/chat-dialogue.guard').read_text()], 'data':[encoded.decode()]}),
            text=True,capture_output=True,check=False)
        print(json.dumps({'stack':stack,'guard_passed':guarded.returncode==0}),flush=True)
        assert guarded.returncode==0, 'Guard validation failed; no change set created'
        digest=hashlib.sha256(encoded).hexdigest()
        key='chat-production/dialogue-release/'+digest+'.json'
        s3.put_object(Bucket=bucket,Key=key,Body=encoded,ContentType='application/json')
        assert template(cf,stack)==original, 'Concurrent template change; stop'
        name='dialogue-safety-'+str(int(time.time()))
        cf.create_change_set(StackName=stack,ChangeSetName=name,ChangeSetType='UPDATE',
            TemplateURL=f'https://{bucket}.s3.us-east-1.amazonaws.com/{key}',
            Parameters=[{'ParameterKey':p['ParameterKey'],'UsePreviousValue':True} for p in state.get('Parameters',[])],
            Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'])
        while True:
            result=cf.describe_change_set(StackName=stack,ChangeSetName=name)
            if result['Status'] in {'CREATE_COMPLETE','FAILED'}:break
            time.sleep(5)
        assert result['Status']=='CREATE_COMPLETE', 'Change set not ready'
        dependencies={'AliasPolicy','ConnectChatAssociation','LexPermission'} if stack==args.chat_stack else set()
        allowed=set(logicals)|dependencies|({'ChatAlias','ProductionContactFlow'} if dependencies else set())
        changes=[x['ResourceChange'] for x in result.get('Changes',[])]
        def safe(x):
            if x['LogicalResourceId'] not in allowed or x['Action']!='Modify':return False
            if x.get('Replacement','False')=='False':return True
            return (x['LogicalResourceId'] in dependencies and x.get('Replacement')=='Conditional'
                and bool(x.get('Details')) and all(d.get('Evaluation')=='Dynamic' and d.get('CausingEntity')=='ChatAlias.Arn'
                    and d.get('ChangeSource')=='ResourceAttribute' for d in x['Details']))
        assert all(safe(x) for x in changes), 'Unrelated replacement or resource change; do not execute'
        validation=[]
        for page in cf.get_paginator('describe_events').paginate(ChangeSetName=result['ChangeSetId']):
            validation.extend(x for x in page.get('OperationEvents',[]) if x.get('EventType')=='VALIDATION_ERROR')
        print(json.dumps({'stack':stack,'change_set':name,'status':result['Status'],
            'changes':[{k:x.get(k) for k in ['LogicalResourceId','Action','Replacement']} for x in changes],
            'validation_errors':len(validation),'rollback_template_sha256':original_hash,'executed':False}),flush=True)
        assert not validation, 'Validation findings require review'


if __name__=='__main__':main()
