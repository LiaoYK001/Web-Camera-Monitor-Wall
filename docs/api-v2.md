# API v2 — local clients and True Direct / 本地客户端与真直连

> Development status / 开发状态：`v2-M1` implementation is in progress on `dev`. API contract, encrypted grants, topology planning, deterministic security tests and an isolated H.264 architecture fixture exist; the locked five-protocol receiver, NVR coexistence and hardware acceptance gate is not complete.

API v1 is unchanged: its `direct` value means Gateway Direct and Docker remains in the media path. API v2 adds device enrollment and a separately measured `true-direct` topology. All responses use bounded unique-field JSON, `Cache-Control: no-store` and credential-free errors.

API v1 保持不变：其中 `direct` 仍表示 Docker 位于媒体链中的网关直通。API v2 增加设备配对，并把 `true-direct` 作为独立测量的拓扑。所有响应均为有界 JSON、禁止缓存，错误不包含凭据。

## Authentication / 认证

- `POST /api/v2/enrollments` is public behind the configured Host/Origin boundary. It creates pending state only and is limited to 32 pending requests.
- `GET /api/v2/enrollments`, approval, client listing and revocation require the existing administrator Session/Basic boundary. The C++ proxy also adds an ephemeral 256-bit internal token; port 8094 rejects direct administrative requests. This prevents Browser Source loopback SSRF from bypassing the public control plane.
- Completion, bootstrap, media plans and audit use exactly one `Authorization: WebObs-Device <token>` header. The proxy forwards only its validated URL-safe token as an internal header. Device tokens are stored only as SHA-256 hashes.
- Native clients omit `Origin`; browser requests, when applicable, must use the configured same Origin. Remote control requires HTTPS.

## Enrollment / 配对

`POST /api/v2/enrollments`

```json
{
  "name": "Guard desk",
  "platform": "windows",
  "signingPublicKey": "<32-byte unpadded base64url>",
  "encryptionPublicKey": "<32-byte unpadded base64url>",
  "enrollmentNonce": "<32-byte unpadded base64url>",
  "signature": "<Ed25519 signature>"
}
```

The signature covers deterministic CBOR containing purpose `webobs-client-enrollment-v1` and the exact normalized fields. A nonce can never be reused. The response contains an opaque enrollment ID, a ten-minute eight-digit pairing code, a one-time device token and expiry. SQLite stores only a random-salt scrypt digest of the pairing code and a SHA-256 digest of the device token; neither bearer value is recoverable from the database.

签名覆盖包含 `webobs-client-enrollment-v1` purpose 及精确规范化字段的确定性 CBOR，nonce 不可重复使用。响应包含不透明 enrollment ID、十分钟有效的八位配对码、一次性设备令牌及过期时间。SQLite 只保存带随机盐的配对码 scrypt 摘要与设备令牌 SHA-256 摘要，无法从数据库恢复这两个 bearer 值。

`POST /api/v2/enrollments/{id}/approve` (administrator)

```json
{
  "pairingCode": "12345678",
  "cameraGrants": [{
    "cameraId": "front-door",
    "profileIds": ["sub"],
    "permissions": ["view", "snapshot", "record-local"],
    "credentialMode": "existing"
  }]
}
```

Permissions are `view`, `ptz`, `talk`, `snapshot`, and `record-local`; `view` is mandatory. `dedicated` mode also requires a `credentialsRef` different from the Registry credential reference. The service verifies the referenced secret exists before approval. It does not create a camera account automatically; an administrator or later ONVIF user-management integration must provision it first.

`POST /api/v2/enrollments/{id}/complete` returns `202` while pending, then an identity summary plus the first `grantBundle`. The Grant payload is deterministic CBOR, signed by the server Ed25519 key and sealed to the client X25519 key. It contains only granted endpoints, profiles, permissions and credentials. The outer bootstrap/Scene documents never contain endpoints or credentials.

## Bootstrap and revocation / 启动与撤销

`GET /api/v2/client/bootstrap?sinceRevision=<n>` returns the current global revision, redacted Registry metadata, Scene v5 shared-local subset, sync policy, a renewed sealed Grant and a ten-second online validation interval. The global bootstrap cursor is distinct from the per-client Grant revision. The reference client persists the cursor and last validated shared Scene inside its OS-protected encrypted identity cache so a new pairing receives the first Scene and offline startup can restore it. Successful authenticated access slides the 30-day offline expiry.

`GET /api/v2/clients` lists at most 256 clients and reports `cameraCount` and `weakRevocation`. `DELETE /api/v2/clients/{id}` immediately revokes online API access, deletes active plans and returns `offlineEffectiveNoLaterThan`. A disconnected client cannot learn revocation before the already issued Grant expires; the UI always displays this boundary.

## Media plans / 媒体规划

`POST /api/v2/media-plans` accepts one granted Camera/Profile plus client evidence:

```json
{
  "cameraId": "front-door",
  "profileId": "sub",
  "policy": "auto",
  "receiverKind": "native",
  "networkClass": "lan",
  "reachability": "reachable",
  "protocols": ["rtsp"],
  "videoCodecs": ["h264"],
  "hardwareDecoders": ["d3d11"],
  "requiresComposite": false
}
```

The reference client submits `reachability=reachable` only after receiving a decoded video buffer within three seconds. This is client evidence, not remote attestation; the server still validates the granted Profile and declared capability set. A plan never starts the server media graph by itself—it only records the selected contract. `true-direct-only` returns `409` instead of silently falling back. `GET /api/v2/media-plans/{planId}` retrieves the five-minute plan owned by that client.

Every `TopologyPlan` contains:

```text
contractVersion, planId, cameraId, profileId, status
topology = true-direct | gateway-direct | hybrid | composite
receiverKind = native | browser
archiveTopology = off | server-copy | server-transcode | local-manual
decoder, renderer, encoder, upstreamOwner
liveServerMediaExpected, fallbackReason, expiresAt
```

Live and archive are independent. An NVR `server-copy` plan may coexist with True Direct, but adding viewers must not create another Docker Camera/MediaMTX/FFmpeg/libobs upstream.

## Offline audit / 离线审计

`POST /api/v2/client/audit/batch` accepts at most 128 events per call and stores at most 8192 global recent rows. Events have exactly `sequence`, `type`, `outcome`, `cameraId`, and `createdAt`; duplicates are idempotent. Free text, endpoints, client addresses and credentials are not accepted.

## Shared Scene boundary / 共享场景边界

`/config/webobs/shared-scenes-v2.json` is a wrapper with schema version 1 and at most 64 Scene v5 documents. The current M1 local subset accepts Camera, text, color and `/assets/` image sources, stable IDs and basic transforms. It rejects raw URLs, endpoint/credential/secret/token fields, unknown fields, non-empty filters and unsupported blend behavior rather than silently changing scene semantics. Local-only layouts serialize the same Scene v5 shape and do not create a second canvas schema.
