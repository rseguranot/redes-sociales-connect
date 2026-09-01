import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def normalize_extensions(values: list[str]) -> list[str]:
    extensions = []
    for value in values:
        extension = value.strip().lower().lstrip(".")
        if not re.fullmatch(r"[a-z0-9_-]{1,10}", extension):
            raise ValueError(f"Invalid attachment extension: {value}")
        if extension not in extensions:
            extensions.append(extension)
    return extensions


def merge_extensions(current: list[dict], requested: list[str]) -> list[dict]:
    values = {
        str(item.get("Extension") or "").strip().lower().lstrip(".")
        for item in current
        if item.get("Extension")
    }
    values.update(normalize_extensions(requested))
    return [{"Extension": value} for value in sorted(values)]


def _signed_json(session: Any, method: str, url: str, payload: dict | None = None) -> dict:
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
    request = AWSRequest(
        method=method,
        url=url,
        data=body,
        headers={"content-type": "application/json"} if body is not None else {},
    )
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials are unavailable")
    SigV4Auth(credentials.get_frozen_credentials(), "connect", session.region_name).add_auth(request)
    prepared = request.prepare()
    http_request = urllib.request.Request(
        prepared.url,
        data=body,
        method=method,
        headers=dict(prepared.headers.items()),
    )
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise RuntimeError(f"Amazon Connect returned HTTP {exc.code}: {detail}") from exc


def _describe(session: Any, client: Any, instance_id: str, scope: str) -> dict:
    if hasattr(client, "describe_attached_files_configuration"):
        response = client.describe_attached_files_configuration(
            InstanceId=instance_id,
            AttachmentScope=scope,
        )
    else:
        base_url = client.meta.endpoint_url.rstrip("/")
        path = f"/attached-files-configurations/{urllib.parse.quote(instance_id)}/{scope}"
        response = _signed_json(session, "GET", base_url + path)
    return response["AttachedFilesConfiguration"]


def configure(profile: str, region: str, instance_id: str, requested: list[str]) -> dict:
    import boto3

    session = boto3.Session(profile_name=profile, region_name=region)
    client = session.client("connect")
    scope = "CHAT"
    current = _describe(session, client, instance_id, scope)
    allowed = merge_extensions(
        (current.get("ExtensionConfiguration") or {}).get("AllowedExtensions") or [],
        requested,
    )
    update = {"ExtensionConfiguration": {"AllowedExtensions": allowed}}
    if hasattr(client, "update_attached_files_configuration"):
        client.update_attached_files_configuration(
            InstanceId=instance_id,
            AttachmentScope=scope,
            **update,
        )
    else:
        base_url = client.meta.endpoint_url.rstrip("/")
        path = f"/attached-files-configurations/{urllib.parse.quote(instance_id)}/{scope}"
        _signed_json(session, "POST", base_url + path, update)
    return _describe(session, client, instance_id, scope)


def main() -> int:
    from botocore.exceptions import ClientError

    parser = argparse.ArgumentParser(description="Allow additional file extensions in Amazon Connect chat.")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--extensions", nargs="+", required=True)
    args = parser.parse_args()
    try:
        result = configure(args.profile, args.region, args.instance_id, args.extensions)
    except (ClientError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    allowed = (result.get("ExtensionConfiguration") or {}).get("AllowedExtensions") or []
    print("Amazon Connect chat extensions: " + ", ".join(item["Extension"] for item in allowed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
