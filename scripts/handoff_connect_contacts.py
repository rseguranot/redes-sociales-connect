#!/usr/bin/env python3
"""Reabre en Connect destino contactos recientes de otra instancia y avisa por Meta.

El modo predeterminado es dry-run. No imprime atributos, teléfonos ni identificadores
de clientes. Sólo procesa contactos CHAT con ``social_phone`` explícito.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--source-instance-id", required=True)
    parser.add_argument("--start-contact-id", required=True)
    parser.add_argument("--destination-instance-id", required=True)
    parser.add_argument("--destination-flow-id", required=True)
    parser.add_argument("--destination-topic-arn", required=True)
    parser.add_argument("--destination-table", required=True)
    parser.add_argument("--destination-secret-id", required=True)
    parser.add_argument("--notice", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--retry-skipped-active", action="store_true")
    return parser.parse_args()


def _contacts(connect, instance_id: str, start: datetime, end: datetime) -> list[dict]:
    request = {
        "InstanceId": instance_id,
        "TimeRange": {"Type": "INITIATION_TIMESTAMP", "StartTime": start, "EndTime": end},
        "SearchCriteria": {"Channels": ["CHAT"]},
        "MaxResults": 100,
    }
    found: list[dict] = []
    while True:
        page = connect.search_contacts(**request)
        found.extend(page.get("Contacts", []))
        token = page.get("NextToken")
        if not token:
            return found
        request["NextToken"] = token


def _identity(attributes: dict[str, str]) -> dict[str, str] | None:
    phone = str(attributes.get("social_phone") or "").strip()
    if not PHONE_RE.fullmatch(phone):
        return None
    phone = re.sub(r"\D", "", phone)
    user_id = str(attributes.get("social_user_id") or "").strip()
    return {
        "id": user_id or phone,
        "phone": phone,
        "user_id": user_id,
        "username": str(attributes.get("social_username") or "").strip(),
        "name": str(attributes.get("social_display_name") or "").strip() or phone,
        "channel": str(attributes.get("social_channel") or "whatsapp").strip(),
    }


def _send_meta(secret: dict[str, str], phone: str, notice: str) -> str:
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": False, "body": notice},
    }).encode()
    request = urllib.request.Request(
        f"https://graph.facebook.com/v26.0/{secret['WA_PHONE_NUMBER_ID']}/messages",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {secret['WA_ACCESS_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read())
    return str((result.get("messages") or [{}])[0].get("id") or "")


def main() -> int:
    args = _args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    source = session.client("connect")
    destination = session.client("connect")
    participant = session.client("connectparticipant")
    ddb = session.resource("dynamodb").Table(args.destination_table)
    first = source.describe_contact(InstanceId=args.source_instance_id, ContactId=args.start_contact_id)["Contact"]
    start = first["InitiationTimestamp"]
    end = datetime.now(timezone.utc)
    if end - start > timedelta(hours=24):
        raise RuntimeError("El rango empieza fuera de la ventana de atención de 24 horas")

    candidates: dict[str, dict] = {}
    for contact in _contacts(source, args.source_instance_id, start, end):
        attrs = source.get_contact_attributes(
            InstanceId=args.source_instance_id, InitialContactId=contact["Id"]
        ).get("Attributes", {})
        identity = _identity(attrs)
        if identity:
            candidates[identity["phone"]] = {"source_contact_id": contact["Id"], "identity": identity}

    print(json.dumps({"mode": "execute" if args.execute else "dry-run", "eligible_unique_contacts": len(candidates)}))
    if not args.execute:
        return 0

    secret = json.loads(session.client("secretsmanager").get_secret_value(
        SecretId=args.destination_secret_id
    )["SecretString"])
    counts = {"created": 0, "already_processed": 0, "already_active": 0, "failed": 0}
    now = int(time.time())
    for candidate in candidates.values():
        source_id = candidate["source_contact_id"]
        identity = candidate["identity"]
        audit_key = {"pk": f"HANDOFF#{source_id}", "sk": "DEV_TO_PROD"}
        try:
            ddb.put_item(
                Item={**audit_key, "status": "CLAIMED", "created_at": now, "ttl": now + 30 * 86400},
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                previous = ddb.get_item(Key=audit_key, ConsistentRead=True).get("Item", {})
                if not args.retry_skipped_active or previous.get("status") != "SKIPPED_ACTIVE":
                    counts["already_processed"] += 1
                    continue
            else:
                raise

        session_key = {"pk": f"IDENTITY#{identity['id']}", "sk": "SESSION"}
        current = ddb.get_item(Key=session_key, ConsistentRead=True).get("Item")
        if current and int(current.get("expires_at", 0)) > now:
            actually_active = False
            try:
                described = destination.describe_contact(
                    InstanceId=args.destination_instance_id,
                    ContactId=current["contact_id"],
                )["Contact"]
                actually_active = not described.get("DisconnectTimestamp")
            except ClientError:
                pass
            if actually_active:
                if args.retry_skipped_active:
                    meta_id = _send_meta(secret, identity["phone"], args.notice)
                    ddb.update_item(
                        Key=audit_key,
                        UpdateExpression="SET #s=:s, meta_message_id=:m, completed_at=:u",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":s": "COMPLETED_EXISTING", ":m": meta_id, ":u": int(time.time())},
                    )
                    counts["created"] += 1
                else:
                    counts["already_active"] += 1
                    ddb.update_item(Key=audit_key, UpdateExpression="SET #s=:s", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": "SKIPPED_ACTIVE"})
                continue

        started = None
        try:
            attributes = {
                "initial_message": args.notice,
                "social_channel": identity["channel"],
                "social_user_id": identity["id"],
                "social_display_name": identity["name"],
                "social_phone": identity["phone"],
                "social_username": identity["username"],
                "handoff_reason": "meta_callback_recovery",
            }
            started = destination.start_chat_contact(
                InstanceId=args.destination_instance_id,
                ContactFlowId=args.destination_flow_id,
                ParticipantDetails={"DisplayName": identity["name"][:256]},
                Attributes={k: v for k, v in attributes.items() if v},
                SupportedMessagingContentTypes=["text/plain", "text/markdown", "application/vnd.amazonaws.connect.message.interactive"],
                ClientToken=hashlib.sha256(f"handoff:{source_id}".encode()).hexdigest(),
            )
            destination.start_contact_streaming(
                InstanceId=args.destination_instance_id,
                ContactId=started["ContactId"],
                ChatStreamingConfiguration={"StreamingEndpointArn": args.destination_topic_arn},
                ClientToken=hashlib.sha256(f"stream:{source_id}".encode()).hexdigest(),
            )
            participant.create_participant_connection(
                Type=["CONNECTION_CREDENTIALS"],
                ParticipantToken=started["ParticipantToken"],
                ConnectParticipant=True,
            )
            expires_at = now + 86400
            ddb.put_item(Item={
                **session_key,
                "contact_id": started["ContactId"],
                "participant_token": started["ParticipantToken"],
                "identity_id": identity["id"],
                "phone": identity["phone"],
                "user_id": identity["user_id"],
                "username": identity["username"],
                "customer_name": identity["name"],
                "gsi1pk": f"CONTACT#{started['ContactId']}",
                "gsi1sk": "SESSION",
                "expires_at": expires_at,
                "ttl": expires_at + 7 * 86400,
            })
            meta_id = _send_meta(secret, identity["phone"], args.notice)
            ddb.update_item(
                Key=audit_key,
                UpdateExpression="SET #s=:s, destination_contact_id=:c, meta_message_id=:m, completed_at=:u",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "COMPLETED", ":c": started["ContactId"], ":m": meta_id, ":u": int(time.time())},
            )
            counts["created"] += 1
        except Exception:
            counts["failed"] += 1
            ddb.update_item(Key=audit_key, UpdateExpression="SET #s=:s, failed_at=:u", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": "FAILED", ":u": int(time.time())})
            if started:
                try:
                    destination.stop_contact(InstanceId=args.destination_instance_id, ContactId=started["ContactId"])
                except Exception:
                    pass
    print(json.dumps(counts, sort_keys=True))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
