"""Publish a WhatsApp-only native agent guide through reviewed change sets."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

import boto3
from deploy_identity_voice_trial import template, package

ROOT = Path(__file__).resolve().parents[1]


def view_template():
    body = []
    for key, label in [('Summary', 'WhatsApp — contexto del contacto'),
                       ('Context', 'Datos recopilados'), ('History', 'Conversación — últimos 7 días')]:
        body.append({'_id': key + 'Container', 'Type': 'Container',
            'Props': {'HideBorder': False}, 'Content': [
                {'_id': key + 'Heading', 'Type': 'Header', 'Props': {'variant': 'h2'}, 'Content': [label]},
                {'_id': key, 'Type': 'AttributeSection', 'Props': {'Items': '$.' + key + '.Items'},
                 'Content': [], 'Configuration': {'Layout': {'Columns': ['12']}}}]})
    for action, text in [('Older', 'Anteriores'), ('Refresh', 'Actualizar / más recientes')]:
        body.append({'_id': action, 'Type': 'Button', 'Props': {'Action': action}, 'Content': [text]})
    return {'Head': {'Title': 'WhatsApp - Atención e historial',
        'Configuration': {'Layout': {'Columns': [12]}}}, 'Body': body}


def action(name, kind, parameters, next_action, errors=True):
    transitions = {'NextAction': next_action}
    if errors:
        transitions['Errors'] = [{'NextAction': 'LoadError', 'ErrorType': 'NoMatchingError'}]
    return {'Identifier': name, 'Type': kind, 'Parameters': parameters, 'Transitions': transitions}


def guide_flow():
    actions = [action('NoLogging', 'UpdateFlowLoggingBehavior', {'FlowLoggingBehavior': 'Disabled'}, 'Load', False)]
    for name, cursor in [('Load', 'LATEST'), ('LoadOlder', '$.External.next_cursor')]:
        actions.append(action(name, 'InvokeLambdaFunction', {
            'LambdaFunctionARN': '${NativeAgentData.Arn}', 'InvocationTimeLimitSeconds': '8',
            'InvocationType': 'SYNCHRONOUS',
            'ResponseValidation': {'ResponseType': 'JSON'}, 'LambdaInvocationAttributes': {'cursor': cursor}}, 'Show'))
    show = action('Show', 'ShowView', {'ViewResource': {'Id': '${NativeAgentView.ViewArn}:$LATEST'},
        'InvocationTimeLimitSeconds': '3600', 'SensitiveDataConfiguration': {'HideResponseOn': ['TRANSCRIPT']},
        'ViewData': {k: '$.External.' + k for k in ('Summary', 'Context', 'History')}}, 'Load')
    show['Transitions']['Conditions'] = [
        {'NextAction': target, 'Condition': {'Operator': 'Equals', 'Operands': [name]}}
        for name, target in [('Older', 'LoadOlder'), ('Refresh', 'Load')]]
    show['Transitions']['Errors'] = [
        {'NextAction': 'EndGuide' if kind == 'TimeLimitExceeded' else 'LoadError', 'ErrorType': kind}
        for kind in ('NoMatchingError', 'NoMatchingCondition', 'TimeLimitExceeded')]
    actions.append(show)
    error = action('LoadError', 'ShowView', {'ViewResource': {'Id': '${NativeAgentView.ViewArn}:$LATEST'},
        'InvocationTimeLimitSeconds': '3600', 'SensitiveDataConfiguration': {'HideResponseOn': ['TRANSCRIPT']},
        'ViewData': {k: {'Items': [{'Label': 'Información', 'Value': value}]} for k, value in [
            ('Summary', 'No se pudo cargar el historial. La conversación sigue activa.'),
            ('Context', 'Pulse Actualizar para reintentar.'),
            ('History', 'No se muestran datos de otro contacto ni se realiza búsqueda por nombre.')]}}, 'Load')
    error['Transitions']['Conditions'] = [{'NextAction': 'Load', 'Condition': {'Operator': 'Equals', 'Operands': [x]}} for x in ('Refresh', 'Older')]
    error['Transitions']['Errors'] = [{'NextAction': 'EndGuide', 'ErrorType': x} for x in ('TimeLimitExceeded','NoMatchingCondition','NoMatchingError')]
    actions.extend([error, {'Identifier': 'EndGuide', 'Type': 'DisconnectParticipant', 'Parameters': {}, 'Transitions': {}}])
    return {'Version': '2019-10-30', 'StartAction': 'NoLogging', 'Metadata': {
        'entryPointPosition': {'x': 10, 'y': 10},
        'ActionMetadata': {a['Identifier']: {'position': {'x': (i % 3)*320, 'y': (i//3)*240}} for i,a in enumerate(actions)}}, 'Actions': actions}


def attach_guide(content, arn):
    """Prepend a channel guard; leave every existing action and transition intact."""
    wrapper = copy.deepcopy(content)
    data = wrapper.get('Fn::Sub') if isinstance(wrapper, dict) else wrapper
    text = data[0] if isinstance(data, list) else data
    flow = json.loads(text)
    if any(a['Identifier'] == 'NativeAgentChannel' for a in flow['Actions']):
        return wrapper
    start = flow['StartAction']
    hook = action('NativeAgentUI', 'UpdateContactEventHooks', {'EventHooks': {'DefaultAgentUI': arn}}, start)
    hook['Transitions']['Errors'][0]['NextAction'] = start
    guard = action('NativeAgentChannel', 'Compare', {'ComparisonValue': '$.Attributes.social_channel'}, start)
    guard['Transitions']['Conditions'] = [{'NextAction': 'NativeAgentUI', 'Condition': {'Operator': 'Equals', 'Operands': ['whatsapp']}}]
    guard['Transitions']['Errors'] = [{'NextAction': start, 'ErrorType': 'NoMatchingCondition'}]
    flow['Actions'] = [guard, hook] + flow['Actions']
    flow['StartAction'] = 'NativeAgentChannel'
    flow.setdefault('Metadata', {}).setdefault('ActionMetadata', {}).update({
        'NativeAgentChannel': {'position': {'x': -600, 'y': 0}}, 'NativeAgentUI': {'position': {'x': -300, 'y': 0}}})
    encoded = json.dumps(flow, ensure_ascii=True)
    if isinstance(wrapper, dict):
        wrapper['Fn::Sub'] = [encoded, data[1]] if isinstance(data, list) else encoded
        return wrapper
    return encoded


def add_resources(document, code, state_table):
    doc = copy.deepcopy(document)
    doc.setdefault('Parameters', {})['NativeAgentStateTable'] = {'Type': 'String', 'AllowedPattern': '[A-Za-z0-9_.-]{3,255}'}
    doc['Parameters']['NativeAgentStateKeyArn'] = {'Type': 'String', 'AllowedPattern': '^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/.+$'}
    sub = lambda value: {'Fn::Sub': value}
    ref = lambda value: {'Ref': value}
    get = lambda name, field: {'Fn::GetAtt': [name, field]}
    resources = {
        'NativeAgentView': {'Type': 'AWS::Connect::View', 'Properties': {
            'InstanceArn': ref('ConnectInstanceArn'), 'Name': sub('${AWS::StackName} - WhatsApp Agentes'),
            'Actions': ['Older', 'Refresh'], 'Template': view_template()}},
        'NativeAgentRole': {'Type': 'AWS::IAM::Role', 'Properties': {
            'AssumeRolePolicyDocument': {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
                'Principal': {'Service': 'lambda.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]},
            'Policies': [{'PolicyName': 'NativeGuideReadOnly', 'PolicyDocument': {'Version': '2012-10-17', 'Statement': [
                {'Effect': 'Allow', 'Action': ['connect:DescribeContact','connect:GetContactAttributes'],
                 'Resource': sub('${ConnectInstanceArn}/contact/*')},
                {'Effect': 'Allow', 'Action': ['dynamodb:GetItem','dynamodb:Query'],
                 'Resource': sub('arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${NativeAgentStateTable}'),
                 'Condition': {'ForAllValues:StringLike': {'dynamodb:LeadingKeys': ['HISTORY#*','HISTORY_CONTACT#*']}}},
                {'Effect': 'Allow', 'Action': ['kms:Decrypt'], 'Resource': ref('NativeAgentStateKeyArn'),
                 'Condition': {'StringEquals': {'kms:ViaService': sub('dynamodb.${AWS::Region}.amazonaws.com')}}},
                {'Effect': 'Allow', 'Action': ['logs:CreateLogStream','logs:PutLogEvents'],
                 'Resource': sub('arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/${AWS::StackName}-native-agent-view-logs:*')}
            ]}}]}},
        'NativeAgentData': {'Type': 'AWS::Lambda::Function', 'DependsOn': 'NativeAgentLogs', 'Properties': {
            'FunctionName': sub('${AWS::StackName}-native-agent-view'), 'Runtime': 'python3.14', 'Handler': 'app.lambda_handler',
            'Role': get('NativeAgentRole','Arn'), 'Code': code, 'Timeout': 8, 'MemorySize': 256,
            'LoggingConfig': {'LogGroup': ref('NativeAgentLogs')},
            'Environment': {'Variables': {'STATE_TABLE': ref('NativeAgentStateTable'),
                'CONNECT_INSTANCE_ID': {'Fn::Select': [1, {'Fn::Split': ['/', ref('ConnectInstanceArn')]}]}}}}},
        'NativeAgentLogs': {'Type': 'AWS::Logs::LogGroup', 'DeletionPolicy': 'RetainExceptOnCreate', 'UpdateReplacePolicy': 'Retain',
            'Properties': {'LogGroupName': sub('/aws/lambda/${AWS::StackName}-native-agent-view-logs'), 'RetentionInDays': 7}},
        'NativeAgentPermission': {'Type': 'AWS::Lambda::Permission', 'Properties': {
            'FunctionName': ref('NativeAgentData'), 'Action': 'lambda:InvokeFunction', 'Principal': 'connect.amazonaws.com',
            'SourceAccount': ref('AWS::AccountId'), 'SourceArn': ref('ConnectInstanceArn')}},
        'NativeAgentAssociation': {'Type': 'AWS::Connect::IntegrationAssociation', 'Properties': {
            'InstanceId': ref('ConnectInstanceArn'), 'IntegrationArn': get('NativeAgentData','Arn'), 'IntegrationType': 'LAMBDA_FUNCTION'}},
        'NativeAgentGuide': {'Type': 'AWS::Connect::ContactFlow', 'DependsOn': ['NativeAgentPermission','NativeAgentAssociation'], 'Properties': {
            'InstanceArn': ref('ConnectInstanceArn'), 'Name': sub('${AWS::StackName} - WhatsApp Vista Agente'),
            'Type': 'CONTACT_FLOW', 'State': 'ACTIVE', 'Content': sub(json.dumps(guide_flow()))}},
    }
    doc['Resources'].update(resources)
    props = doc['Resources']['ProductionContactFlow']['Properties']
    props['Content'] = attach_guide(props['Content'], '${NativeAgentGuide.ContactFlowArn}')
    doc.setdefault('Outputs', {}).update({
        'NativeAgentViewId': {'Value': get('NativeAgentView','ViewId'), 'Description': 'Native WhatsApp agent view'},
        'NativeAgentGuideArn': {'Value': get('NativeAgentGuide','ContactFlowArn'), 'Description': 'Native WhatsApp agent guide'},
    })
    return doc, set(resources) | {'ProductionContactFlow'}


def release(cf, stack, doc, allowed, parameters, s3=None, bucket=None):
    name = 'native-agent-view-' + str(int(time.time()))
    encoded = json.dumps(doc)
    source = {'TemplateBody': encoded}
    if len(encoded.encode()) >= 51200:
        assert s3 and bucket, 'Template upload required'
        key = 'native-agent-view/' + hashlib.sha256(encoded.encode()).hexdigest() + '.json'
        s3.put_object(Bucket=bucket,Key=key,Body=encoded.encode(),ContentType='application/json')
        source = {'TemplateURL': f'https://{bucket}.s3.us-east-1.amazonaws.com/{key}'}
    changes = cf.create_change_set(StackName=stack, ChangeSetName=name, ChangeSetType='UPDATE',
        **source, Parameters=parameters, Capabilities=['CAPABILITY_NAMED_IAM','CAPABILITY_AUTO_EXPAND'])
    while True:
        plan = cf.describe_change_set(ChangeSetName=changes['Id'])
        if plan['Status'] in ('CREATE_COMPLETE','FAILED'):
            break
        time.sleep(4)
    if plan['Status'] != 'CREATE_COMPLETE':
        if "didn't contain changes" in plan.get('StatusReason','') or 'No updates are to be performed' in plan.get('StatusReason',''):
            print(stack + ' unchanged', flush=True)
            return
        raise RuntimeError(plan.get('StatusReason','Change set failed'))
    failures = [e for p in cf.get_paginator('describe_events').paginate(ChangeSetName=changes['Id'])
                for e in p.get('OperationEvents', []) if e.get('EventType') == 'VALIDATION_ERROR']
    print(json.dumps({'validation_errors': len(failures)}), flush=True)
    assert not failures, 'CloudFormation validation requires review'
    entries = [x['ResourceChange'] for x in plan.get('Changes', [])]
    print(json.dumps({'reviewed_changes': [{k:e.get(k) for k in ('LogicalResourceId','Action','Replacement')} for e in entries]}),flush=True)
    original = template(cf,stack)
    def stable_native_dependency(entry):
        return (entry['LogicalResourceId'] == 'NativeAgentAssociation'
            and entry.get('Replacement') == 'Conditional'
            and original['Resources'].get('NativeAgentAssociation') == doc['Resources']['NativeAgentAssociation']
            and original['Resources']['NativeAgentData']['Properties']['FunctionName'] == doc['Resources']['NativeAgentData']['Properties']['FunctionName']
            and bool(entry.get('Details'))
            and all(d.get('Evaluation') == 'Dynamic' and d.get('ChangeSource') == 'ResourceAttribute'
                    and d.get('CausingEntity') == 'NativeAgentData.Arn' for d in entry['Details']))
    def stable_processor_dependency(entry):
        return (entry['LogicalResourceId'] == 'ProcessorFunction' and entry.get('Replacement') == 'False'
            and original['Resources'].get('ProcessorFunction') == doc['Resources'].get('ProcessorFunction')
            and bool(entry.get('Details'))
            and all(d.get('Evaluation') == 'Dynamic' and d.get('ChangeSource') == 'ResourceAttribute'
                    and d.get('CausingEntity') == 'DefaultConnectContactFlow.ContactFlowArn' for d in entry['Details']))
    assert all((e['LogicalResourceId'] in allowed or stable_processor_dependency(e)) and e['Action'] in ('Add','Modify')
               and (e.get('Replacement','False') == 'False' or stable_native_dependency(e)) for e in entries), 'Unrelated change or replacement rejected'
    previous_ids = {k:cf.describe_stack_resource(StackName=stack,LogicalResourceId=k)['StackResourceDetail']['PhysicalResourceId']
                    for k in ('NativeAgentData','NativeAgentAssociation','ProcessorFunction','DefaultConnectContactFlow') if k in original['Resources']}
    cf.execute_change_set(ChangeSetName=changes['Id'])
    while True:
        status = cf.describe_stacks(StackName=stack)['Stacks'][0]['StackStatus']
        if status == 'UPDATE_COMPLETE':
            assert all(cf.describe_stack_resource(StackName=stack,LogicalResourceId=k)['StackResourceDetail']['PhysicalResourceId'] == v for k,v in previous_ids.items()), 'Native dependency identity changed'
            print(stack + ' UPDATE_COMPLETE', flush=True)
            return
        if status not in ('UPDATE_IN_PROGRESS','UPDATE_COMPLETE_CLEANUP_IN_PROGRESS'):
            raise RuntimeError('Stack update did not complete: ' + status)
        time.sleep(5)


def main():
    import cfnlint.api
    parser = argparse.ArgumentParser()
    for key in ('profile','account','main-stack','chat-stack'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--include-direct-route', action='store_true')
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name='us-east-1')
    assert session.client('sts').get_caller_identity()['Account'] == args.account
    cf, s3 = session.client('cloudformation'), session.client('s3')
    original = template(cf, args.chat_stack)
    main_doc = template(cf, args.main_stack)
    bucket = main_doc['Resources']['ProcessorFunction']['Properties']['Code']['S3Bucket']
    table_name = cf.describe_stack_resource(StackName=args.main_stack, LogicalResourceId='StateTable')['StackResourceDetail']['PhysicalResourceId']
    table_key = session.client('dynamodb').describe_table(TableName=table_name)['Table']['SSEDescription']['KMSMasterKeyArn']
    source = (ROOT/'src/agent_view/app.py').read_bytes()
    previous_code = original['Resources'].get('NativeAgentData', {}).get('Properties', {}).get('Code')
    code = None
    if previous_code:
        with s3.get_object(Bucket=previous_code['S3Bucket'],Key=previous_code['S3Key'])['Body'] as body:
            with zipfile.ZipFile(io.BytesIO(body.read())) as archive:
                if archive.read('app.py') == source:
                    code = previous_code
    if code is None:
        code = package(s3,bucket,{'app.py':source}) if args.execute else {'S3Bucket': bucket,'S3Key':'validation-only.zip'}
    doc, allowed = add_resources(original, code, table_name)
    findings = cfnlint.api.lint(json.dumps(doc), regions=['us-east-1'])
    print(json.dumps({'lint': [{'rule':f.rule.id,'message':f.message} for f in findings]}), flush=True)
    assert not any(f.rule.id.startswith('E') for f in findings)
    if not args.execute:
        return
    parameters = [{'ParameterKey':p['ParameterKey'],'UsePreviousValue':True} for p in cf.describe_stacks(StackName=args.chat_stack)['Stacks'][0].get('Parameters', []) if p['ParameterKey'] not in ('NativeAgentStateTable','NativeAgentStateKeyArn')]
    parameters.extend([{'ParameterKey':'NativeAgentStateTable','ParameterValue':table_name},
                       {'ParameterKey':'NativeAgentStateKeyArn','ParameterValue':table_key}])
    release(cf,args.chat_stack,doc,allowed,parameters)
    if args.include_direct_route:
        outputs={x['OutputKey']:x['OutputValue'] for x in cf.describe_stacks(StackName=args.chat_stack)['Stacks'][0]['Outputs']}
        direct=template(cf,args.main_stack)
        direct['Parameters']['NativeAgentGuideArn']={'Type':'String','AllowedPattern':'^arn:aws:connect:[a-z0-9-]+:[0-9]{12}:instance/.*/contact-flow/.*$'}
        props=direct['Resources']['DefaultConnectContactFlow']['Properties']
        content=attach_guide(props['Content'],'${NativeAgentGuideArn}')
        props['Content']=content if isinstance(content,dict) else {'Fn::Sub':content}
        findings=cfnlint.api.lint(json.dumps(direct),regions=['us-east-1'])
        print(json.dumps({'direct_lint': [f.rule.id for f in findings]}),flush=True)
        assert not any(f.rule.id.startswith('E') for f in findings)
        parameters=[{'ParameterKey':p['ParameterKey'],'UsePreviousValue':True} for p in cf.describe_stacks(StackName=args.main_stack)['Stacks'][0]['Parameters'] if p['ParameterKey']!='NativeAgentGuideArn']
        parameters.append({'ParameterKey':'NativeAgentGuideArn','ParameterValue':outputs['NativeAgentGuideArn']})
        processor_name=cf.describe_stack_resource(StackName=args.main_stack,LogicalResourceId='ProcessorFunction')['StackResourceDetail']['PhysicalResourceId']
        lamb=session.client('lambda')
        before=lamb.get_function_configuration(FunctionName=processor_name)
        release(cf,args.main_stack,direct,{'DefaultConnectContactFlow'},parameters,s3,bucket)
        after=lamb.get_function_configuration(FunctionName=processor_name)
        assert all(before[k] == after[k] for k in ('CodeSha256','Environment','Role','Runtime','Handler')), 'Processor runtime changed'
        print('Processor code and effective configuration unchanged',flush=True)


if __name__ == '__main__':
    main()
