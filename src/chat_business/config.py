"""Constantes, patrones y clientes boto3 compartidos por todos los módulos."""
import os
import re
import boto3
from botocore.config import Config
_nova_cfg = Config(read_timeout=10, connect_timeout=5, retries={'max_attempts': 2})
_intent_cfg = Config(read_timeout=25, connect_timeout=5, retries={'max_attempts': 1})
_qconnect_cfg = Config(read_timeout=6, connect_timeout=3, retries={'max_attempts': 1})
_region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
bedrock_runtime = boto3.client('bedrock-runtime', config=_nova_cfg, region_name=_region)
bedrock_intent_runtime = boto3.client('bedrock-agent-runtime', config=_intent_cfg, region_name=_region)
qconnect_client = boto3.client('qconnect', config=_qconnect_cfg, region_name=_region)
QCONNECT_ASSISTANT_ID = os.environ['QCONNECT_ASSISTANT_ID']
QCONNECT_ASSOCIATION_ID = os.environ['QCONNECT_ASSOCIATION_ID']
INTENT_GENERA = 'Genera'
INTENT_AMAZON_Q = os.environ.get('AMAZON_Q_INTENT_NAME', 'AmazonQinConnect')
INTENT_CERRAR = 'Cerrar'
SEARCH_RESPONSE_KEY = 'x-amz-lex:bedrock-agent-search-response'
ACTION_INPUT_KEY = 'x-amz-lex:bedrock-agent-action-group-invocation-input'
Q_RESPONSE_KEY = 'x-amz-lex:q-in-connect-response'
BEDROCK_SESSION_PREFIX = os.environ.get('BEDROCK_SESSION_PREFIX', 'plazalama')
NOVA_MICRO_MODEL = 'amazon.nova-micro-v1:0'
INTENT_AGENT_MAP = {'quejas': (os.environ['BEDROCK_QUEJAS_AGENT_ID'], os.environ['BEDROCK_QUEJAS_AGENT_ALIAS_ID']), 'reclamaciones': (os.environ['BEDROCK_RECLAMACIONES_AGENT_ID'], os.environ['BEDROCK_RECLAMACIONES_AGENT_ALIAS_ID']), 'consulta': (os.environ['BEDROCK_CONSULTA_AGENT_ID'], os.environ['BEDROCK_CONSULTA_AGENT_ALIAS_ID'])}
LEX_INTENT_ROUTING = frozenset(INTENT_AGENT_MAP)
ROUTE_AMAZON_Q = 'amazon_q'
ROUTE_BEDROCK_SUPERVISOR = 'bedrock_supervisor'
ROUTE_AGENT_TRANSFER = 'agent_transfer'
ROUTE_CLOSED = 'closed'
ROUTE_ATTR = 'routing_mode'
BEDROCK_SESSION_ATTR = 'bedrock_supervisor_session_id'
TRANSFER_TAG_REGEX = re.compile('\\[TRANSFER\\s*:\\s*(\\w+)\\s*\\]', re.IGNORECASE)
CLOSE_TAG_REGEX = re.compile('\\[CLOSE\\]', re.IGNORECASE)
CASE_REGEX = re.compile('\\b\\d{7,8}\\b')
GENERIC_NUMBER_REGEX = re.compile('\\b[A-Za-z0-9]{6,20}\\b')
DIGITS_REGEX = re.compile('\\b\\d{6,20}\\b')
PRODUCT_CLARIFICATION_QUESTIONS = ['La queja tiene que ver con un producto', 'La reclamación tiene que ver con un producto', 'tiene que ver con un producto comprado', 'La situación tiene que ver con un producto']
AUTOGESTION_COMPLETADA_PATTERNS = ['\\bhemos registrado\\b', '\\bfue registrad\\b', '\\bcaso registrad\\b', '\\bqueja registrad\\b', '\\breclamacion registrad\\b', '\\bcanalizar\\b', '\\bcanalizaremos\\b', '\\bgestionaremos\\b', '\\bcaso esta cerrado\\b', '\\bel taller asignado\\b', '\\bla resolucion es\\b', '\\bultimo comentario\\b', '\\bcorreo enviado\\b', '\\btu caso sera atendido\\b', '\\bser(a|a) gestionado\\b', '\\bcaso (abierto|creado|generado)\\b']
USER_CLOSE_PATTERNS = ['\\b(adios|adiÃ³s|hasta luego|hasta pronto|chao|chau|bye|hasta manana|hasta mañana)\\b', '\\b(no gracias|no necesito|no quiero|no deseo|no requiero)\\s+(nada|ayuda|mas|más)\\b', '\\beso es todo\\b', '\\bya no necesito\\b', '\\bgracias\\s+(y\\s+)?(adios|adiÃ³s|hasta luego|chao)\\b']
NEGATIVE_AFTER_HELP_PATTERNS = ['^no$', '^no\\b.*', '\\bno (gracias|necesito|quiero|deseo)\\b', '\\beso es todo\\b', '\\bya estoy\\b', '\\bno hay nada mas\\b', '\\bno hay nada más\\b']
HELP_QUESTION_HINTS = ['puedo ayudarte con algo mas', 'puedo ayudarte con algo más', 'hay algo mas en que pueda ayudarte', 'hay algo más en que pueda ayudarte', 'en que mas puedo ayudarte', 'en qué más puedo ayudarte', 'puedo ayudarte en algo mas', 'puedo ayudarte en algo más', 'necesitas algo mas', 'necesitas algo más', 'tienes alguna otra consulta', 'alguna otra pregunta', 'te puedo ayudar con algo mas', 'te puedo ayudar con algo más', 'quieres otra opcion', 'quieres otra opción', 'quieres que busque otra opcion', 'quieres que busque otra opción', 'deseas consultar otra cosa', 'necesitas mas informacion', 'necesitas más información']
AGENT_REQUEST_PATTERNS = ['\\b(quiero|necesito|deseo|quisiera)\\s+(hablar|comunicarme|hablar|contactar)\\s+(con\\s+)?(un\\s+)?(agente|representante|asesor|persona|humano|ejecutivo|alguien)\\b', '\\b(pasame|pásame|comunícame|comunicame|transfiereme|transfíéreme)\\s+(con\\s+)?(un\\s+)?(agente|representante|asesor|persona|humano)\\b', '\\b(pasame|comunicame|transfiereme)\\s+con\\s+(la\\s+)?gente\\b', '\\bagente\\s+(humano|real|en\\s+vivo|de\\s+verdad)\\b', '\\b(hablar|comunicarme)\\s+con\\s+(un\\s+)?(agente|representante|persona|alguien)\\b', '\\b(necesito|quiero)\\s+(un\\s+)?(agente|representante|asesor)\\b', '\\bhablar\\s+con\\s+(una\\s+)?(persona|alguien)\\b', '\\b(quiero|necesito|quisiera)\\s+hablar\\s+con\\s+alguien\\b']
OTROS_MENU_PATTERNS = ['^otr[oa]s?$', '^otr[oa]s?\\s+(opciones?|temas?|cosas?|consultas?)$', '^(ver|quiero|quisiera)\\s+(ver\\s+)?otr[oa]s?\\s+(opciones?|temas?|cosas?)$', '^quiero\\s+otr[oa]\\s+(cosa|opcion|tema)$']
AGENT_HANDOFF_PATTERNS = ['\\btransferirte\\b', '\\btransfiero\\b', '\\bcomunicarte con un representante\\b', '\\bcomunicaremos con un representante\\b', '\\bcomunicarte con un agente\\b', '\\bcomunicaremos con un agente\\b', '\\bte estare comunicando\\b', '\\bte estaré comunicando\\b', '\\ble estare comunicando\\b', '\\ble estaré comunicando\\b', '\\bte comunico con un\\b', '\\ble comunico con un\\b', '\\btransfer(ir|endo)\\b']
AGENT_CLOSE_PATTERNS = ['\\bque tengas?(?: un)? buen dia[.!]?\\s*$']
COMPLAINT_FIELD_NAMES = {'nombre_cliente', 'telefono_cliente', 'detalle_queja', 'lugar_queja', 'fecha_incidente', 'area_involucrada', 'persona_involucrada', 'nivel_criticidad', 'nivel_queja', 'servicio'}
CLAIM_PATTERNS = ['\\b(tengo|quiero|necesito)\\s+(una?\\s+)?(reclamacion|reclamaciÃ³n|reclamo)\\b', '\\breclamar\\b', '\\bdevoluci(o|Ã³)n\\b', '\\bgarant(i|Ã\xad)a\\b', '\\bproducto\\s+(daÃ±ado|danado|defectuoso|roto|averiado|rayado|abollado)\\b', '\\b(daÃ±ado|danado|defectuoso|averiado|roto|rayado|abollado)\\b.*\\bproducto\\b', '\\bno\\s+funciona(ba)?\\b', '\\bproducto\\s+incompleto\\b', '\\bfaltaban?\\s+(piezas|partes|accesorios|componentes)\\b', '\\bno\\s+llegÃ³?\\b', '\\bentr(e|Ã©)ga\\s+incompleta\\b', '\\bproblema\\s+con\\s+(mi\\s+)?(compra|pedido|producto|orden)\\b', '\\bno\\s+recibi(Ã³|o)?\\b', '\\bno\\s+me\\s+llegÃ³?\\b', '\\bnumero\\s+de\\s+(caso|reclamacion)\\b', '\\bnÃºmero\\s+de\\s+(caso|reclamaciÃ³n)\\b', '\\bmi\\s+(caso|reclamacion)\\b', '\\bconsultar\\s+una?\\s+(reclamacion|reclamaciÃ³n)\\b']
COMPLAINT_PATTERNS = ['\\b(tengo|quiero|necesito)\\s+(una?\\s+)?queja\\b', '\\bponer\\s+(una?\\s+)?queja\\b', '\\bregistrar\\s+(una?\\s+)?queja\\b', '\\bhacer\\s+(una?\\s+)?queja\\b', '\\bmal\\s+trato\\b', '\\bmaltrato\\b', '\\bme\\s+(trataron|trató)\\s+mal\\b', '\\bme\\s+faltaron\\s+el\\s+respeto\\b', '\\bme\\s+insultaron\\b', '\\bme\\s+agredieron\\b', '\\bempleado\\s+(grosero|descortés|maleducado|irrespetuoso)\\b', '\\bpersonal\\s+(grosero|descortés|maleducado|irrespetuoso)\\b', '\\b(gerente|supervisor|empleado|cajero|cajera|guardia|seguridad)\\s+(me|fue|estuvo)\\b', '\\bincidente\\s+(en|con)\\s+(el|la|un|una)\\s+(tienda|sucursal|empleado|personal)\\b', '\\bsituacion\\s+(que|con)\\s+(el|la|un|una)\\s+(empleado|personal|gerente)\\b', '\\bqueja\\s+(formal|oficial)\\b', '\\bme\\s+(golpearon|amenazaron|empujaron|acosaron)\\b', '\\btuve\\s+un\\s+accidente\\b', '\\bme\\s+cai\\b', '\\bme\\s+lesione\\b', '\\bdenunciar\\b', '\\bdenuncia\\b', '\\bdemanda\\b', '\\bproconsumidor\\b']
STATUS_PATTERNS = ['\\b(estado|estatus|seguimiento)\\s+de\\s+(mi\\s+)?(pedido|entrega|compra|orden|factura)\\b', '\\b(donde\\s+est(a|á)|cuando\\s+llega|cuando\\s+llegar(a|á))\\s+(mi\\s+)?(pedido|entrega|compra|orden)\\b', '\\bmi\\s+pedido\\s+(no|sigue|aun|aún)\\b', '\\b(cuando|cuándo)\\s+me\\s+(entregan|llega|llegar(a|á))\\b', '\\bno\\s+me\\s+ha(n)?\\s+llegado\\b', '\\bseguimiento\\s+de\\s+(mi\\s+)?pedido\\b']
GENERAL_PATTERNS = ['^(hola|buenos\\s+(dias|días|tardes|noches)|buen\\s+dia|buen\\s+día|saludos)\\b', '^(buenas)\\b', '\\binformaci(o|ó)n\\s+(general|de\\s+la\\s+tienda)\\b', '\\bprecios?\\b', '\\bcatalogo\\b', '\\bcatálogo\\b', '\\btienen\\b.*\\b(producto|televisor|electrodomestico|celular|computadora)\\b', '\\bvenden\\b', '\\bdisponibilidad\\b', '\\bhorario\\b', '\\bhorarios\\b', '\\bhora\\s+de\\s+(apertura|cierre|atencion|atención)\\b', '\\bque\\s+(dia|día|dias|días)\\s+(abren|cierran|atienden)\\b', '\\bestán\\s+abiertos\\b', '\\bestan\\s+abiertos\\b']
BRANCH_ALIASES = {'Plaza Lama Nicolas de Ovando': ['\\bovando\\b', '\\bnicolas\\s+de\\s+ovando\\b', '\\bcolonia\\s+ovando\\b'], 'Plaza Lama Churchill': ['\\bchurchill\\b'], 'Plaza Lama Duarte': ['\\bduarte\\b'], 'Plaza Lama Mirador': ['\\bmirador\\b'], 'Plaza Lama Megacentro': ['\\bmegacentro\\b'], 'Plaza Lama La Romana': ['\\bla\\s+romana\\b'], 'Plaza Lama Santiago': ['\\bsantiago\\b'], 'Plaza Lama San Francisco': ['\\bsan\\s+francisco\\b'], 'Plaza Lama Las Americas': ['\\blas\\s+americas\\b'], 'Plaza Lama San Pedro': ['\\bsan\\s+pedro\\b']}
_LEGACY_BRANCH_ALIASES = BRANCH_ALIASES
from branch_directory import BRANCH_DIRECTORY, BRANCH_ALIASES as _DETERMINISTIC_BRANCH_ALIASES
BRANCH_ALIASES = {**_LEGACY_BRANCH_ALIASES}
for _branch_name, _patterns in _DETERMINISTIC_BRANCH_ALIASES.items():
    BRANCH_ALIASES.setdefault(_branch_name, [])
    BRANCH_ALIASES[_branch_name] = list(dict.fromkeys([*BRANCH_ALIASES[_branch_name], *_patterns]))
