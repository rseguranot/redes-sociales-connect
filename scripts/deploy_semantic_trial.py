"""Release chat-only semantic catalog and Meta typing to existing private trial identities."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile
import boto3
from deploy_identity_voice_trial import template, package, snapshot, deploy


def executable(lamb, cf, stack, logical):
    name = cf.describe_stack_resource(StackName=stack,LogicalResourceId=logical)['StackResourceDetail']['PhysicalResourceId']
    function = lamb.get_function(FunctionName=name)
    with urllib.request.urlopen(function['Code']['Location'],timeout=20) as response:
        blob = response.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        files = {name:archive.read(name) for name in archive.namelist()}
    return files,function['Configuration']


def snapshots_needed(lamb,cf,stack,document,logicals):
    names=set()
    fields=('CodeSha256','Environment','Handler','Runtime','Role','Timeout','MemorySize')
    for logical in logicals:
        physical=cf.describe_stack_resource(StackName=stack,LogicalResourceId=logical)['StackResourceDetail']['PhysicalResourceId']
        current=lamb.get_function_configuration(FunctionName=physical)
        matching=False
        for page in lamb.get_paginator('list_versions_by_function').paginate(FunctionName=physical):
            for version in page['Versions']:
                if version['Version']!='$LATEST' and all(version.get(k)==current.get(k) for k in fields):
                    matching=True
        if not matching:
            fingerprint = hashlib.sha256(json.dumps({k:current.get(k) for k in fields},sort_keys=True).encode()).hexdigest()[:12]
            names.add(snapshot(document,logical,'BeforeSemantic'+fingerprint))
        print(json.dumps({'resource':logical,'existing_immutable_backup':matching}),flush=True)
    return names


def main():
    parser = argparse.ArgumentParser()
    for key in ('profile','account','main-stack','chat-stack'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--phase',choices=['chat','main','both'],default='both')
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile,region_name='us-east-1')
    assert session.client('sts').get_caller_identity()['Account']==args.account
    cf,s3,lamb = (session.client(name) for name in ('cloudformation','s3','lambda'))
    root = Path(__file__).resolve().parents[1]
    main_doc = template(cf,args.main_stack)
    bucket = main_doc['Resources']['ProcessorFunction']['Properties']['Code']['S3Bucket']
    processor,configuration = executable(lamb,cf,args.main_stack,'ProcessorFunction')
    env = configuration['Environment']['Variables']
    assert env.get('VOICE_BASELINE_MODULE')=='production_baseline' and 'production_baseline.py' in processor
    users,phones = env.get('VOICE_SINGLE_TURN_USER_IDS',''),env.get('VOICE_SINGLE_TURN_PHONE_NUMBERS','')
    assert users and phones, 'Private trial identity selectors required'
    chat_doc = template(cf,args.chat_stack)
    business,business_config = executable(lamb,cf,args.chat_stack,'BusinessHook')
    expected = (root/'src/chat_business/handlers.py').read_text(encoding='utf-8')
    live = business['handlers.py'].decode('utf-8').replace('\r\n','\n')
    added = "                if session_attrs.get('chat_semantic_trial') == 'true':\n                    session_attrs['chat_catalog_options'] = json.dumps([\n                        {'name': p['name'][:160], 'price': p['price'][:60]}\n                        for p in products[offset:offset + 5]], ensure_ascii=False)\n"
    assert live in (expected, expected.replace(added,'')), 'Unreviewed business code drift'
    # Preserve immutable snapshots before any executable change.
    pre = snapshots_needed(lamb,cf,args.main_stack,main_doc,() if args.phase=='chat' else ('ProcessorFunction','MediaFunction'))
    if pre:
        deploy(cf,s3,bucket,args.main_stack,main_doc,pre)
    pre = snapshots_needed(lamb,cf,args.chat_stack,chat_doc,() if args.phase=='main' else ('ChatAdapter','BusinessHook'))
    if pre:
        deploy(cf,s3,bucket,args.chat_stack,chat_doc,pre)
    main_doc = template(cf,args.main_stack)
    for logical in (() if args.phase=='chat' else ('ProcessorFunction','MediaFunction')):
        files,_ = executable(lamb,cf,args.main_stack,logical)
        assert 'production_baseline.py' in files
        files['app.py'] = (root/'src/processor/app.py').read_bytes()
        props = main_doc['Resources'][logical]['Properties']
        props['Code'] = package(s3,bucket,files)
        props['Environment']['Variables']['WHATSAPP_TYPING_ENABLED']='true'
    if args.phase!='chat':
        deploy(cf,s3,bucket,args.main_stack,main_doc,{'ProcessorFunction','MediaFunction'})
    if args.phase=='main':
        return
    chat_doc = template(cf,args.chat_stack)
    business['handlers.py']=expected.encode('utf-8')
    code = package(s3,bucket,business)
    trial = copy.deepcopy(chat_doc['Resources']['BusinessHook'])
    trial_props = trial['Properties']
    for key in ('AutoPublishAlias','AutoPublishAliasAllProperties','AutoPublishCodeSha256','Policies','Events','FunctionName'):
        trial_props.pop(key,None)
    trial_props['Role'] = business_config['Role']
    trial_props['CodeUri']=f"s3://{bucket}/{code['S3Key']}"
    chat_doc['Resources']['SemanticBusinessTrial'] = trial
    version = snapshot(chat_doc,'SemanticBusinessTrial','Version'+hashlib.sha256(expected.encode()).hexdigest()[:12])
    props = chat_doc['Resources']['ChatAdapter']['Properties']
    code = package(s3,bucket,{'app.py':(root/'src/chat_adapter/app.py').read_bytes()})
    props['CodeUri']=f"s3://{bucket}/{code['S3Key']}"
    for name in ('ChatTrialPhones','ChatTrialUserIds'):
        chat_doc['Parameters'][name]={'Type':'String','NoEcho':True,'Default':''}
    props['Environment']['Variables'].update({'CHAT_TRIAL_BUSINESS_HOOK_ARN':{'Ref':version},
        'CHAT_SEMANTIC_MODEL_ID':'amazon.nova-micro-v1:0',
        'CHAT_TRIAL_PHONES':{'Ref':'ChatTrialPhones'},'CHAT_TRIAL_USER_IDS':{'Ref':'ChatTrialUserIds'}})
    # Use the same named business function, including its immutable qualified version.
    policy = {'Statement':[
        {'Effect':'Allow','Action':'lambda:InvokeFunction','Resource':{'Fn::Sub':'${SemanticBusinessTrial.Arn}:*'}},
        {'Effect':'Allow','Action':'bedrock:InvokeModel','Resource':'arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0'},
        {'Effect':'Allow','Action':'connect:GetContactAttributes','Resource':{'Fn::Sub':'${ConnectInstanceArn}/contact/*'}}]}
    if policy not in props['Policies']:
        props['Policies'].append(policy)
    deps={'AliasPolicy','ConnectChatAssociation','LexPermission'}
    allowed={'ChatAdapter','ChatAdapterRole','SemanticBusinessTrial',version,'ChatAlias','ProductionContactFlow'}|deps
    deploy(cf,s3,bucket,args.chat_stack,chat_doc,allowed,
        {'ChatTrialPhones':phones,'ChatTrialUserIds':users},stable_dependencies=deps)


if __name__=='__main__': main()
