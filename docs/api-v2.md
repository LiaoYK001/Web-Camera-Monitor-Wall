# API v2 — local clients and True Direct / 本地客户端与真直连

> Stable status / 稳定状态：v2-M1 through v2-M3 shipped in `v2.0.1`; v2-M4/M5 ship in `v2.1`. Native package qualification remains frozen / v2-M1 至 v2-M3 已随 `v2.0.1` 发布；v2-M4/M5 随 `v2.1` 发布，原生包验收仍冻结。

The v2-M6 operations contracts shipped in `v2.2`. `dev` now adds the v2-M7 RBAC, node, storage, placement, archive, backup and Provider contracts; they are not stable-release claims until the v2.3 gates and immutable Tag pass / v2-M6 运维契约已随 `v2.2` 发布；`dev` 当前增加 v2-M7 的 RBAC、节点、存储、分配、归档、备份与 Provider 契约，在 v2.3 门禁和不可移动 Tag 通过前不构成稳定版声明。

API v1 is unchanged: its `direct` value means Gateway Direct and Docker remains in the media path. API v2 adds device enrollment and a separately measured `true-direct` topology. All responses use bounded unique-field JSON, `Cache-Control: no-store` and credential-free errors.

API v1 保持不变：其中 `direct` 仍表示 Docker 位于媒体链中的网关直通。API v2 增加设备配对，并把 `true-direct` 作为独立测量的拓扑。所有响应均为有界 JSON、禁止缓存，错误不包含凭据。

## v2-M7 管理与集群接口（dev）

下列公共接口继续位于既有 Session/RBAC/Origin 边界内。修改操作使用 `If-Match` revision；服务端不会把 Secret、节点私钥、主机路径或完整媒体端点返回给浏览器：

```text
GET/POST/PATCH /api/v2/users
GET              /api/v2/roles
GET/DELETE       /api/v2/nodes/{id?}
POST             /api/v2/node-enrollments
POST             /api/v2/node-enrollments/{id}/approve
GET/PATCH        /api/v2/storage-volumes/{nodeId?}/{volumeId?}
GET/POST         /api/v2/recording-placements
GET              /api/v2/recordings
GET              /api/v2/recordings/timeline
GET              /api/v2/resource-capacity
GET/POST         /api/v2/archive-targets
GET/POST         /api/v2/backup-jobs
GET/POST         /api/v2/providers
POST             /api/v2/providers/{id}/tasks
```

角色权限与 Camera/Group scope 默认拒绝。Enrollment token 有效十分钟且只保存摘要；节点证书有效 30 天。`storage-volumes` 只能管理已经挂载并由节点报告的 `volumeId`，不接受主机路径。`recordings` 与 `recordings/timeline` 只返回稳定 Camera/Profile/Segment/Node/Volume ID、UTC 时间、编码、完整性、锁定和归档状态；不返回 `storageKey`、主机路径、S3 object key 或媒体端点。查询范围最多 31 天，单次目录响应最多 256 个位置；非管理员必须提供一个获授权的 `cameraId`，多 Camera 查询需逐路执行，避免用首个参数绕过 scope。Provider 任务只返回最长 60 秒、单次可消费的媒体授权，`credentialExposure` 固定为 `none`。当任务引用录像时，`segmentId` 必须存在于 Controller Catalog，并且必须同时匹配获批的 `cameraId/profileId`；实际下载仅代理该只读 NVR 片段，不接受任意路径。旧 Catalog 行在 Recorder 重新对账补齐 Camera/Profile 绑定前保持拒绝访问。

Controller 与 Recorder/Worker 之间的 `/internal/v1` 只在 TLS 1.3 mTLS 私网端口提供：

```text
POST /internal/v1/nodes/enroll
POST /internal/v1/nodes/enroll/complete
POST /internal/v1/nodes/heartbeat
POST /internal/v1/nodes/certificate/renew
GET  /internal/v1/assignments
POST /internal/v1/leases/renew
POST /internal/v1/catalog/batch
```

除两个一次性 Enrollment 请求外，每个请求都必须携带恰好一个已验证的 `webobs-node:<id>` URI SAN，且 `X-WebObs-Node-Id` 只能与该 SAN 相同。心跳、租约、generation fence、120 秒隔离窗口和 5 秒时钟偏差边界详见 [v2.3 扩展、生态与韧性](scale-ecosystem-resilience-v2.3.md)。

## Authentication / 认证

- `POST /api/v2/enrollments` is public behind the configured Host/Origin boundary. It creates pending state only and is limited to 32 pending requests.
- `GET /api/v2/enrollments`, approval, client listing and revocation require the existing administrator Session/Basic boundary. The C++ proxy also adds an ephemeral 256-bit internal token; port 8094 rejects direct administrative requests. This prevents Browser Source loopback SSRF from bypassing the public control plane.
- Completion, bootstrap, media plans and audit use exactly one `X-WebObs-Device-Token` header. The proxy validates its URL-safe form and forwards only that value. Device tokens are stored only as SHA-256 hashes.
- Native clients omit `Origin`; browser requests, when applicable, must use the configured same Origin. Remote control requires HTTPS.

