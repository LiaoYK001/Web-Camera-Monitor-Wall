#!/usr/bin/env python3
"""Create the isolated MinIO fixture bucket using SigV4 without exposing secrets."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import pathlib
import ssl


BUCKET = "webobs-archive"
REGION = "us-east-1"


def signing_key(secret: str, date: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode(), date.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, REGION.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def signed_headers(method: str, uri: str, query: str, payload: bytes,
                   access_key: str, secret_key: str, host: str) -> dict[str, str]:
    timestamp = dt.datetime.now(dt.timezone.utc)
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
    short_date = timestamp.strftime("%Y%m%d")
    digest = hashlib.sha256(payload).hexdigest()
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{digest}\nx-amz-date:{amz_date}\n"
    signed = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([method, uri, query, canonical_headers, signed, digest])
    scope = f"{short_date}/{REGION}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])
    signature = hmac.new(signing_key(secret_key, short_date), string_to_sign.encode(),
                         hashlib.sha256).hexdigest()
    return {
        "Host": host, "Content-Length": str(len(payload)), "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": digest,
        "Authorization": (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                          f"SignedHeaders={signed}, Signature={signature}"),
    }


def main() -> None:
    credentials = json.loads(pathlib.Path("/run/secrets/minio-s3.json").read_text(encoding="utf-8"))
    access_key = credentials["accessKeyId"]
    secret_key = credentials["secretAccessKey"]
    host = "minio:9000"
    headers = signed_headers("PUT", f"/{BUCKET}", "", b"", access_key, secret_key, host)
    context = ssl.create_default_context(cafile="/run/secrets/cluster-ca.crt")
    connection = http.client.HTTPSConnection("minio", 9000, context=context, timeout=15)
    try:
        connection.request("PUT", f"/{BUCKET}", headers=headers)
        response = connection.getresponse()
        response.read(4096)
        if response.status not in {200, 204, 409}:
            raise SystemExit(f"MinIO fixture bucket creation failed with HTTP {response.status}")
    finally:
        connection.close()
    print("MinIO fixture bucket is ready.")


if __name__ == "__main__":
    main()
