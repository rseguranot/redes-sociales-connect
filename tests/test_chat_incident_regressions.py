"""Anonymized regression phrases: no customer records or provider identities."""
import copy
import json
from unittest.mock import patch
from test_chat_adapter import adapter, turn


def test_specific_spoken_request_keeps_brand_and_size_without_model_guess():
    event = turn('Quisiera saber el precio de un televisor de 65 pulgadas de LG.', {})
    with patch.object(adapter.semantic_client, 'converse') as model:
        assert adapter.semantic_product(event) is None
    model.assert_not_called()
    assert event['inputTranscript'] == 'precio televisores LG 65 pulgadas'
    assert event['_semantic_product'] is True


def test_shorter_spoken_followup_keeps_explicit_size():
    event = turn('Quisiera televisores LG.', {'chat_semantic_product':'televisor',
        'chat_semantic_brand':'LG', 'chat_semantic_features':'65 pulgadas'})
    adapter.semantic_product(event)
    assert '65 pulgadas' in event['inputTranscript']


def test_spoken_selection_returns_the_existing_record_not_a_new_search():
    records = [{'name':f'TV TEST {i}', 'price':f'RD$ {i}'} for i in range(1,5)]
    for phrase in ['Háblame del televisor número 3 es un LG LED 4K.',
                   'Me interesa la opción tres', 'el tercero', 'Ver producto 3']:
        event = turn(phrase, {'chat_catalog_options':json.dumps(records)})
        with patch.object(adapter.semantic_client, 'converse') as model:
            result = adapter.semantic_product(event)
        assert 'TV TEST 3' in result['messages'][0]['content']
        model.assert_not_called()
    assert adapter.select_catalog_option('No quiero el producto 3', records) is None
    assert adapter.select_catalog_option('El número 9', records) is None


def test_options_reuse_exact_cached_records():
    event = turn('Ver opciones', {'chat_catalog_options':json.dumps([{'name':'TV TEST','price':'RD$ 10'}])})
    with patch.object(adapter.semantic_client,'converse') as model:
        result = adapter.semantic_product(event)
    assert '[opcion] Ver producto 1' in result['messages'][0]['content']
    assert 'TV TEST' in result['messages'][0]['content']
    model.assert_not_called()


def test_delivery_and_failure_are_not_catalog_intents():
    cases = {'Tengo inconveniente con la nevera':'reclamaciones',
             'Mi refrigerador no enfria':'reclamaciones',
             'Ya compramos una lavadora y queremos saber cuando nos la van a traer':'consulta',
             'Quiero saber cuando me van a traer la lavadora':'consulta'}
    for phrase, topic in cases.items():
        event = adapter.prepare(turn(phrase, {'chat_semantic_product':'televisor'}))
        assert event['sessionState']['sessionAttributes']['bedrock_active_intent'] == topic
        with patch.object(adapter.semantic_client, 'converse') as model:
            assert adapter.semantic_product(event) is None
        model.assert_not_called()


def test_spare_parts_and_services_do_not_become_equipment_or_invoice_queries():
    for phrase in ['Sensor de temperatura para aire acondicionado',
                   'Tienes los resortes de la lavadora tipo torre', 'Comunícame con repuestos',
                   'Forran libros']:
        event = turn(phrase, {'bedrock_active_intent':'consulta', 'consulta_factura':'test'})
        with patch.object(adapter.semantic_client,'converse') as model:
            result = adapter.semantic_product(event)
        assert 'Hablar con un agente' in result['messages'][0]['content']
        assert 'consulta_factura' not in result['sessionState']['sessionAttributes']
        model.assert_not_called()