## Enrollment / 配对

`POST /api/v2/enrollments`

```json
{
  "name": "Guard desk",
  "platform": "web",
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
    "credentialMode": "none"
  }]
}
```

Permissions are `view`, `ptz`, `talk`, `snapshot`, and `record-local`; `view` is mandatory. `web` and `chromium-iwa` enrollments must use `credentialMode=none`; their grants never contain camera credentials. Frozen native platforms retain `existing|dedicated`: dedicated mode requires verified ONVIF user management and a distinct Secret reference.

`POST /api/v2/enrollments/{id}/complete` returns `202` while pending, then an identity summary plus the first `grantBundle`. The payload is deterministic CBOR, signed by the server Ed25519 key and sealed to the client X25519 key. Browser format `webobs-browser-grant-v1` contains only granted Camera/Profile metadata, non-secret eligible endpoints and permissions; it never contains `credentials`. Outer bootstrap/Scene documents never contain endpoints or credentials.

## Bootstrap and revocation / 启动与撤销

`GET /api/v2/client/bootstrap?sinceRevision=<n>` returns the current global revision, redacted Registry metadata, Scene v5 shared-local subset, sync policy, a renewed sealed Grant and a five-second online validation interval. Successful authenticated access slides browser/IWA authorization by seven days; frozen native contracts retain 30 days. The PWA encrypts the cursor, Grant and redacted Scene snapshot in IndexedDB with a non-extractable AES-GCM wrapping key.

For contract-v2 browser clients, bootstrap also returns `sync.resetRequired`, `sync.documents`, and ordered `sync.changes`. A zero cursor or a cursor older than the bounded 4096-change journal receives a full safe snapshot. `syncPolicy=bidirectional-field-conflict-v1`; physical addresses, media endpoints, credential references and bearer values are never sync documents.

对于 contract-v2 浏览器客户端，bootstrap 还返回 `sync.resetRequired`、`sync.documents` 与有序 `sync.changes`。游标为零或早于 4096 条有界变更日志时返回完整安全快照。同步策略固定为 `bidirectional-field-conflict-v1`；物理地址、媒体端点、凭据引用和 bearer 值永远不是同步文档。

`POST /api/v2/client/sync` accepts schema-v1 batches with one base revision and at most 64 mutations. Supported document kinds are:

- `scene`: the safe Camera/text/color/nested Scene v5 subset, addressed by stable Scene ID; fields are `name`, `canvas`, `sources`, and `items`.
- `camera-preference`: a non-secret display overlay with `displayName`, `favorite`, and `group`, addressed by an already granted Camera ID.

Each mutation is `upsert` or `delete`. The service validates the complete resulting document, client Camera/Profile scope, nested Scene graph, bounds and secret-free representation inside one SQLite transaction. A field changed after `baseRevision` returns `409` with only that field's safe server value and revision; unrelated stale fields can still commit. Deletes create tombstones, and retries with identical values are idempotent. The PWA retains conflicting encrypted mutations until the operator chooses “采用服务端” or rebases them with “保留本地”.

`POST /api/v2/client/sync` 接收 schema-v1、携带一个基础 revision、最多 64 个 mutation 的批次。`scene` 只允许安全的 Camera/文字/纯色/嵌套 Scene v5 子集；`camera-preference` 只允许已授权 Camera ID 的显示名称、收藏与分组。服务在同一 SQLite 事务中校验完整结果、授权范围、嵌套图、边界和脱敏表示。基础 revision 之后被修改的字段返回 `409`，互不相关的旧字段仍可提交；删除使用墓碑，等值重试保持幂等。PWA 在操作员选择采用服务端或保留本地前，会继续以密文保留冲突 mutation。

`GET /api/v2/clients` lists at most 256 clients and reports `cameraCount` and `weakRevocation`. `DELETE /api/v2/clients/{id}` immediately revokes online API access, deletes active plans, removes managed ONVIF dedicated accounts in a bounded parallel cleanup, and returns `offlineEffectiveNoLaterThan`, `weakRevocation`, and `cameraCredentialCleanup`. If any camera is unreachable or refuses account removal, that Grant is atomically changed to weak revocation and the UI requires camera-password rotation. A disconnected client cannot learn server-token revocation before the already issued Grant expires; the UI always displays this boundary.

## Media plans / 媒体规划

`POST /api/v2/media-plans` accepts one granted Camera/Profile plus client evidence:

```json
{
  "cameraId": "front-door",
  "profileId": "sub",
  "policy": "auto",
  "receiverKind": "browser",
  "networkClass": "lan",
  "reachability": "reachable",
  "protocols": ["whep", "hls", "mjpeg"],
  "videoCodecs": ["h264"],
  "hardwareDecoders": ["webcodecs"],
  "requiresComposite": false
}
```

