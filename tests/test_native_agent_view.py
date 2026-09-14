"""Native agent guide fixtures only; no live customer data."""
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = 1800000000
ID = '11111111-1111-1111-1111-111111111111'
GUIDE = '22222222-2222-2222-2222-222222222222'


def load():
    spec = importlib.util.spec_from_file_location('native_agent_view_test', ROOT/'src/agent_view/app.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {'STATE_TABLE':'test'}), patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(module)
    # Other legacy suites install SDK stubs during collection. Isolate expressions.
    module.Key = lambda _name: MagicMock()
    return module


def row(index, text='Mensaje de prueba', role='CUSTOMER'):
    return {'pk':'HISTORY#test', 'sk':f'MSG#{NOW-index:012d}#'+str(index).zfill(64),
            'timestamp':NOW-index,'text':text,'role':role,'name':'Agente de prueba','attachments':[]}


def test_page_preserves_all_long_message_characters():
    m = load()
    text = 'Información importante.\n' * 900
    entry = row(0,text)
    m.table.query.return_value = {'Items':[entry]}
    entries, cursor = m.history_page('HISTORY#test','',NOW)
    content = entries[0]['Value']
    for _ in range(30):
        if not cursor:
            break
        m.table.query.return_value = {'Items':[]}
        m.table.get_item.return_value = {'Item':entry}
        entries, cursor = m.history_page('HISTORY#test',cursor,NOW)
        content += entries[0]['Value']
    assert content == text
    assert not cursor


def test_history_contains_all_roles_and_agent_name_not_secret_links():
    m = load()
    m.table.query.return_value = {'Items':[row(0,'Hola','AGENT'),row(1,'Respuesta','SYSTEM'),row(2,'https://example.invalid/token','CUSTOMER')]}
    items, cursor = m.history_page('HISTORY#test','',NOW)
    encoded = json.dumps(items)
    assert 'Agente de prueba' in encoded and 'Bot' in encoded and 'Cliente' in encoded
    assert 'example.invalid' not in encoded
    assert not cursor


def test_scope_comes_from_server_contact_mapping_not_name_or_client_input():
    m = load()
    m.connect.describe_contact.side_effect = [{'Contact':{'RelatedContactId':ID}}, {'Contact':{'InitialContactId':ID}}]
    m.connect.get_contact_attributes.return_value = {'Attributes':{'social_channel':'whatsapp','social_display_name':'Same name'}}
    m.table.get_item.return_value = {'Item':{'contact_id':ID,'history_scope':'HISTORY#correct','ttl':NOW+1}}
    with patch.dict(os.environ,{'CONNECT_INSTANCE_ID':'instance'}):
        attrs, scope = m.resolve({'InstanceARN':'arn:instance/instance','ContactId':GUIDE,'Attributes':{'history_scope':'HISTORY#wrong'}},NOW)
    assert scope == 'HISTORY#correct'
    assert m.table.get_item.call_args.kwargs['Key']['pk'] == 'HISTORY_CONTACT#'+ID
    assert 'ProjectionExpression' in m.table.get_item.call_args.kwargs


def test_wrong_channel_or_expired_binding_fails_closed():
    m = load()
    m.connect.describe_contact.return_value = {'Contact':{'InitialContactId':ID}}
    for attrs, mapping in [({'social_channel':'voice'},{}),({'social_channel':'whatsapp'},{'contact_id':ID,'ttl':NOW-1})]:
        m.connect.get_contact_attributes.return_value = {'Attributes':attrs}
        m.table.get_item.return_value = {'Item':mapping}
        with patch.dict(os.environ,{'CONNECT_INSTANCE_ID':'instance'}), pytest.raises(ValueError):
            m.resolve({'InstanceARN':'arn:instance/instance','ContactId':ID},NOW)


def test_invalid_cursor_and_outside_retention():
    m = load()
    with pytest.raises(ValueError):
        m.history_page('HISTORY#test','arbitrary-partition',NOW)
    m.table.query.return_value = {'Items':[row(8*86400)]}
    assert m.history_page('HISTORY#test','',NOW) == ([], '')


def test_json_menu_readable_without_transport_envelope():
    m = load()
    value=json.dumps({'whatsapp_outbound':{'interactive':{'body':{'text':'Bienvenido'},'action':{'buttons':[{'reply':{'title':'Información'}}]}}}})
    assert m.display_text(value) == 'Bienvenido\nInformación'


def test_native_hook_preserves_original_flow_and_is_idempotent():
    import sys
    with patch.object(sys,'path',[str(ROOT/'scripts')]+sys.path):
        from deploy_native_agent_view import attach_guide, guide_flow, view_template
    original={'Version':'2019-10-30','StartAction':'Original','Actions':[{'Identifier':'Original','Type':'DisconnectParticipant','Parameters':{},'Transitions':{}}]}
    content={'Fn::Sub':[json.dumps(original),{'Existing':'reference'}]}
    result=attach_guide(content,'${NativeAgentGuide.ContactFlowArn}')
    flow=json.loads(result['Fn::Sub'][0])
    assert flow['Actions'][2:] == original['Actions']
    assert result['Fn::Sub'][1] == content['Fn::Sub'][1]
    assert attach_guide(result,'ignored') == result
    guide=guide_flow()
    assert not any(a['Type'] in ('TransferContactToQueue','MessageParticipant') for a in guide['Actions'])
    assert 'whatsapp' in json.dumps(flow)
    assert view_template()['Body'][-1]['Props']['Action'] == 'Refresh'
