"""Grant the deployed Connect 3P application to selected security profiles.

The operation is additive: applications with other namespaces are preserved.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any


NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")


def merge_applications(current: list[dict[str, Any]], namespace: str) -> list[dict[str, Any]]:
    if not NAMESPACE_PATTERN.fullmatch(namespace):
        raise ValueError("Invalid application namespace")
    preserved = [item for item in current if str(item.get("Namespace") or "") != namespace]
    preserved.append(
        {
            "Namespace": namespace,
            "ApplicationPermissions": ["ACCESS"],
            "Type": "THIRD_PARTY_APPLICATION",
        }
    )
    return preserved


def configure(profile: str, region: str, instance_id: str, namespace: str,
              security_profile_ids: list[str]) -> list[str]:
    import boto3

    if not ID_PATTERN.fullmatch(instance_id):
        raise ValueError("Invalid Amazon Connect instance ID")
    unique_ids = list(dict.fromkeys(value.strip() for value in security_profile_ids if value.strip()))
    if not unique_ids or any(not ID_PATTERN.fullmatch(value) for value in unique_ids):
        raise ValueError("Every security profile ID must be a UUID")

    client = boto3.Session(profile_name=profile, region_name=region).client("connect")
    configured: list[str] = []
    for security_profile_id in unique_ids:
        applications: list[dict[str, Any]] = []
        request: dict[str, Any] = {
            "InstanceId": instance_id,
            "SecurityProfileId": security_profile_id,
            "MaxResults": 100,
        }
        while True:
            page = client.list_security_profile_applications(**request)
            applications.extend(page.get("Applications") or [])
            token = page.get("NextToken")
            if not token:
                break
            request["NextToken"] = token
        desired = merge_applications(applications, namespace)
        client.update_security_profile(
            InstanceId=instance_id,
            SecurityProfileId=security_profile_id,
            Applications=desired,
        )
        configured.append(security_profile_id)
    return configured


def main() -> int:
    from botocore.exceptions import ClientError

    parser = argparse.ArgumentParser(
        description="Grant a Connect third-party application to security profiles without removing other applications."
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--security-profile-ids", nargs="+", required=True)
    args = parser.parse_args()
    try:
        configured = configure(
            args.profile,
            args.region,
            args.instance_id,
            args.namespace,
            args.security_profile_ids,
        )
    except (ClientError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Amazon Connect application access configured for {len(configured)} security profile(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
