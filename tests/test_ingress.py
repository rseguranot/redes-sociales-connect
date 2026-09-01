import importlib.util
import os
import sys
import time
import types
import unittest
from decimal import Decimal
from pathlib import Path


class _Dummy:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: _Dummy()


if "boto3" not in sys.modules:
    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = lambda *_a, **_k: _Dummy()
    fake_boto3.resource = lambda *_a, **_k: _Dummy()
    sys.modules["boto3"] = fake_boto3
if "boto3.dynamodb.conditions" not in sys.modules:
    conditions = types.ModuleType("boto3.dynamodb.conditions")
    conditions.Key = lambda *_a, **_k: _Dummy()
    sys.modules.setdefault("boto3.dynamodb", types.ModuleType("boto3.dynamodb"))
    sys.modules["boto3.dynamodb.conditions"] = conditions
if "botocore.config" not in sys.modules:
    botocore_config = types.ModuleType("botocore.config")
    botocore_config.Config = lambda **kwargs: kwargs
    sys.modules.setdefault("botocore", types.ModuleType("botocore"))
    sys.modules["botocore.config"] = botocore_config

os.environ.update({"STATE_TABLE": "x", "CAMPAIGN_QUEUE_URL": "campaign.fifo"})
path = Path(__file__).parents[1] / "src" / "ingress" / "app.py"
spec = importlib.util.spec_from_file_location("ingress", path)
ingress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingress)


class _QueueCapture:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": str(len(self.calls))}


