import importlib.util
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path


class _Dummy:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: _Dummy()


fake_boto3 = types.ModuleType("boto3")
fake_boto3.client = lambda *_a, **_k: _Dummy()
fake_boto3.resource = lambda *_a, **_k: _Dummy()
sys.modules.setdefault("boto3", fake_boto3)
conditions = types.ModuleType("boto3.dynamodb.conditions")
conditions.Key = lambda *_a, **_k: _Dummy()
sys.modules.setdefault("boto3.dynamodb", types.ModuleType("boto3.dynamodb"))
sys.modules.setdefault("boto3.dynamodb.conditions", conditions)
botocore = types.ModuleType("botocore.exceptions")
botocore.ClientError = Exception
sys.modules.setdefault("botocore", types.ModuleType("botocore"))
sys.modules.setdefault("botocore.exceptions", botocore)
botocore_config = types.ModuleType("botocore.config")
botocore_config.Config = lambda **kwargs: kwargs
sys.modules.setdefault("botocore.config", botocore_config)

os.environ.update({"STATE_TABLE": "x"})
path = Path(__file__).parents[1] / "src" / "processor" / "app.py"
spec = importlib.util.spec_from_file_location("processor", path)
processor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(processor)


class ParserTests(unittest.TestCase):
    def test_bsuid_and_username_are_preferred(self):
        change = {"contacts": [{"user_id": "US.123", "profile": {"username": "cliente", "name": "Ana"}}]}
        identity = processor._identity(change, {"from_user_id": "US.123"})
        self.assertEqual(identity["id"], "US.123")
        self.assertEqual(identity["phone"], "")
        self.assertEqual(identity["username"], "cliente")

    def test_legacy_phone_is_supported(self):
        identity = processor._identity({"contacts": [{"wa_id": "18095550100"}]}, {"from": "18095550100"})
        self.assertEqual(identity["id"], "18095550100")
        self.assertEqual(identity["phone"], "18095550100")

    def test_agent_display_name_includes_whatsapp_phone(self):
        display_name = processor._participant_display_name({
            "id": "CRM-123", "name": "Cliente Ejemplo", "phone": "15555550100"
        })
        self.assertEqual(display_name, "Cliente Ejemplo | 15555550100")

    def test_agent_display_name_does_not_duplicate_phone_fallback(self):
        display_name = processor._participant_display_name({
            "id": "15555550100", "name": "15555550100", "phone": "15555550100"
        })
        self.assertEqual(display_name, "15555550100")

    def test_development_phone_selects_isolated_flow(self):
        old_flow = os.environ.get("DEVELOPMENT_CONTACT_FLOW_ID")
        old_numbers = os.environ.get("DEVELOPMENT_PHONE_NUMBERS")
        os.environ["DEVELOPMENT_CONTACT_FLOW_ID"] = "dev-flow"
        os.environ["DEVELOPMENT_PHONE_NUMBERS"] = "+1 555-555-0100,15555550101"
        try:
            self.assertEqual(processor._development_contact_flow("15555550100"), "dev-flow")
            self.assertEqual(processor._development_contact_flow("15555550999"), "")
        finally:
            if old_flow is None:
                os.environ.pop("DEVELOPMENT_CONTACT_FLOW_ID", None)
            else:
                os.environ["DEVELOPMENT_CONTACT_FLOW_ID"] = old_flow
            if old_numbers is None:
                os.environ.pop("DEVELOPMENT_PHONE_NUMBERS", None)
            else:
                os.environ["DEVELOPMENT_PHONE_NUMBERS"] = old_numbers

    def test_location_is_visible_to_agent(self):
        text, _ = processor._content({"type": "location", "location": {"latitude": 18.4, "longitude": -69.9}})
        self.assertIn("maps.google.com", text)

    def test_whatsapp_flow_reply_is_parsed_with_campaign_token(self):
        message = {
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "name": "flow",
                    "response_json": json.dumps({
                        "flow_token": "camp-123", "calificacion": "Excelente", "comentario": "Muy bien"
                    }),
                },
            },
        }
        reply = processor._flow_reply(message)
        text, reply_id = processor._content(message)
        self.assertEqual(reply["flow_token"], "camp-123")
        self.assertEqual(reply["answers"][0], {"field": "calificacion", "value": "Excelente"})
        self.assertIn("comentario: Muy bien", text)
        self.assertIsNone(reply_id)

    def test_flow_reply_is_stored_under_its_campaign(self):
        puts, updates = [], []
        original = processor.ddb

        class Table:
            def get_item(self, **kwargs):
                if kwargs["Key"] == {"pk": "CAMPAIGN#camp-123", "sk": "META"}:
                    return {"Item": {"template_name": "testing_encuesta", "flow_ids": ["flow-1"]}}
                return {}

            def put_item(self, **kwargs):
                puts.append(kwargs["Item"])

            def update_item(self, **kwargs):
                updates.append(kwargs)

        processor.ddb = Table()
        try:
            campaign_id = processor._store_flow_response(
                {"flow_token": "camp-123", "answers": [{"field": "nota", "value": "5"}]},
                {"id": "18495550100", "name": "Ana", "phone": "18495550100"},
                "wamid.flow", "Formulario de WhatsApp recibido\nnota: 5",
            )
        finally:
            processor.ddb = original
        self.assertEqual(campaign_id, "camp-123")
        self.assertEqual(puts[0]["pk"], "CAMPAIGN#camp-123")
        self.assertEqual(puts[0]["flow_id"], "flow-1")
        self.assertEqual(puts[0]["answers"], [{"field": "nota", "value": "5"}])
        self.assertEqual(len(updates), 2)

    def test_whatsapp_bold_is_translated_to_connect_markdown(self):
        text, content_type = processor._connect_text_content("*hola*")
        self.assertEqual(text, "**hola**")
        self.assertEqual(content_type, "text/markdown")

    def test_multiple_whatsapp_styles_do_not_leave_duplicate_markers(self):
        text, content_type = processor._connect_text_content("Hola *Cliente*, esto es _importante_ y ~viejo~.")
        self.assertEqual(text, "Hola **Cliente**, esto es _importante_ y viejo.")
        self.assertEqual(content_type, "text/markdown")

    def test_literal_and_unmatched_asterisks_remain_plain_text(self):
        for value in ("2 * 3", "*sin cerrar", "archivo*.txt", r"\*literal\*"):
            with self.subTest(value=value):
                text, content_type = processor._connect_text_content(value)
                self.assertEqual(text, value)
                self.assertEqual(content_type, "text/plain")

    def test_existing_connect_markdown_is_not_double_converted(self):
        text, content_type = processor._connect_text_content("**hola**")
        self.assertEqual(text, "**hola**")
        self.assertEqual(content_type, "text/markdown")

    def test_photo_without_provider_filename_gets_descriptive_name(self):
        name = processor._attachment_name(
            {"id": "wamid.photo", "timestamp": "1787569812", "image": {}}, "image", "image/jpeg"
        )
        self.assertTrue(name.startswith("foto-whatsapp-"))
        self.assertTrue(name.endswith(".jpg"))

    def test_bedrock_reorders_indices_without_rewriting_ocr_text(self):
        original_bedrock = processor.bedrock

        class Bedrock:
            def converse(self, **_kwargs):
                return {"output": {"message": {"content": [{"text": '{"sections":[{"heading":[1],"body":[0,2]}]}' }]}}}

        processor.bedrock = Bedrock()
        lines = [
            {"id": 0, "text": "Texto exacto A", "page": 1, "top": 0.2, "left": 0.1},
            {"id": 1, "text": "TÍTULO ÍNTEGRO", "page": 1, "top": 0.1, "left": 0.1},
            {"id": 2, "text": "Texto exacto B", "page": 1, "top": 0.3, "left": 0.1},
        ]
        try:
            result = processor._organized_ocr_text(lines)
        finally:
            processor.bedrock = original_bedrock
        self.assertEqual(result, "TÍTULO ÍNTEGRO\nTexto exacto A\nTexto exacto B")
        for line in lines:
            self.assertEqual(result.count(line["text"]), 1)

    def test_ocr_rejects_low_confidence_hallucinations_and_symbol_only_lines(self):
        result = {"Blocks": [
            {"BlockType": "LINE", "Text": "=", "Confidence": 99},
            {"BlockType": "LINE", "Text": ">", "Confidence": 91},
            {"BlockType": "LINE", "Text": "MA", "Confidence": 10.98},
            {"BlockType": "LINE", "Text": "smith", "Confidence": 16.1},
            {"BlockType": "LINE", "Text": "Texto real y legible", "Confidence": 99.7},
        ]}
        self.assertEqual(
            [line["text"] for line in processor._ocr_lines(result)],
            ["Texto real y legible"],
        )

    def test_ocr_does_not_publish_tiny_non_meaningful_result(self):
        lines = [{"id": 0, "text": "OK", "page": 1, "top": 0.1, "left": 0.1}]
        self.assertEqual(processor._organized_ocr_text(lines), "")

    def test_bedrock_groups_transcript_without_rewriting_words(self):
        original_bedrock = processor.bedrock

        class Bedrock:
            def converse(self, **_kwargs):
                return {"output": {"message": {"content": [{"text": '{"paragraphs":[[0,1],[2]]}'}]}}}

        processor.bedrock = Bedrock()
        source = "Buenos días. Necesito una cotización. Para mañana, por favor."
        try:
            result = processor._organized_transcript_text(source)
        finally:
            processor.bedrock = original_bedrock
        self.assertEqual(result, "Buenos días. Necesito una cotización.\n\nPara mañana, por favor.")
        for sentence in ("Buenos días.", "Necesito una cotización.", "Para mañana, por favor."):
            self.assertEqual(result.count(sentence), 1)

    def test_contacts_include_phone_email_company_and_address(self):
        text, _ = processor._content({"type": "contacts", "contacts": [{
            "name": {"formatted_name": "Ana Pérez"},
            "phones": [{"phone": "+1 809 555 0100"}],
            "emails": [{"email": "ana@example.com"}],
            "org": {"company": "Ejemplo SRL"},
            "addresses": [{"formatted_address": "Santo Domingo, RD"}],
        }]})
        for expected in ("Ana Pérez", "+1 809 555 0100", "ana@example.com", "Ejemplo SRL", "Santo Domingo, RD"):
            self.assertIn(expected, text)

    def test_media_link_uses_short_customer_label_and_hashed_token(self):
        writes = []
        originals = processor.ddb, processor.secure_random.token_urlsafe
        old_base = os.environ.get("MEDIA_LINK_BASE_URL")

        class Table:
            def put_item(self, **kwargs):
                writes.append(kwargs["Item"])

        processor.ddb = Table()
        processor.secure_random.token_urlsafe = lambda _size: "AbCdEfGhIjKlMnOp"
        os.environ["MEDIA_LINK_BASE_URL"] = "https://short.test/m"
        try:
            token, url = processor._reserve_media_link("image")
        finally:
            processor.ddb, processor.secure_random.token_urlsafe = originals
            if old_base is None:
                os.environ.pop("MEDIA_LINK_BASE_URL", None)
            else:
                os.environ["MEDIA_LINK_BASE_URL"] = old_base
        self.assertEqual(token, "AbCdEfGhIjKlMnOp")
        self.assertEqual(url, "https://short.test/m/AbCdEfGhIjKlMnOp")
        self.assertEqual(processor._media_link_label("image"), "Imagen enviada por el cliente")
        self.assertNotIn(token, writes[0]["pk"])
        self.assertEqual(writes[0]["status"], "PENDING")

    def test_media_link_displays_filename_and_preserves_caption(self):
        message = {
            "id": "wamid.photo",
            "timestamp": "1787569812",
            "type": "document",
            "document": {"filename": "cotización [final].pdf", "mime_type": "application/pdf", "caption": "Adjunto"},
        }
        rendered = processor._media_link_text(message, "document", "https://short.test/m/token")
        self.assertEqual(
            rendered,
            "Adjunto\n\n[cotización \\[final\\].pdf](https://short.test/m/token)",
        )

    def test_transcribe_language_defaults_to_spanish_and_allows_auto(self):
        old = os.environ.get("TRANSCRIBE_LANGUAGE_CODE")
        try:
            os.environ.pop("TRANSCRIBE_LANGUAGE_CODE", None)
            self.assertEqual(processor._transcribe_language_parameters(), {"LanguageCode": "es-US"})
            os.environ["TRANSCRIBE_LANGUAGE_CODE"] = "auto"
            self.assertEqual(processor._transcribe_language_parameters(), {"IdentifyLanguage": True})
        finally:
            if old is None:
                os.environ.pop("TRANSCRIBE_LANGUAGE_CODE", None)
            else:
                os.environ["TRANSCRIBE_LANGUAGE_CODE"] = old

    def test_transcription_message_has_only_requested_heading(self):
        self.assertEqual(
            processor._transcription_message("  Hola, estoy haciendo una prueba.  "),
            "Transcripción:\n\nHola, estoy haciendo una prueba.",
        )
        self.assertNotIn("organizada", processor._transcription_message("Texto"))

    def test_media_link_activation_preserves_inline_preview_metadata(self):
        updates = []
        original_ddb = processor.ddb

        class Table:
            def update_item(self, **kwargs):
                updates.append(kwargs)

        processor.ddb = Table()
        try:
            processor._activate_media_link("AbCdEfGhIjKlMnOp", "inbound/photo.jpg", "foto cliente.jpg", "image/jpeg")
        finally:
            processor.ddb = original_ddb
        values = updates[0]["ExpressionAttributeValues"]
        self.assertEqual(values[":s"], "READY")
        self.assertEqual(values[":k"], "inbound/photo.jpg")
        self.assertEqual(values[":c"], "image/jpeg")
        self.assertTrue(values[":d"].startswith("inline;"))

    def test_expired_connect_session_does_not_discard_processed_media(self):
        original_send = processor._send_connect

        class AccessDenied(Exception):
            response = {"Error": {"Code": "AccessDeniedException"}}

        processor._send_connect = lambda *_args, **_kwargs: (_ for _ in ()).throw(AccessDenied("expired"))
        try:
            delivered = processor._send_connect_if_active({"contact_id": "closed-contact"}, "preview")
        finally:
            processor._send_connect = original_send
        self.assertFalse(delivered)

    def test_completed_audio_without_speech_is_audited(self):
        updates = []
        originals = processor.ddb, processor.s3, processor._send_connect_if_active

        class Table:
            def get_item(self, **_kwargs):
                return {"Item": {"contact_id": "contact", "participant_token": "token", "media_type": "audio",
                                 "filename": "prueba.mp3"}}

            def update_item(self, **kwargs):
                updates.append(kwargs)

        class S3:
            def get_object(self, **_kwargs):
                return {"Body": io.BytesIO(json.dumps({"results": {"transcripts": [{"transcript": ""}]}}).encode())}

        processor.ddb, processor.s3 = Table(), S3()
        processor._send_connect_if_active = lambda *_args, **_kwargs: False
        os.environ["MEDIA_BUCKET"] = "test-bucket"
        try:
            processor._transcribe_event({"TranscriptionJobName": "wa-empty", "TranscriptionJobStatus": "COMPLETED"})
        finally:
            processor.ddb, processor.s3, processor._send_connect_if_active = originals
        self.assertEqual(updates[0]["ExpressionAttributeValues"][":s"], "COMPLETED_NO_SPEECH")
        self.assertEqual(updates[0]["ExpressionAttributeValues"][":c"], 0)

    def test_interactive_reply_keeps_route_id(self):
        text, route = processor._content({"type": "interactive", "interactive": {"button_reply": {"id": "cotizar", "title": "Cotizar"}}})
        self.assertEqual((text, route), ("Cotizar", "cotizar"))

    def test_canonical_envelope_exposes_channel_and_sender_asset(self):
        change = {
            "_social_business_id": "business-account-1",
            "metadata": {"phone_number_id": "sender-asset-1"},
            "contacts": [{"wa_id": "15555550100", "profile": {"name": "Ana"}}],
        }
        envelope = processor._canonical_envelope(
            change,
            {"id": "wamid.1", "from": "15555550100", "type": "text", "text": {"body": "Hola"},
             "context": {"id": "wamid.previous"}},
        )
        self.assertEqual(envelope["schema"], "social-message/1.0")
        self.assertEqual(envelope["provider"], "meta_direct")
        self.assertEqual(envelope["channel"], "whatsapp")
        self.assertEqual(envelope["business_id"], "business-account-1")
        self.assertEqual(envelope["sender_asset_id"], "sender-asset-1")
        self.assertEqual(envelope["conversation_key"], "15555550100")
        self.assertEqual(envelope["message"]["reply_to"], "wamid.previous")

    def test_connect_notification_is_requeued_for_ordering(self):
        captured = []
        original = processor._enqueue_fifo
        processor._enqueue_fifo = lambda payload, group, dedup: captured.append((payload, group, dedup))
        os.environ["WORKER_MODE"] = "conversation"
        try:
            processor._dispatch({
                "Type": "Notification",
                "Message": '{"ContactId":"contact-1","Id":"event-1","ParticipantRole":"AGENT"}',
            })
        finally:
            processor._enqueue_fifo = original
        self.assertEqual(captured[0][1], "connect:contact-1")
        self.assertEqual(captured[0][0]["source"], "connect_ordered")

    def test_new_session_marks_customer_connected(self):
        calls = []
        original_ddb, original_connect, original_participant = processor.ddb, processor.connect, processor.participant

        class Table:
            def get_item(self, **_kwargs):
                return {}

            def put_item(self, **_kwargs):
                calls.append(("put_item", _kwargs))

        class Connect:
            def start_chat_contact(self, **_kwargs):
                calls.append(("start_chat_contact", _kwargs))
                return {"ContactId": "contact-1", "ParticipantToken": "participant-token"}

            def start_contact_streaming(self, **_kwargs):
                calls.append(("start_contact_streaming", _kwargs))

        class Participant:
            def create_participant_connection(self, **_kwargs):
                calls.append(("create_participant_connection", _kwargs))
                return {"ConnectionCredentials": {"ConnectionToken": "connection-token"}}

        os.environ.update({
            "CONNECT_INSTANCE_ID": "instance-1", "DEFAULT_CONTACT_FLOW_ID": "flow-1",
            "OUTBOUND_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:outbound",
            "DEVELOPMENT_CONTACT_FLOW_ID": "", "DEVELOPMENT_PHONE_NUMBERS": "",
        })
        processor.ddb, processor.connect, processor.participant = Table(), Connect(), Participant()
        try:
            processor._session(
                {"id": "customer-1", "name": "Ana", "phone": "18095550100", "user_id": "", "username": ""},
                "Hola", {}, "event-1",
            )
        finally:
            processor.ddb, processor.connect, processor.participant = original_ddb, original_connect, original_participant
        connection = next(args for name, args in calls if name == "create_participant_connection")
        start = next(args for name, args in calls if name == "start_chat_contact")
        self.assertTrue(connection["ConnectParticipant"])
        self.assertEqual(connection["ParticipantToken"], "participant-token")
        self.assertEqual(start["InitialMessage"]["ContentType"], "text/plain")
        self.assertEqual(start["ParticipantDetails"]["DisplayName"], "Ana | 18095550100")

    def test_development_flow_overrides_campaign_route(self):
        calls = []
        original_ddb, original_connect, original_participant = processor.ddb, processor.connect, processor.participant

        class Table:
            def get_item(self, **_kwargs):
                return {}

            def put_item(self, **_kwargs):
                pass

        class Connect:
            def start_chat_contact(self, **kwargs):
                calls.append(kwargs)
                return {"ContactId": "contact-dev", "ParticipantToken": "participant-token"}

            def start_contact_streaming(self, **_kwargs):
                pass

        class Participant:
            def create_participant_connection(self, **_kwargs):
                return {"ConnectionCredentials": {"ConnectionToken": "connection-token"}}

        os.environ.update({
            "CONNECT_INSTANCE_ID": "instance-1", "DEFAULT_CONTACT_FLOW_ID": "default-flow",
            "DEVELOPMENT_CONTACT_FLOW_ID": "dev-flow", "DEVELOPMENT_PHONE_NUMBERS": "15555550101",
            "OUTBOUND_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:outbound",
        })
        processor.ddb, processor.connect, processor.participant = Table(), Connect(), Participant()
        try:
            processor._session(
                {"id": "15555550101", "name": "Cliente", "phone": "15555550101", "user_id": "", "username": ""},
                "Hola", {"target_flow_id": "campaign-flow"}, "event-dev",
            )
        finally:
            processor.ddb, processor.connect, processor.participant = original_ddb, original_connect, original_participant
        self.assertEqual(calls[0]["ContactFlowId"], "dev-flow")
        self.assertEqual(calls[0]["Attributes"]["routing_rule"], "development_phone")

    def test_media_worker_processes_media_task(self):
        calls = []
        original_media, original_send, original_metric = processor._media, processor._send_connect, processor._metric
        processor._media = lambda message, session: "Transcripción lista"
        processor._send_connect = lambda session, text, _content_type="text/plain": calls.append((session, text))
        processor._metric = lambda *_a, **_k: None
        os.environ["WORKER_MODE"] = "media"
        try:
            processor._dispatch({"source": "media", "message": {"type": "audio"}, "session": {"contact_id": "c"}})
        finally:
            processor._media, processor._send_connect, processor._metric = original_media, original_send, original_metric
            os.environ["WORKER_MODE"] = "conversation"
        self.assertEqual(calls[0][1], "Transcripción lista")

    def test_agent_attachment_is_uploaded_and_sent_to_whatsapp(self):
        sent = []
        originals = (
            processor.ddb, processor.participant, processor._claim, processor._download_url,
            processor._upload_whatsapp_media, processor._send_whatsapp, processor._metric,
        )

        class Table:
            def query(self, **_kwargs):
                return {"Items": [{"participant_token": "pt", "identity_id": "15555550101", "phone": "15555550101"}]}

            def put_item(self, **_kwargs):
                pass

        class Participant:
            def create_participant_connection(self, **_kwargs):
                return {"ConnectionCredentials": {"ConnectionToken": "ct"}}

            def get_attachment(self, **_kwargs):
                return {"Url": "https://connect.test/attachment"}

        processor.ddb = Table()
        processor.participant = Participant()
        processor._claim = lambda _claim_id: True
        processor._download_url = lambda _url: b"png"
        processor._upload_whatsapp_media = lambda _blob, _content_type, _filename: "meta-media-id"
        processor._send_whatsapp = lambda identity, payload: sent.append((identity, payload)) or {"messages": []}
        processor._metric = lambda *_a, **_k: None
        try:
            processor._connect_event({"Message": {
                "Id": "event-attachment", "ContactId": "contact-1", "ParticipantRole": "AGENT",
                "Attachments": [{
                    "AttachmentId": "attachment-1", "AttachmentName": "cotización.png",
                    "ContentType": "image/png", "Status": "APPROVED",
                }],
            }})
        finally:
            (
                processor.ddb, processor.participant, processor._claim, processor._download_url,
                processor._upload_whatsapp_media, processor._send_whatsapp, processor._metric,
            ) = originals
        self.assertEqual(sent[0][0]["phone"], "15555550101")
        self.assertEqual(sent[0][1], {"type": "image", "image": {"id": "meta-media-id"}})

    def test_admin_send_accepts_public_to_field(self):
        sent = []
        original_claim, original_send = processor._claim, processor._send_whatsapp
        processor._claim = lambda _claim_id: True
        processor._send_whatsapp = lambda identity, payload: (sent.append((identity, payload)) or {"messages": [{"id": "wamid.test"}]})
        try:
            processor._admin_one({"to": "15555550100", "text": "prueba"}, "request-1")
        finally:
            processor._claim, processor._send_whatsapp = original_claim, original_send
        self.assertEqual(sent[0][0], {"id": "15555550100", "phone": "15555550100"})
        self.assertEqual(sent[0][1]["text"]["body"], "prueba")

    def test_template_dsl_parses_information_question_and_numbered_options(self):
        parsed = processor._parse_template_dsl("""
        [PLANTILLA]
        [Título] Visita de técnico
        [Información]
        Hola $.Attributes.nombre,

        La visita será mañana.
        [Pregunta] ¿Confirmas el horario?
        [Opción 1] Confirmar
        [opcion 2] Reprogramar
        """)
        self.assertEqual(parsed["title"], "Visita de técnico")
        self.assertIn("La visita será mañana.", parsed["information"])
        self.assertEqual(parsed["question"], "¿Confirmas el horario?")
        self.assertEqual(parsed["options"], ["Confirmar", "Reprogramar"])

    def test_template_dsl_builds_buttons_and_resolves_connect_attributes(self):
        payload, kind = processor._template_dsl_payload("""
        [plantilla]
        [titulo] Confirmación
        [informacion] Hola $.Attributes.nombre
        [pregunta] ¿Deseas continuar?
        [opcion] Sí
        [opcion] No
        """, {"customer_name": "Juan", "phone": "15555550101"})
        self.assertEqual(kind, "buttons")
        self.assertEqual(payload["interactive"]["header"]["text"], "Confirmación")
        self.assertEqual(payload["interactive"]["body"]["text"], "Hola Juan\n\n*¿Deseas continuar?*")
        self.assertEqual(
            [button["reply"]["title"] for button in payload["interactive"]["action"]["buttons"]],
            ["Sí", "No"],
        )

    def test_template_variables_do_not_treat_identity_id_as_phone(self):
        values = processor._template_values({
            "customer_name": "Ana",
            "identity_id": "bsuid-not-a-phone",
            "phone": "",
        })

        self.assertEqual(values["nombre"], "Ana")
        self.assertEqual(values["telefono"], "")
        self.assertEqual(values["customer_phone"], "")

    def test_template_dsl_converts_four_options_to_list(self):
        payload, kind = processor._template_dsl_payload("""
        [plantilla]
        [pregunta] Selecciona un área
        [opcion] Ventas
        [opcion] Compras
        [opcion] Cotizaciones
        [opcion] Soporte
        """, {"phone": "15555550101"})
        self.assertEqual(kind, "list")
        self.assertEqual(payload["interactive"]["type"], "list")
        self.assertEqual(len(payload["interactive"]["action"]["sections"][0]["rows"]), 4)

    def test_template_dsl_information_without_options_becomes_plain_text(self):
        payload, kind = processor._template_dsl_payload("""
        [plantilla]
        [titulo] Cita confirmada
        [informacion] Hola {nombre}, tu cita está confirmada.
        [pie] Empresa Ejemplo
        """, {"customer_name": "Juan", "phone": "15555550101"})
        self.assertEqual(kind, "information")
        self.assertEqual(
            payload["text"]["body"],
            "*Cita confirmada*\n\nHola Juan, tu cita está confirmada.\n\nEmpresa Ejemplo",
        )

    def test_template_dsl_question_has_exactly_one_bold_marker_pair(self):
        row = {"customer_name": "Juan", "phone": "15555550101"}
        plain, _ = processor._template_dsl_payload("""
        [plantilla]
        [pregunta] ¿Deseas confirmar la cita?
        [opcion] Sí
        [opcion] No
        """, row)
        already_bold, _ = processor._template_dsl_payload("""
        [plantilla]
        [pregunta] *¿Deseas confirmar la cita?*
        [opcion] Sí
        [opcion] No
        """, row)
        self.assertEqual(plain["interactive"]["body"]["text"], "*¿Deseas confirmar la cita?*")
        self.assertEqual(already_bold["interactive"]["body"]["text"], "*¿Deseas confirmar la cita?*")

    def test_template_dsl_interactive_footer_uses_native_footer_component(self):
        payload, _ = processor._template_dsl_payload("""
        [plantilla]
        [informacion] Tu cotización está disponible.
        [pregunta] ¿Deseas continuar?
        [opcion] Sí
        [opcion] No
        [pie] Empresa Ejemplo
        """, {"phone": "15555550101"})
        self.assertEqual(payload["interactive"]["footer"], {"text": "Empresa Ejemplo"})

    def test_template_dsl_is_enabled_only_for_allowlisted_phone(self):
        original_mode = os.environ.get("TEMPLATE_DSL_MODE")
        original_phones = os.environ.get("TEMPLATE_DSL_PHONE_NUMBERS")
        try:
            os.environ["TEMPLATE_DSL_MODE"] = "allowlist"
            os.environ["TEMPLATE_DSL_PHONE_NUMBERS"] = "15555550101"
            self.assertTrue(processor._template_dsl_enabled("+1 (555) 555-0101"))
            self.assertFalse(processor._template_dsl_enabled("15555550100"))
        finally:
            if original_mode is None:
                os.environ.pop("TEMPLATE_DSL_MODE", None)
            else:
                os.environ["TEMPLATE_DSL_MODE"] = original_mode
            if original_phones is None:
                os.environ.pop("TEMPLATE_DSL_PHONE_NUMBERS", None)
            else:
                os.environ["TEMPLATE_DSL_PHONE_NUMBERS"] = original_phones

    def test_connect_event_renders_dsl_only_for_test_phone(self):
        sent = []
        originals = processor.ddb, processor._send_whatsapp, processor._metric
        original_mode = os.environ.get("TEMPLATE_DSL_MODE")
        original_phones = os.environ.get("TEMPLATE_DSL_PHONE_NUMBERS")

        class Table:
            def query(self, **_kwargs):
                return {"Items": [{
                    "identity_id": "15555550101", "phone": "15555550101", "customer_name": "Juan"
                }]}

        processor.ddb = Table()
        processor._send_whatsapp = lambda identity, payload: sent.append((identity, payload)) or {"messages": []}
        processor._metric = lambda *_a, **_k: None
        os.environ["TEMPLATE_DSL_MODE"] = "allowlist"
        os.environ["TEMPLATE_DSL_PHONE_NUMBERS"] = "15555550101"
        try:
            processor._connect_event({"Message": {
                "Id": "dsl-1", "ContactId": "contact-1", "ParticipantRole": "SYSTEM",
                "Content": "[plantilla]\n[pregunta] Hola $.Attributes.nombre, elige\n[opcion] Ventas\n[opcion] Soporte",
            }})
        finally:
            processor.ddb, processor._send_whatsapp, processor._metric = originals
            if original_mode is None:
                os.environ.pop("TEMPLATE_DSL_MODE", None)
            else:
                os.environ["TEMPLATE_DSL_MODE"] = original_mode
            if original_phones is None:
                os.environ.pop("TEMPLATE_DSL_PHONE_NUMBERS", None)
            else:
                os.environ["TEMPLATE_DSL_PHONE_NUMBERS"] = original_phones
        self.assertEqual(sent[0][1]["type"], "interactive")
        self.assertEqual(sent[0][1]["interactive"]["body"]["text"], "*Hola Juan, elige*")

    def test_quote_document_uses_uploaded_s3_key(self):
        sent = []
        original_claim, original_send, original_s3 = processor._claim, processor._send_whatsapp, processor.s3
        old_media_bucket = os.environ.get("MEDIA_BUCKET")

        class S3:
            def generate_presigned_url(self, *_args, **_kwargs):
                return "https://example.test/quote.pdf"

        processor._claim = lambda _claim_id: True
        processor._send_whatsapp = lambda identity, payload: (sent.append((identity, payload)) or {"messages": []})
        processor.s3 = S3()
        os.environ["MEDIA_BUCKET"] = "test-bucket"
        try:
            processor._admin_one({
                "to": "15555550100",
                "media": {
                    "type": "document", "s3_key": "outbound/quote.pdf",
                    "filename": "quote.pdf", "caption": "Cotización de prueba",
                },
            }, "request-quote")
        finally:
            processor._claim, processor._send_whatsapp, processor.s3 = original_claim, original_send, original_s3
            if old_media_bucket is None:
                os.environ.pop("MEDIA_BUCKET", None)
            else:
                os.environ["MEDIA_BUCKET"] = old_media_bucket
        self.assertEqual(sent[0][1]["type"], "document")
        self.assertEqual(sent[0][1]["document"]["link"], "https://example.test/quote.pdf")
        self.assertEqual(sent[0][1]["document"]["filename"], "quote.pdf")


if __name__ == "__main__":
    unittest.main()