The reference client submits `reachability=reachable` only after receiving a decoded video buffer within three seconds. This is client evidence, not remote attestation; the server still validates the granted Profile and declared capability set. For browser runtimes, an administrator first calls `POST /api/v1/cameras/{cameraId}/profiles/{profileId}/browser-direct/probe`; the bounded Registry probe verifies TLS, exact-origin CORS and a protocol-specific media response, binds proof to `WEBOBS_PWA_PUBLIC_ORIGIN`, and expires it after 24 hours. Reserved `browserDirect` fields from submitted Camera JSON are ignored. A plan never starts the server media graph by itself—it only records the selected contract. `true-direct-only` returns `409` instead of silently falling back. `GET /api/v2/media-plans/{planId}` retrieves the five-minute plan owned by that client.

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
runtimeKind = pwa | chromium-iwa
executionOwner = browser | docker
mediaTransport = whep | hls | mjpeg | rtsp
credentialExposure = none | ephemeral
offlineConfigExpiresAt
```

Live and archive are independent. An NVR `server-copy` plan may coexist with True Direct, but adding viewers must not create another Docker Camera/MediaMTX/FFmpeg/libobs upstream.

## Offline audit / 离线审计

`POST /api/v2/client/audit/batch` accepts at most 128 events per call and stores at most 8192 global recent rows. Events have exactly `sequence`, `type`, `outcome`, `cameraId`, and `createdAt`; duplicates are idempotent. Free text, endpoints, client addresses and credentials are not accepted.

The PWA keeps at most 512 encrypted offline events and reconciles them in batches of 128. Revocation, Grant expiry, or logout atomically clears the audit queue together with identity, private snapshots, sync cursor and pending mutations; the static application shell remains cached.

## Operations workspace / 运维工作区

Camera Registry schema v2 keeps `Camera → Profile → Track` as the only source hierarchy. Public catalog documents expose stable IDs and sanitized display addresses; credentials, query secrets and private endpoints are never returned by the catalog API.

```text
GET   /api/v2/source-catalog
GET   /api/v2/source-catalog/{cameraId}
PATCH /api/v2/source-catalog/{cameraId}                  If-Match required
POST  /api/v2/source-catalog/batch                       1..256 atomic patches
POST  /api/v2/source-catalog/{cameraId}/probe             all Profiles, bounded
POST  /api/v2/source-catalog/{cameraId}/profiles/{profileId}/probe
GET   /api/v2/operations/issues
POST  /api/v2/operations/issues/{issueId}/acknowledge
GET   /api/v2/audio/mixer?sceneId=<id>&topology=direct|composite
PATCH /api/v2/scenes/{sceneId}/audio/sources/{sourceId} If-Match required
GET   /api/v2/settings
GET   /api/v2/settings/schema
PATCH /api/v2/settings                                  If-Match required
```

Catalog PATCH fields are bounded to device name/kind/enabled/group/tags/hardware decode and Profile enabled/transport/bitrate-cap/audio-expectation/`allowInsecureHttp`. A stale revision returns a conflict without a partial write. Plain HTTP media resolution and probing fail until the operator enables this per-Profile exception; the exception is never included in browser Grants and never relaxes HTTPS True Direct qualification. Disabling a device rejects new resolution immediately and closes its owned Gateway/Hybrid sessions at the C++ boundary. Probe concurrency is one per Camera and four globally, defaults to ten seconds, caps combined output at 1 MiB and records only allowlisted diagnostic fields.

`OperationalIssue` is deduplicated by code, scope and component, bounded by the runtime retention policy, and never stores an endpoint, command line, raw response, PID, path or client address. `AUDIO_TRACK_MISSING` is created only when `audioExpectation=required`.

Direct meters are produced locally by per-source Web Audio analysers. Composite polling lazily attaches libobs `obs_volmeter` objects and returns real RMS/Peak values in `-120..0 dBFS`; inactive meters detach after two seconds. Missing or inaccessible audio is `null`/`—`, never synthetic. Audio PATCH accepts only `muted`, `volume`, `monitoring`, `syncOffsetMs` and `audioTrack`, updates the shared Scene v5 value atomically and applies a changed Program source through libobs.

`/api/v1/ws` clients may ignore the new `source.catalog.updated`, `source.status`, `operations.issue`, `operations.issue.resolved`, and `audio.meters` event types. Meter events contain only a timestamp, topology, stable source IDs and dBFS values; no audio sample, address or endpoint is included. The PWA continues to use bounded polling as a reconnect-safe fallback.

## Shared Scene boundary / 共享场景边界

`/config/webobs/shared-scenes-v2.json` is a wrapper with schema version 1 and at most 64 Scene v5 documents. The local subset accepts Camera, text, color, image and two-level nested Scene sources; stable IDs; bounded transforms/crop/grouping; and the standardized ordered filter records. LUT/mask paths are constrained to `/assets/` or `/recordings/`, scaling uses bounded `WIDTHxHEIGHT`, and nested references must exist, remain acyclic and stop at two levels. Raw URLs, endpoint/credential/secret/token fields, unknown fields and unsupported source kinds remain rejected. Local-only layouts serialize the same Scene v5 shape and do not create a second canvas schema.