BRANCH_INFO_KEYWORDS_REGEX = '\\b(horario|hora|abre|cierra|atiende|ubicacion|ubicación|direccion|dirección|donde\\s+queda|donde\\s+está|como\\s+llegar|telefono|teléfono)\\b'
BRANCH_GENERAL_INFO_PATTERNS = [f'{BRANCH_INFO_KEYWORDS_REGEX}']
VAGUE_GENERAL_START_PATTERNS = ['^(necesito|quiero|quisiera)\\s+(saber|conocer|informacion|información|preguntar)\\b', '^tengo\\s+una\\s+pregunta\\b', '^tengo\\s+una\\s+duda\\b', '^(tengo\\s+)?una\\s+consulta\\b', '^(quiero|quisiera|necesito)\\s+(hacer\\s+)?(una\\s+)?consulta\\b']
EXPLICIT_NEW_REQUEST_PATTERNS = ['^(otra|nuevo|nueva)\\s+(pregunta|consulta|solicitud|tema|asunto)\\b', '^(cambiar\\s+de\\s+tema|quiero\\s+preguntar\\s+otra\\s+cosa)\\b']
CONSULTA_FACTURA_PATTERNS = ['\\bfactura\\b', '\\bnumero\\s+de\\s+(factura|orden)\\b', '\\bmi\\s+factura\\b', '\\btengo\\s+una\\s+factura\\b', '\\b(consultar|revisar|verificar|ver)\\s+(mi\\s+)?(factura|orden|numero|estado\\s+de)\\b', '\\b(estado|estatus|seguimiento)\\s+(de\\s+)?(mi\\s+)?(factura|entrega|orden)\\b', '\\bconsulta\\s+(de\\s+)?(una?\\s+)?(factura|orden|entrega)\\b', '\\bhacer\\s+una\\s+consulta\\s+de\\b']
BEDROCK_ROUTE_PATTERNS = ['\\b(reclamacion|reclamaciÃ³n|queja|garantia|garantÃ\xada|devolucion|devoluciÃ³n)\\b', '\\b(producto\\s+daÃ±ado|danado|defectuoso)\\b', '\\bnumero\\s+de\\s+caso\\b', '\\bnÃºmero\\s+de\\s+caso\\b']