class IngressOrderingTests(unittest.TestCase):
    def setUp(self):
        os.environ.update({
            "CONNECT_INSTANCE_ID": "instance-1",
            "ADMIN_APP_NAMESPACE": "redes-sociales-connect",
            "ADMIN_APP_AUTH_MODE": "connect-context-preview",
            "DEVELOPER_ROUTING_PROFILE_IDS": "routing-dev",
            "DEVELOPER_SECURITY_PROFILE_IDS": "security-dev",
        })

    def test_meta_webhook_is_split_by_customer(self):
        body = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
                "contacts": [{"wa_id": "18495550100", "profile": {"name": "Ana"}}],
                "messages": [
                    {"id": "wamid.1", "from": "18495550100", "type": "text", "text": {"body": "Uno"}},
                    {"id": "wamid.2", "from": "18495550100", "type": "text", "text": {"body": "Dos"}},
                ],
            }}]}],
        }
        units = ingress._meta_units(body)
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0][1], units[1][1])
        self.assertNotEqual(units[0][2], units[1][2])
        self.assertEqual(len(units[0][0]["entry"][0]["changes"][0]["value"]["messages"]), 1)

    def test_fifo_enqueue_uses_stable_hashes(self):
        capture = _QueueCapture()
        original = ingress._sqs
        ingress._sqs = capture
        try:
            ingress._enqueue_fifo("queue.fifo", {"ok": True}, "whatsapp:1", "message:1")
        finally:
            ingress._sqs = original
        call = capture.calls[0]
        self.assertEqual(len(call["MessageGroupId"]), 64)
        self.assertEqual(len(call["MessageDeduplicationId"]), 64)

    def test_dynamodb_numbers_are_serialized_for_admin_responses(self):
        response = ingress._response(200, {"count": Decimal("12"), "rate": Decimal("0.5")})
        self.assertEqual(response["body"], '{"count": 12, "rate": 0.5}')

    def test_flow_json_rejects_missing_terminal_screen(self):
        with self.assertRaisesRegex(ValueError, "flow_terminal_screen_required"):
            ingress._validated_flow_json({"version": "7.1", "screens": [{"id": "FORMULARIO"}]})

    def test_flow_json_accepts_generated_shape(self):
        definition = {
            "version": "7.1",
            "screens": [{"id": "FORMULARIO", "terminal": True, "layout": {"type": "SingleColumnLayout", "children": []}}],
        }
        parsed, encoded = ingress._validated_flow_json(definition)
        self.assertEqual(parsed["screens"][0]["id"], "FORMULARIO")
        self.assertIn(b'"version":"7.1"', encoded)

    def test_template_body_requires_examples_for_named_variables(self):
        with self.assertRaisesRegex(ValueError, "template_variable_examples_required"):
            ingress._template_component_body("Hola {{nombre}}", {})
        component = ingress._template_component_body("Hola {{nombre}}", {"nombre": "María"})
        self.assertEqual(component["example"]["body_text_named_params"][0]["param_name"], "nombre")

    def test_publish_requires_explicit_confirmation_before_meta_call(self):
        original_context = ingress._meta_context
        ingress._meta_context = lambda: ("v26.0", {"Authorization": "Bearer hidden"}, "waba")
        try:
            with self.assertRaisesRegex(ValueError, "publish_confirmation_required"):
                ingress._meta_flow_command({"subject": "developer"}, {"action": "publish", "flow_id": "123"})
        finally:
            ingress._meta_context = original_context

    def test_campaign_is_fanned_out_per_recipient(self):
        capture = _QueueCapture()
        writes, updates = [], []
        original, original_ddb = ingress._sqs, ingress._ddb

        class Table:
            def put_item(self, **kwargs):
                writes.append(kwargs["Item"])

            def update_item(self, **kwargs):
                updates.append(kwargs)

        class Resource:
            def Table(self, _name):
                return Table()

        ingress._sqs = capture
        ingress._ddb = Resource()
        try:
            count = ingress._enqueue_admin(
                "campaign",
                {
                    "campaign_id": "summer", "name": "Encuesta verano",
                    "template": {"name": "testing_encuesta", "language": {"code": "es"}},
                    "flow_ids": ["flow-1"],
                    "flow_names": ["Testing encuesta"],
                    "recipients": [{"to": "18490000001"}, {"to": "18490000002"}],
                },
                "request-1",
                {"subject": "test-user", "email": "test@example.com"},
            )
        finally:
            ingress._sqs, ingress._ddb = original, original_ddb
        self.assertEqual(count, 2)
        self.assertEqual(len(capture.calls), 1)
        queued = __import__("json").loads(capture.calls[0]["MessageBody"])
        self.assertEqual(queued["command"], "campaign")
        self.assertEqual(len(queued["body"]["recipients"]), 2)
        self.assertEqual(writes[0]["pk"], "ADMIN#CAMPAIGNS")
        self.assertEqual(writes[0]["template_name"], "testing_encuesta")
        self.assertEqual(writes[0]["flow_ids"], ["flow-1"])
        self.assertEqual(writes[0]["flow_names"], ["Testing encuesta"])
        self.assertEqual(len(updates), 2)

    def test_segment_contacts_are_normalized_and_stored(self):
        writes = []
        original_ddb = ingress._ddb

        class Batch:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def put_item(self, **kwargs):
                writes.append(kwargs["Item"])

        class Table:
            def batch_writer(self):
                return Batch()

        class Resource:
            def Table(self, _name):
                return Table()

        ingress._ddb = Resource()
        try:
            response = ingress._segments_response("POST", {
                "name": "Clientes agosto",
                "source": "csv",
                "contacts": [{
                    "name": "Ana Pérez",
                    "phones": ["+1 (849) 555-0101", "849-555-0102"],
                    "document_id": "001-0000000-1",
                    "email": "ANA@example.com",
                }],
            })
        finally:
            ingress._ddb = original_ddb
        body = __import__("json").loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["contact_count"], 1)
        self.assertEqual(body["phone_count"], 2)
        self.assertEqual(body["available_fields"], ["name", "phone", "document_id", "email"])
        self.assertEqual(body["field_counts"]["email"], 1)
        self.assertEqual(writes[0]["pk"], "ADMIN#SEGMENTS")
        self.assertEqual(writes[2]["phones"], ["+18495550101", "8495550102"])
        self.assertEqual(writes[2]["email"], "ana@example.com")

    def test_segment_detail_returns_contacts_for_authorized_export(self):
        original_ddb = ingress._ddb

        class Table:
            def query(self, **_kwargs):
                return {"Items": [
                    {"pk": "SEGMENT#seg-1", "sk": "META", "id": "seg-1", "name": "Clientes", "contact_count": 1},
                    {"pk": "SEGMENT#seg-1", "sk": "MEMBER#000000", "id": "contact-1", "name": "Ana", "phones": ["18490000001"], "email": "ana@example.com", "ttl": 1},
                ]}

        class Resource:
            def Table(self, _name):
                return Table()

        ingress._ddb = Resource()
        try:
            response = ingress._segments_response("GET", segment_id="seg-1")
        finally:
            ingress._ddb = original_ddb
        body = __import__("json").loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["segment"]["name"], "Clientes")
        self.assertEqual(body["contacts"][0]["phones"], ["18490000001"])
        self.assertNotIn("ttl", body["contacts"][0])

    def test_campaign_can_resolve_recipients_from_segment(self):
        capture = _QueueCapture()
        writes, updates = [], []
        original, original_ddb = ingress._sqs, ingress._ddb

        class Table:
            def query(self, **kwargs):
                if "Limit" in kwargs and kwargs["Limit"] == 250:
                    return {"Items": [{"sk": "META"}, {"sk": "MEMBER#000000", "name": "Ana", "phones": ["18490000001", "18490000002"]}]}
                return {"Items": []}

            def put_item(self, **kwargs):
                writes.append(kwargs["Item"])

            def update_item(self, **kwargs):
                updates.append(kwargs)

        class Resource:
            def Table(self, _name):
                return Table()

        ingress._sqs, ingress._ddb = capture, Resource()
        try:
            count = ingress._enqueue_admin("campaign", {
                "campaign_id": "segment-test",
                "name": "Informativa",
                "segment_id": "seg-1",
                "segment_name": "Clientes",
                "phone_strategy": "primary",
                "campaign_type": "informative",
                "template": {"name": "hola_cliente", "language": {"code": "es"}},
            }, "request-segment", {"subject": "agent"})
        finally:
            ingress._sqs, ingress._ddb = original, original_ddb
        self.assertEqual(count, 1)
        self.assertEqual(len(capture.calls), 1)
        self.assertEqual(writes[0]["segment_id"], "seg-1")
        self.assertEqual(writes[0]["campaign_type"], "informative")

    def test_campaign_personalizes_template_from_segment_fields(self):
        capture = _QueueCapture()
        writes = []
        original, original_ddb = ingress._sqs, ingress._ddb

        class Table:
            def query(self, **kwargs):
                return {"Items": [{
                    "sk": "MEMBER#000000", "name": "Ana", "phones": ["18490000001"],
                    "document_id": "001", "email": "ana@example.com",
                }]}

            def put_item(self, **kwargs):
                writes.append(kwargs["Item"])

            def update_item(self, **_kwargs):
                return None

        class Resource:
            def Table(self, _name):
                return Table()

        ingress._sqs, ingress._ddb = capture, Resource()
        try:
            count = ingress._enqueue_admin("campaign", {
                "campaign_id": "dynamic-test", "segment_id": "seg-1",
                "template": {"name": "hola_cliente", "language": {"code": "es"}},
                "variable_mappings": {"1": "name", "2": "phone"},
            }, "request-dynamic", {"subject": "agent"})
        finally:
            ingress._sqs, ingress._ddb = original, original_ddb
        self.assertEqual(count, 1)
        queued = __import__("json").loads(capture.calls[0]["MessageBody"])
        parameters = queued["body"]["recipients"][0]["template"]["components"][0]["parameters"]
        self.assertEqual([value["text"] for value in parameters], ["Ana", "18490000001"])
        self.assertEqual(writes[0]["variable_mappings"], {"1": "name", "2": "phone"})

    def test_quote_queues_template_before_document_for_each_recipient(self):
        capture = _QueueCapture()
        original = ingress._sqs
        ingress._sqs = capture
        try:
            count = ingress._enqueue_admin(
                "quote",
                {"to": "18490000001", "template": {"name": "hola_cliente"}, "media": {"type": "document", "s3_key": "quote.pdf"}},
                "request-1", {"subject": "agent"},
            )
        finally:
            ingress._sqs = original
        self.assertEqual(count, 2)
        queued = [__import__("json").loads(call["MessageBody"]) for call in capture.calls]
        self.assertEqual(queued[0]["body"]["quote_stage"], "template")
        self.assertEqual(queued[1]["body"]["quote_stage"], "document")
        self.assertEqual(capture.calls[0]["MessageGroupId"], capture.calls[1]["MessageGroupId"])

    def test_meta_templates_returns_only_approved_templates(self):
        original_secret, original_meta = ingress._secret, ingress._meta_json
        calls = []
        ingress._secret = lambda: {
            "WA_ACCESS_TOKEN": "token", "WA_PHONE_NUMBER_ID": "phone", "WA_BUSINESS_ACCOUNT_ID": "waba"
        }

        def meta(url, _headers):
            calls.append(url)
            return {"data": [
                {"name": "hola_cliente", "language": "es", "category": "MARKETING", "status": "APPROVED", "components": [{"type": "BODY", "text": "Hola {{1}}"}]},
                {"name": "borrador", "language": "es", "category": "MARKETING", "status": "PENDING", "components": []},
            ]}

        ingress._meta_json = meta
        try:
            response = ingress._meta_templates_response()
        finally:
            ingress._secret, ingress._meta_json = original_secret, original_meta
        body = __import__("json").loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["items"][0]["name"], "hola_cliente")
        self.assertEqual(body["items"][0]["variables"], [1])
        self.assertEqual(len(body["items"]), 1)
        self.assertTrue(all("/waba/" in url for url in calls))

    def test_meta_templates_supports_named_parameters(self):
        original_secret, original_meta = ingress._secret, ingress._meta_json
        ingress._secret = lambda: {
            "WA_ACCESS_TOKEN": "token", "WA_PHONE_NUMBER_ID": "phone", "WA_BUSINESS_ACCOUNT_ID": "waba"
        }
        ingress._meta_json = lambda _url, _headers: {"data": [{
            "name": "envio_cotizacion_solicitada",
            "language": "es_DO",
            "category": "UTILITY",
            "status": "APPROVED",
            "parameter_format": "NAMED",
            "components": [{
                "type": "HEADER", "format": "TEXT", "text": "Envío de cotización",
            }, {
                "type": "BODY",
                "text": "Hola {{nombre}}. Le atiende {{nombre_agente}}. Gracias.",
                "example": {"body_text_named_params": [
                    {"param_name": "nombre", "example": "María"},
                    {"param_name": "nombre_agente", "example": "Agente Ejemplo"},
                ]},
            }, {"type": "FOOTER", "text": "Empresa Ejemplo, S.A."}],
        }]}
        try:
            response = ingress._meta_templates_response()
        finally:
            ingress._secret, ingress._meta_json = original_secret, original_meta
        item = __import__("json").loads(response["body"])["items"][0]
        self.assertEqual(item["variables"], ["nombre", "nombre_agente"])
        self.assertEqual(item["parameter_format"], "NAMED")
        self.assertEqual(item["variable_examples"]["nombre_agente"], "Agente Ejemplo")
        self.assertEqual(item["header"], "Envío de cotización")
        self.assertEqual(item["footer"], "Empresa Ejemplo, S.A.")

    def test_meta_catalog_uses_last_successful_cache_when_meta_fails(self):
        stored = {}

        class Table:
            def put_item(self, Item):
                stored.update(Item)

            def get_item(self, **_kwargs):
                return {"Item": dict(stored)} if stored else {}

        class Ddb:
            def Table(self, _name):
                return Table()

        original = ingress._ddb
        ingress._ddb = Ddb()
        try:
            live = ingress._meta_catalog_with_cache(
                "templates", lambda: ingress._response(200, {"items": [{"id": "template-1"}]})
            )
            cached = ingress._meta_catalog_with_cache(
                "templates", lambda: (_ for _ in ()).throw(RuntimeError("Meta unavailable"))
            )
        finally:
            ingress._ddb = original
        live_body = __import__("json").loads(live["body"])
        cached_body = __import__("json").loads(cached["body"])
        self.assertFalse(live_body["stale"])
        self.assertTrue(cached_body["stale"])
        self.assertEqual(cached_body["items"], [{"id": "template-1"}])

    def test_meta_flows_returns_published_and_draft_flows(self):
        original_secret, original_meta = ingress._secret, ingress._meta_json
        ingress._secret = lambda: {
            "WA_ACCESS_TOKEN": "token", "WA_PHONE_NUMBER_ID": "phone", "WA_BUSINESS_ACCOUNT_ID": "waba"
        }

        def meta(url, _headers):
            return {"data": [
                {"id": "1823853561976111", "name": "testing encuesta", "status": "PUBLISHED", "updated_time": "2026-08-24T00:00:00+0000"},
                {"id": "draft", "name": "borrador", "status": "DRAFT"},
            ]}

        ingress._meta_json = meta
        try:
            response = ingress._meta_flows_response()
        finally:
            ingress._secret, ingress._meta_json = original_secret, original_meta
        body = __import__("json").loads(response["body"])
        self.assertEqual(body["items"][0]["status"], "Publicado")
        self.assertFalse(body["items"][1]["published"])

    def test_connect_agent_on_development_routing_gets_developer_role(self):
        original = ingress._connect
        agent_arn = "arn:aws:connect:us-east-1:123:instance/instance-1/agent/agent-1"

        class Connect:
            def describe_user(self, **_kwargs):
                return {"User": {
                    "Arn": agent_arn, "Username": "agente.dev", "RoutingProfileId": "routing-dev",
                    "SecurityProfileIds": ["admin"],
                    "IdentityInfo": {"FirstName": "Agente", "LastName": "Ejemplo"},
                }}

            def list_security_profile_applications(self, **_kwargs):
                return {"Applications": [{
                    "Namespace": "redes-sociales-connect", "ApplicationPermissions": ["ACCESS"]
                }]}

            def list_security_profile_permissions(self, **_kwargs):
                return {"Permissions": ["SecurityProfiles.Edit"]}

        ingress._connect = Connect()
        try:
            actor = ingress._connect_actor(agent_arn)
        finally:
            ingress._connect = original
        self.assertEqual(actor["role"], "developer")
        self.assertEqual(actor["name"], "Agente Ejemplo")

    def test_admin_context_only_session_is_disabled_by_default(self):
        previous = os.environ.get("ADMIN_APP_AUTH_MODE")
        os.environ["ADMIN_APP_AUTH_MODE"] = "disabled"
        try:
            response = ingress._create_connect_session(
                {"headers": {"origin": "https://example.invalid"}},
                {"agent_arn": "arn:aws:connect:us-east-1:123:instance/instance-1/agent/agent-1"},
            )
        finally:
            if previous is None:
                os.environ.pop("ADMIN_APP_AUTH_MODE", None)
            else:
                os.environ["ADMIN_APP_AUTH_MODE"] = previous
        self.assertEqual(response["statusCode"], 503)
        self.assertIn("admin_auth_not_configured", response["body"])

    def test_connect_agent_with_developers_security_profile_is_always_developer(self):
        original = ingress._connect
        agent_arn = "arn:aws:connect:us-east-1:123:instance/instance-1/agent/agent-dev"

        class Connect:
            def describe_user(self, **_kwargs):
                return {"User": {
                    "Arn": agent_arn, "Username": "developer", "RoutingProfileId": "ordinary-routing",
                    "SecurityProfileIds": ["security-dev"],
                }}

            def list_security_profile_applications(self, **_kwargs):
                return {"Applications": [{
                    "Namespace": "redes-sociales-connect", "ApplicationPermissions": ["ACCESS"]
                }]}

            def list_security_profile_permissions(self, **_kwargs):
                return {"Permissions": []}

        ingress._connect = Connect()
        try:
            actor = ingress._connect_actor(agent_arn)
        finally:
            ingress._connect = original
        self.assertEqual(actor["role"], "developer")

    def test_connect_agent_without_live_contact_is_allowed(self):
        """Agent Workspace access must not require a current contact or presence."""
        original = ingress._connect
        agent_arn = "arn:aws:connect:us-east-1:123:instance/instance-1/agent/agent-1"

        class Connect:
            def describe_user(self, **_kwargs):
                return {"User": {
                    "Arn": agent_arn, "Username": "agente.dev", "RoutingProfileId": "normal",
                    "SecurityProfileIds": ["agent"],
                }}

            def list_security_profile_applications(self, **_kwargs):
                return {"Applications": [{
                    "Namespace": "redes-sociales-connect", "ApplicationPermissions": ["ACCESS"]
                }]}

            def list_security_profile_permissions(self, **_kwargs):
                return {"Permissions": ["BasicAgentAccess"]}

        ingress._connect = Connect()
        try:
            actor = ingress._connect_actor(agent_arn)
        finally:
            ingress._connect = original
        self.assertEqual(actor["role"], "agent")

    def test_connect_agent_without_application_access_is_rejected(self):
        original = ingress._connect
        agent_arn = "arn:aws:connect:us-east-1:123:instance/instance-1/agent/agent-1"

        class Connect:
            def describe_user(self, **_kwargs):
                return {"User": {"Arn": agent_arn, "SecurityProfileIds": ["agent"], "RoutingProfileId": "normal"}}

            def get_current_user_data(self, **_kwargs):
                return {"UserDataList": [{"User": {"Id": "agent-1"}, "RoutingProfile": {"Id": "normal"}}]}

            def list_security_profile_applications(self, **_kwargs):
                return {"Applications": []}

            def list_security_profile_permissions(self, **_kwargs):
                return {"Permissions": ["BasicAgentAccess"]}

        ingress._connect = Connect()
        try:
            actor = ingress._connect_actor(agent_arn)
        finally:
            ingress._connect = original
        self.assertIsNone(actor)

    def test_only_developer_can_manage_profile_visibility(self):
        response = ingress._access_profiles_response({"role": "admin"}, "GET", None)
        self.assertEqual(response["statusCode"], 403)

    def test_module_permissions_are_granular_by_business_action(self):
        self.assertEqual(ingress.MODULE_ACTIONS["segments"], {"view", "create", "import"})
        self.assertEqual(ingress.MODULE_ACTIONS["campaigns"], {"view", "create", "send", "delete"})
        self.assertEqual(ingress.MODULE_ACTIONS["quotes"], {"view", "send"})
        self.assertEqual(ingress.MODULE_ACTIONS["responses"], {"view"})

    def test_legacy_manage_grants_migrate_without_broadening_other_modules(self):
        grants = ingress._normalized_grants({
            "segments": {"view": True, "manage": True},
            "campaigns": {"view": True, "manage": True},
            "responses": {"view": False},
        })
        self.assertTrue(grants["segments"]["create"])
        self.assertTrue(grants["segments"]["import"])
        self.assertTrue(grants["campaigns"]["create"])
        self.assertTrue(grants["campaigns"]["send"])
        self.assertFalse(grants["responses"]["view"])
        self.assertFalse(grants["quotes"]["send"])
        self.assertFalse(grants["campaigns"]["delete"])

    def test_campaign_status_uses_delivery_and_flow_response_counts(self):
        flow = {"recipient_count": 2, "campaign_type": "survey", "flow_ids": ["flow-1"]}
        self.assertEqual(
            ingress._campaign_status(flow, accepted_count=2, delivered_count=2, response_count=2)["status"],
            "COMPLETED",
        )
        self.assertEqual(
            ingress._campaign_status(flow, accepted_count=2, delivered_count=2, response_count=1)["status"],
            "PARTIAL_RESPONSES",
        )
        self.assertEqual(
            ingress._campaign_status(flow, accepted_count=2, delivered_count=2, response_count=0)["status"],
            "AWAITING_RESPONSES",
        )
        informative = {"recipient_count": 2, "campaign_type": "informative"}
        self.assertEqual(
            ingress._campaign_status(informative, accepted_count=2, delivered_count=2, response_count=0)["status"],
            "COMPLETED",
        )

    def test_campaign_soft_delete_requires_exact_name_and_is_recoverable(self):
        updates = []

        class Table:
            def get_item(self, **_kwargs):
                return {"Item": {"id": "camp-1", "name": "Encuesta agosto"}}

            def update_item(self, **kwargs):
                updates.append(kwargs)

        class Ddb:
            def Table(self, _name):
                return Table()

        original = ingress._ddb
        ingress._ddb = Ddb()
        try:
            rejected = ingress._campaign_delete_response(
                {"agent_arn": "arn:agent", "name": "Developer"},
                {"campaign_id": "camp-1", "confirmation_name": "Encuesta"},
            )
            accepted = ingress._campaign_delete_response(
                {"agent_arn": "arn:agent", "name": "Developer"},
                {"campaign_id": "camp-1", "confirmation_name": "Encuesta agosto"},
            )
        finally:
            ingress._ddb = original
        self.assertEqual(rejected["statusCode"], 400)
        self.assertEqual(accepted["statusCode"], 200)
        self.assertEqual(len(updates), 2)
        self.assertTrue(all("deleted_at" in call["UpdateExpression"] for call in updates))

    def test_developer_can_grant_application_to_security_profile(self):
        original = ingress._connect
        updates = []

        class Connect:
            def list_security_profile_applications(self, **_kwargs):
                return {"Applications": []}

            def update_security_profile(self, **kwargs):
                updates.append(kwargs)

        ingress._connect = Connect()
        try:
            response = ingress._access_profiles_response(
                {"role": "developer", "security_profile_ids": ["admin"]},
                "POST", {"security_profile_id": "agent", "enabled": True},
            )
        finally:
            ingress._connect = original
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(updates[0]["Applications"][0]["Namespace"], "redes-sociales-connect")
        self.assertEqual(updates[0]["Applications"][0]["Type"], "THIRD_PARTY_APPLICATION")

    def test_ready_short_media_link_redirects_to_fresh_inline_s3_url(self):
        originals = ingress._ddb, ingress._s3
        generated = []

        class Table:
            def get_item(self, **_kwargs):
                return {"Item": {
                    "status": "READY", "expires_at": int(time.time()) + 60,
                    "s3_key": "inbound/photo.jpg", "content_type": "image/jpeg",
                    "content_disposition": 'inline; filename="foto.jpg"',
                }}

        class Dynamo:
            def Table(self, _name):
                return Table()

        class S3:
            def generate_presigned_url(self, operation, **kwargs):
                generated.append((operation, kwargs))
                return "https://s3.test/fresh-signed-url"

        ingress._ddb, ingress._s3 = Dynamo(), S3()
        os.environ.update({"MEDIA_BUCKET": "media-bucket", "MEDIA_REDIRECT_SECONDS": "300"})
        try:
            response = ingress._media_redirect("AbCdEfGhIjKlMnOp")
        finally:
            ingress._ddb, ingress._s3 = originals
        self.assertEqual(response["statusCode"], 302)
        self.assertEqual(response["headers"]["location"], "https://s3.test/fresh-signed-url")
        self.assertEqual(generated[0][0], "get_object")
        self.assertEqual(generated[0][1]["ExpiresIn"], 300)
        self.assertEqual(generated[0][1]["Params"]["ResponseContentType"], "image/jpeg")

    def test_pending_short_media_link_asks_browser_to_retry(self):
        original = ingress._ddb

        class Table:
            def get_item(self, **_kwargs):
                return {"Item": {"status": "PENDING", "expires_at": int(time.time()) + 60}}

        class Dynamo:
            def Table(self, _name):
                return Table()

        ingress._ddb = Dynamo()
        try:
            response = ingress._media_redirect("AbCdEfGhIjKlMnOp")
        finally:
            ingress._ddb = original
        self.assertEqual(response["statusCode"], 425)
        self.assertEqual(response["headers"]["retry-after"], "3")

    def test_expired_short_media_link_does_not_reveal_s3(self):
        original = ingress._ddb

        class Table:
            def get_item(self, **_kwargs):
                return {"Item": {"status": "READY", "expires_at": int(time.time()) - 1, "s3_key": "secret"}}

        class Dynamo:
            def Table(self, _name):
                return Table()

        ingress._ddb = Dynamo()
        try:
            response = ingress._media_redirect("AbCdEfGhIjKlMnOp")
        finally:
            ingress._ddb = original
        self.assertEqual(response["statusCode"], 410)
        self.assertNotIn("secret", response["body"])


if __name__ == "__main__":
    unittest.main()
