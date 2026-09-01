#!/usr/bin/env python3
"""Create ephemeral RBAC principals for the private Windows browser gate."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import secrets
import ssl
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1] / ".m7-cluster"
BASE = os.environ.get("WEBOBS_M7_CONTROL_URL", "https://127.0.0.1:18443")
ORIGIN = BASE.rstrip("/")
TLS_CONTEXT = ssl.create_default_context(cafile=str(ROOT / "secrets/cluster-ca.crt"))


def administrator_request(path: str, value: dict) -> dict:
    username = (ROOT / "secrets/admin-user").read_text(encoding="utf-8")
    password = (ROOT / "secrets/admin-password").read_text(encoding="utf-8")
    authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    payload = json.dumps(value, separators=(",", ":")).encode()
    request = urllib.request.Request(BASE + path, data=payload, method="POST", headers={
        "Authorization": authorization, "Origin": ORIGIN, "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=15, context=TLS_CONTEXT) as response:
        return json.load(response)


def main() -> None:
    definitions = {
        "admin": ("admin", []),
        "operator": ("operator", [{"kind": "camera", "id": "fixture-01"}]),
        "viewerGroup": ("viewer", [{"kind": "group", "id": "fixture-zone-a"}]),
        "viewerCamera": ("viewer", [{"kind": "camera", "id": "fixture-02"}]),
        "auditor": ("auditor", [{"kind": "camera", "id": "fixture-01"}]),
        "exporter": ("exporter", [{"kind": "camera", "id": "fixture-01"}]),
    }
    users: dict[str, dict[str, str]] = {}
    nonce = secrets.token_hex(4)
    for key, (role, scopes) in definitions.items():
        username = f"gate-{key.lower()}-{nonce}"
        password = secrets.token_urlsafe(24)
        created = administrator_request("/api/v2/users", {
            "username": username, "password": password, "roles": [role], "scopes": scopes,
        })
        users[key] = {"id": created["id"], "username": username, "password": password,
                      "revision": str(created["revision"])}
    target = ROOT / "secrets/windows-admin-users.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(users, separators=(",", ":"), sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    print("Prepared ephemeral principals for the Windows v2-M7 browser gate.")


if __name__ == "__main__":
    main()
