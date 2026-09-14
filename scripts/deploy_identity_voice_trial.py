"""Scoped, versioned release using the exact deployed CloudFormation templates."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request
import zipfile

import boto3


def template(cf, stack):
    value = cf.get_template(StackName=stack, TemplateStage='Original')['TemplateBody']
    return json.loads(value) if isinstance(value, str) else value


def deploy(cf, s3, bucket, stack, document, allowed, updates=None, stable_dependencies=None):
    encoded = json.dumps(document, ensure_ascii=True).encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest()
    key = 'chat-production/identity-trial/' + digest + '.json'
    s3.put_object(Bucket=bucket, Key=key, Body=encoded, ContentType='application/json')
    parameters = {p['ParameterKey']: {'ParameterKey':p['ParameterKey'], 'UsePreviousValue':True}
                  for p in cf.describe_stacks(StackName=stack)['Stacks'][0].get('Parameters', [])}
    for name, value in (updates or {}).items():
        parameters[name] = {'ParameterKey':name, 'ParameterValue':value}
    name = 'identity-trial-' + str(int(time.time()))
    cf.create_change_set(StackName=stack, ChangeSetName=name, ChangeSetType='UPDATE',
                         TemplateURL=f'https://{bucket}.s3.us-east-1.amazonaws.com/{key}',
                         Parameters=list(parameters.values()),
                         Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'])
    while True:
        result = cf.describe_change_set(StackName=stack, ChangeSetName=name)
        if result['Status'] in {'CREATE_COMPLETE', 'FAILED'}:
            break
        time.sleep(5)
    if result['Status'] == 'FAILED':
        cf.delete_change_set(StackName=stack, ChangeSetName=name)
        if "didn't contain changes" in result.get('StatusReason', ''):
            print(stack + ' no changes', flush=True)
            return
        raise RuntimeError('Change set creation failed; inspect CloudFormation validation')
    changes = [entry['ResourceChange'] for entry in result.get('Changes', [])]
    summary = [{k:entry.get(k) for k in ('LogicalResourceId','Action','Replacement')} for entry in changes]
    print(json.dumps({'stack':stack, 'reviewed_changes':summary}), flush=True)
    print(json.dumps({'dependency_review':[{ 'resource':entry['LogicalResourceId'], 'details':entry.get('Details',[])} for entry in changes if entry.get('Replacement') in ('Conditional','True')]}),flush=True)
    original = template(cf,stack)
    def safe_dependency(entry):
        logical = entry['LogicalResourceId']
        return (logical in (stable_dependencies or set())
                and entry.get('Replacement') == 'Conditional'
                and document['Resources'][logical] == original['Resources'][logical]
                and bool(entry.get('Details'))
                and all(d.get('Evaluation') == 'Dynamic'
                        and d.get('ChangeSource') == 'ResourceAttribute'
                        and d.get('CausingEntity') == 'ChatAlias.Arn'
                        for d in entry['Details'])
                and document['Resources']['ChatAlias'] == original['Resources']['ChatAlias'])
    if any(entry['LogicalResourceId'] not in allowed or entry['Action'] == 'Remove'
           or ((entry.get('Replacement') or 'False') != 'False' and not safe_dependency(entry)) for entry in changes):
        cf.delete_change_set(StackName=stack, ChangeSetName=name)
        raise RuntimeError('Unrelated change or replacement rejected')
    previous_ids = {logical:cf.describe_stack_resource(StackName=stack,LogicalResourceId=logical)['StackResourceDetail']['PhysicalResourceId'] for logical in (stable_dependencies or set())}
    cf.execute_change_set(StackName=stack, ChangeSetName=name)
    while True:
        status = cf.describe_stacks(StackName=stack)['Stacks'][0]['StackStatus']
        if status == 'UPDATE_COMPLETE':
            assert all(cf.describe_stack_resource(StackName=stack,LogicalResourceId=logical)['StackResourceDetail']['PhysicalResourceId'] == physical for logical,physical in previous_ids.items()), 'Dependent resource identity changed'
            print(stack + ' UPDATE_COMPLETE', flush=True)
            return
        if status not in {'UPDATE_IN_PROGRESS','UPDATE_COMPLETE_CLEANUP_IN_PROGRESS'}:
            raise RuntimeError('Stack update did not complete: ' + status)
        time.sleep(5)


def snapshot(document, logical, suffix):
    name = logical + suffix
    document['Resources'][name] = {'Type':'AWS::Lambda::Version', 'DeletionPolicy':'Retain',
        'UpdateReplacePolicy':'Retain', 'Properties':{'FunctionName':{'Ref':logical},
        'Description':'Immutable rollback snapshot for identity-scoped chat release'}}
    return name


def pin_adapter_arn(value, arn, logical='ChatAdapter'):
    """Keep Lex's unchanged Lambda ARN stable during a code-only update."""
    if value == {'Fn::GetAtt':[logical,'Arn']}:
        return arn
    if isinstance(value,dict):
        return {key:pin_adapter_arn(item,arn,logical) for key,item in value.items()}
    if isinstance(value,list):
        return [pin_adapter_arn(item,arn,logical) for item in value]
    if isinstance(value,str):
        return value.replace('${'+logical+'.Arn}',arn)
    return value


