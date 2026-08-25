# API v2 — local clients and True Direct / 本地客户端与真直连

> Development status / 开发状态：v2-M1 is complete on `dev`. API/Grant/Scene contracts, the isolated protocol fixture, exact Qt 6.11.2/GStreamer 1.28.6 RTSP/MJPEG/HLS/WHEP decoding, and 16-viewer True Direct coexistence with one unchanged NVR upstream pass. v2-M2 remains in release qualification until signed Windows/Fedora packages and private 16+1 thirty-minute hardware evidence pass / `dev` 上的 v2-M1 已完成：API/Grant/Scene 契约、隔离协议夹具、固定 Qt 6.11.2/GStreamer 1.28.6 的 RTSP/MJPEG/HLS/WHEP 解码，以及 16 个真直连观看端与一路不变 NVR 上游的共存门禁均通过。v2-M2 仍需 Windows/Fedora 签名包和私有 16+1 三十分钟硬件证据，故处于发布验收阶段。

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

An `auto` plan that visibly selects `gateway-direct`, `hybrid`, or `composite` must be explicitly activated before server media starts:

- `POST /api/v2/media-plans/{planId}/activate` creates an owned activation lease and returns only the same-origin WHEP alias `/api/v2/media-plans/{planId}/whep`.
- `GET /api/v2/media-plans/{planId}/activation` revalidates the device, Grant, plan ownership, expiry, and lease before every WHEP creation or deletion.
- `DELETE /api/v2/media-plans/{planId}/activation` is idempotent and tears down every WHEP session, on-demand MediaMTX route, and transcoder owned by that plan.

The native client authenticates this WHEP alias with an in-memory device bearer; the C++ boundary never returns an internal MediaMTX path. Forged IDs, cross-client access, invalid bearers, expired plans, released leases, and True Direct activation are rejected before a media route is created. Client revocation also closes all active fallback sessions immediately. If a fallback plan expires while disconnected or suspended, the reference client restores its original camera endpoint and performs a new bounded True Direct probe instead of retrying a stale server URL.

当 `auto` 计划明确选择 `gateway-direct`、`hybrid` 或 `composite` 时，客户端必须先显式激活，服务端才会启动媒体链：激活接口只返回同源 v2 WHEP 别名；查询接口会在每次创建/删除 WHEP 会话前重新校验设备、Grant、归属、期限与租约；删除激活是幂等的，并清理该计划的全部 WHEP 会话、按需 MediaMTX 路由及转码器。原生客户端仅在内存中携带 device bearer，内部 MediaMTX 路径不会暴露。伪造 ID、跨客户端访问、无效 bearer、过期计划、已释放租约及对真直连计划的激活都会在建路由前被拒绝；撤销客户端会立即关闭其所有后备会话。挂起或断线后若计划已过期，客户端会恢复原始摄像机端点并重新执行有界真直连探测，不会无限重试陈旧的服务端 URL。

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

`/config/webobs/shared-scenes-v2.json` is a wrapper with schema version 1 and at most 64 Scene v5 documents. The local subset accepts Camera, text, color, image and two-level nested Scene sources; stable IDs; bounded transforms/crop/grouping; and the standardized ordered filter records. LUT/mask paths are constrained to `/assets/` or `/recordings/`, scaling uses bounded `WIDTHxHEIGHT`, and nested references must exist, remain acyclic and stop at two levels. Raw URLs, endpoint/credential/secret/token fields, unknown fields and unsupported source kinds remain rejected. Local-only layouts serialize the same Scene v5 shape and do not create a second canvas schema.