def test_agent_and_close_work_without_legacy_contact_binding():
    env = {'CHAT_DIALOGUE_SAFETY_ENABLED':'true'}
    for phrase in ['Necesito hablar con el servicio al cliente','Puedo hablar con una persona',
                   'Comunícame con un representante','Hablar con un agente']:
        with patch.dict(adapter.os.environ,env), patch.object(adapter,'semantic_trial',return_value=False), patch.object(adapter,'persist_context',side_effect=lambda r,e:r), patch.object(adapter.client,'invoke') as hook:
            result = adapter.lambda_handler(turn(phrase, {'nombre_cliente':'QA fixture'}),None)
        assert result['sessionState']['dialogAction']['type']=='Close'
        assert result['sessionState']['sessionAttributes']['agente']=='true'
        assert result['sessionState']['sessionAttributes']['nombre_cliente']=='QA fixture'
        hook.assert_not_called()
    for phrase in ['No quiero hablar con un agente','No necesito un representante']:
        assert not adapter.agent_requested(phrase)
    with patch.dict(adapter.os.environ,env), patch.object(adapter,'semantic_trial',return_value=False), patch.object(adapter,'persist_context',side_effect=lambda r,e:r):
        result = adapter.lambda_handler(turn('finalizar',{}),None)
    assert result['sessionState']['sessionAttributes']['agente']=='false'
    assert result['sessionState']['dialogAction']['type']=='Close'


def test_internal_prose_is_never_presented_as_a_customer_answer():
    for text in ['The response indicates customerIdentified false again. We must transfer.',
                 '<thinking>look up the client</thinking>', 'We need to output the transfer marker exactly']:
        result = adapter.safe_dialogue_response(adapter.chat_reply(turn('consulta',{}),text),turn('consulta',{}))
        assert result['sessionState']['sessionAttributes']['agente']=='true'
        assert text not in result['messages'][0]['content']


def test_two_failed_identifications_handoff_with_context():
    event = turn('documento de prueba', {'chat_identification_failures':'1','social_reply_override':'text'})
    result = adapter.safe_dialogue_response(adapter.chat_reply(event,'No encontré información con ese número de factura. ¿Puedes revisarlo?'),event)
    assert result['sessionState']['sessionAttributes']['agente']=='true'
    assert result['sessionState']['sessionAttributes']['social_reply_override']=='text'
    assert 'dos intentos' in result['messages'][0]['content']


def test_unrequested_empty_close_becomes_a_live_dialogue():
    event=turn('Una pregunta',{})
    response={'sessionState':{'dialogAction':{'type':'Close'},'sessionAttributes':{'agente':'false'}},'messages':[]}
    result=adapter.safe_dialogue_response(response,event)
    assert result['sessionState']['dialogAction']['type']=='ElicitIntent'
    assert result['messages']


def test_catalog_excludes_accessories_for_equipment_search():
    event=turn('Laptop',{'chat_semantic_product':'laptop'});event['_semantic_product']=True
    response={'sessionState':{'sessionAttributes':{'chat_catalog_options':json.dumps([
        {'name':'CANDADO PARA LAPTOP','price':'RD$ 5'}, {'name':'LAPTOP TEST','price':'RD$ 50'}])}}}
    result=adapter.adapt(response,event)
    assert 'CANDADO' not in result['messages'][0]['content']
    assert 'LAPTOP TEST' in result['messages'][0]['content']


def test_multiple_products_ask_which_one_instead_of_ignoring_half_the_request():
    event=turn('Quiero una cotización de laptop e impresora',{})
    with patch.object(adapter.semantic_client,'converse') as model:
        result=adapter.semantic_product(event)
    assert '[opcion] Laptop' in result['messages'][0]['content']
    assert '[opcion] Impresora' in result['messages'][0]['content']
    model.assert_not_called()


def test_nonconversational_markers_do_not_reach_business_hook():
    for text in ['[Mensaje de tipo unsupported]','Imagen enviada por el cliente','Audio enviado por el cliente']:
        with patch.dict(adapter.os.environ,{'CHAT_DIALOGUE_SAFETY_ENABLED':'true'}), patch.object(adapter,'semantic_trial',return_value=False), patch.object(adapter,'persist_context',side_effect=lambda r,e:r), patch.object(adapter.client,'invoke') as hook:
            result=adapter.lambda_handler(turn(text,{}),None)
        assert not result.get('messages')
        hook.assert_not_called()