def package(s3, bucket, files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    blob = buffer.getvalue()
    key = 'chat-production/identity-trial/' + hashlib.sha256(blob).hexdigest() + '.zip'
    s3.put_object(Bucket=bucket, Key=key, Body=blob)
    return {'S3Bucket':bucket, 'S3Key':key}


def main():
    parser = argparse.ArgumentParser()
    for name in ('profile','account','main-stack','chat-stack','phones','user-ids'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name='us-east-1')
    assert session.client('sts').get_caller_identity()['Account'] == args.account
    cf, s3, lamb = (session.client(name) for name in ('cloudformation','s3','lambda'))
    root = Path(__file__).resolve().parents[1]
    main_doc = template(cf, args.main_stack)
    chat_doc = template(cf, args.chat_stack)
    bucket = main_doc['Resources']['ProcessorFunction']['Properties']['Code']['S3Bucket']
    baselines = {}
    for logical in ('ProcessorFunction','MediaFunction'):
        physical = cf.describe_stack_resource(StackName=args.main_stack, LogicalResourceId=logical)['StackResourceDetail']['PhysicalResourceId']
        code = lamb.get_function(FunctionName=physical)
        with urllib.request.urlopen(code['Code']['Location'], timeout=30) as response:
            blob = response.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            # Reruns preserve the original production baseline instead of nesting it.
            baselines[logical] = archive.read('production_baseline.py' if 'production_baseline.py' in archive.namelist() else 'app.py')
    suffix = 'PreVoiceTrial20260914'
    names = {snapshot(main_doc, logical, suffix) for logical in ('ProcessorFunction','MediaFunction')}
    deploy(cf,s3,bucket,args.main_stack,main_doc,names)
    chat_names = {snapshot(chat_doc,'ChatAdapter',suffix)}
    deploy(cf,s3,bucket,args.chat_stack,chat_doc,chat_names)
    main_doc = template(cf,args.main_stack)
    for name in ('VoiceSingleTurnPhoneNumbers','VoiceSingleTurnUserIds','VoiceBaselineModule'):
        main_doc['Parameters'][name] = {'Type':'String','Default':'','NoEcho':True}
    for logical in ('ProcessorFunction','MediaFunction'):
        props = main_doc['Resources'][logical]['Properties']
        props['Code'] = package(s3,bucket,{'app.py':(root/'src/processor/app.py').read_bytes(),
                                          'production_baseline.py':baselines[logical]})
        props['Environment']['Variables'].update({
            'VOICE_SINGLE_TURN_PHONE_NUMBERS':{'Ref':'VoiceSingleTurnPhoneNumbers'},
            'VOICE_SINGLE_TURN_USER_IDS':{'Ref':'VoiceSingleTurnUserIds'},
            'VOICE_BASELINE_MODULE':{'Ref':'VoiceBaselineModule'}})
    policies = main_doc['Resources']['ProcessorFunctionRole']['Properties']['Policies']
    policies = [p for p in policies if p['PolicyName'] != 'VoiceTrialAgentAttachment']
    policies.append({'PolicyName':'VoiceTrialAgentAttachment','PolicyDocument':{'Version':'2012-10-17','Statement':[
        {'Effect':'Allow','Action':['s3:GetObject'],'Resource':{'Fn::Sub':'${MediaBucket.Arn}/*'}},
        {'Effect':'Allow','Action':['connect:UpdateContactAttributes'],'Resource':{'Fn::Sub':[
            'arn:${AWS::Partition}:connect:${AWS::Region}:${AWS::AccountId}:instance/${instance}/contact/*',
            {'instance':main_doc['Resources']['ProcessorFunction']['Properties']['Environment']['Variables']['CONNECT_INSTANCE_ID']}]}},
    ]}})
    main_doc['Resources']['ProcessorFunctionRole']['Properties']['Policies'] = policies
    candidate_names = {snapshot(main_doc,logical,'VoiceTrial20260914') for logical in ('ProcessorFunction','MediaFunction')}
    deploy(cf,s3,bucket,args.main_stack,main_doc,{'ProcessorFunction','MediaFunction','ProcessorFunctionRole'}|candidate_names,
           {'VoiceSingleTurnPhoneNumbers':args.phones,'VoiceSingleTurnUserIds':args.user_ids,'VoiceBaselineModule':'production_baseline'})
    chat_doc = template(cf,args.chat_stack)
    adapter_name = cf.describe_stack_resource(StackName=args.chat_stack,LogicalResourceId='ChatAdapter')['StackResourceDetail']['PhysicalResourceId']
    adapter_arn = lamb.get_function_configuration(FunctionName=adapter_name)['FunctionArn']
    code = package(s3,bucket,{'app.py':(root/'src/chat_adapter/app.py').read_bytes()})
    chat_doc['Resources']['ChatAdapter']['Properties']['CodeUri'] = f"s3://{bucket}/{code['S3Key']}"
    name = snapshot(chat_doc,'ChatAdapter','IncidentFix20260914')
    dependencies = {'AliasPolicy','ConnectChatAssociation','LexPermission'}
    deploy(cf,s3,bucket,args.chat_stack,chat_doc,{'ChatAdapter',name,'ChatAlias','ProductionContactFlow'}|dependencies,stable_dependencies=dependencies)


if __name__ == '__main__':
    main()
