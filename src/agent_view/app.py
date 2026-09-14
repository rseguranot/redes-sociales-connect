"""Read-only native Connect guide. Never logs customer content or bearer tokens."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

connect = boto3.client('connect')
table = boto3.resource('dynamodb').Table(os.environ['STATE_TABLE'])
UUID = re.compile(r'^[0-9a-f-]{36}$')
CURSOR = re.compile(r'^(MSG#[0-9]{12}#[0-9a-f]{64})\|([0-9]{1,6})$')
FIELDS = (
    ('Nombre WhatsApp', 'social_display_name'), ('Usuario', 'social_username'),
    ('Teléfono proporcionado por Meta', 'social_phone'), ('Identidad estable', 'social_user_id'),
    ('Nombre declarado', 'social_collected_name'), ('Teléfono declarado', 'social_collected_phone'),
    ('Servicio', 'social_service'), ('Tipo de documento', 'social_document_type'),
    ('Documento', 'social_document_number'), ('Factura', 'social_invoice_number'),
    ('Caso', 'social_case_number'), ('Detalle de la solicitud', 'social_request_detail'),
    ('Sucursal', 'social_incident_location'), ('Fecha del incidente', 'social_incident_date'),
    ('Área', 'social_incident_area'), ('Prioridad', 'social_request_priority'),
)


def safe_text(value):
    return re.sub(r'https?://\S+', '[enlace omitido; consulte el adjunto original]', str(value or ''))


def display_text(value):
    """Render the transport envelope as readable text without executing its data."""
    text = safe_text(value)
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(payload, dict):
        return text
    outbound = payload.get('whatsapp_outbound', payload)
    interactive = outbound.get('interactive') if isinstance(outbound, dict) else None
    if not isinstance(interactive, dict):
        return text
    parts = [str(interactive.get(k, {}).get('text', '')) for k in ('header', 'body', 'footer')]
    action = interactive.get('action') or {}
    for section in action.get('sections', []):
        parts += [str(row.get('title', '')) for row in section.get('rows', [])]
    parts += [str(b.get('reply', {}).get('title', '')) for b in action.get('buttons', [])]
    return '\n'.join(p for p in parts if p)


def stamp(value):
    return datetime.fromtimestamp(int(value), timezone(timedelta(hours=-4))).strftime('%d/%m/%Y %H:%M')


def resolve(contact_data, now):
    instance = os.environ['CONNECT_INSTANCE_ID']
    if contact_data.get('InstanceARN', '').split('/')[-1] != instance:
        raise ValueError('Invalid instance')
    contact_id = contact_data.get('ContactId', '')
    if not UUID.fullmatch(contact_id):
        raise ValueError('Invalid contact')
    current = connect.describe_contact(InstanceId=instance, ContactId=contact_id)['Contact']
    source = current.get('RelatedContactId') or current.get('InitialContactId') or contact_id
    source_contact = connect.describe_contact(InstanceId=instance, ContactId=source)['Contact']
    source = source_contact.get('InitialContactId') or source
    attrs = connect.get_contact_attributes(InstanceId=instance, InitialContactId=source)['Attributes']
    if attrs.get('social_channel', '').lower() != 'whatsapp':
        raise ValueError('Not a WhatsApp contact')
    mapping = table.get_item(Key={'pk': 'HISTORY_CONTACT#' + source, 'sk': 'MAP'},
                             ProjectionExpression='contact_id,history_scope,#expiry',
                             ExpressionAttributeNames={'#expiry': 'ttl'}, ConsistentRead=True).get('Item') or {}
    if int(mapping.get('ttl', 0)) <= now or mapping.get('contact_id') != source:
        raise ValueError('History binding unavailable')
    return attrs, mapping['history_scope']


def history_page(scope, cursor, now):
    """Bound output, not total history. A long message continues on the next page."""
    cutoff = now - 7 * 86400
    key, offset = '', 0
    if cursor:
        match = CURSOR.fullmatch(cursor)
        if not match:
            raise ValueError('Invalid history cursor')
        key, offset = match.group(1), int(match.group(2))
    condition = Key('pk').eq(scope) & Key('sk').between(f'MSG#{cutoff:012d}#', f'MSG#{now:012d}#~')
    kwargs = {'KeyConditionExpression': condition, 'Limit': 6, 'ScanIndexForward': False, 'ConsistentRead': True}
    if key:
        kwargs['ExclusiveStartKey'] = {'pk': scope, 'sk': key}
    rows = []
    if key and offset:
        item = table.get_item(Key={'pk': scope, 'sk': key}, ConsistentRead=True).get('Item')
        if item and cutoff <= int(item.get('timestamp', 0)) <= now:
            rows.append(item)
    page = table.query(**kwargs)
    rows.extend(page.get('Items', []))
    items, used, next_cursor = [], 0, ''
    for i, row in enumerate(rows):
        if not cutoff <= int(row.get('timestamp', 0)) <= now:
            continue
        text = display_text(row.get('text', ''))
        if row.get('attachments'):
            text += '\nAdjuntos: ' + ', '.join(safe_text(x) for x in row['attachments'])
        start = offset if row['sk'] == key else 0
        remainder = text[start:]
        # Leave room for contact context and the guide's inherited attributes.
        budget = 3800 - used
        if budget < 500 and items:
            next_cursor = rows[i-1]['sk'] + '|0'
            break
        chunk = remainder.encode('utf-8')[:max(1, budget - 250)].decode('utf-8', errors='ignore')
        role = {'CUSTOMER': 'Cliente', 'SYSTEM': 'Bot', 'AGENT': 'Agente'}.get(row.get('role'), 'Mensaje')
        name = safe_text(row.get('name'))[:100] if role == 'Agente' else role
        label = f'{stamp(row["timestamp"])} — {role}' + (f' ({name})' if role == 'Agente' else '')
        if start:
            label += ' — continuación'
        item = {'Label': label, 'Value': chunk or '[Adjunto]', 'Copyable': True}
        used += len(json.dumps(item, ensure_ascii=False).encode('utf-8'))
        items.append(item)
        if len(chunk) < len(remainder):
            next_cursor = row['sk'] + '|' + str(start + len(chunk))
            break
        next_cursor = row['sk'] + '|0' if i < len(rows)-1 or page.get('LastEvaluatedKey') else ''
    return items, next_cursor


def lambda_handler(event, _context):
    now = int(time.time())
    details = event.get('Details') or {}
    attrs, scope = resolve(details.get('ContactData') or {}, now)
    cursor = str((details.get('Parameters') or {}).get('cursor') or '')
    if cursor == 'LATEST':
        cursor = ''
    entries, next_cursor = history_page(scope, cursor, now)
    last = table.get_item(Key={'pk': scope, 'sk': 'LAST_AGENT'}, ConsistentRead=True).get('Item') or {}
    context = [{'Label': label, 'Value': safe_text(attrs[key])[:500], 'Copyable': True}
               for label, key in FIELDS if attrs.get(key)]
    if not attrs.get('social_phone'):
        context.insert(0, {'Label': 'Teléfono', 'Value': 'Meta no proporcionó teléfono; no se infiere del usuario.'})
    agent = safe_text(last.get('name') or attrs.get('social_last_agent_name') or 'Sin agente registrado')
    if last.get('timestamp'):
        agent += ' — ' + stamp(last['timestamp'])
    return {
        'Context': {'Items': context},
        'Summary': {'Items': [{'Label': 'Último agente que respondió', 'Value': agent},
            {'Label': 'Historial', 'Value': 'Últimos 7 días, más recientes primero. Incluye cliente, bot y agentes.'},
            {'Label': 'Datos declarados', 'Value': 'Recopilados en la conversación; validar antes de operar.'},
            {'Label': 'Paginación', 'Value': 'Hay más mensajes: pulse Anteriores.' if next_cursor else 'Fin del historial disponible.'}]},
        'History': {'Items': entries or [{'Label': 'Historial', 'Value': 'No hay mensajes disponibles en este intervalo.'}]},
        'next_cursor': next_cursor,
    }
