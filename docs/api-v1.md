# Control API v1 / 控制接口 v1

v1-M1 through v1-M11 provide the control, Studio, WebRTC, NVR, evidence, device-operation and event planes. v1-M10 adds Camera Registry and guarded ONVIF operations; v1-M11 adds normalized events, motion zones, detector providers, rules and a bounded notification outbox. The current composition contract is [scene-schema-v5.md](scene-schema-v5.md).

v1-M1 至 v1-M11 提供控制、Studio、WebRTC、NVR、证据、设备运维与事件平面；v1-M10 增加 Camera Registry 和受控 ONVIF 操作，v1-M11 增加统一事件、移动区域、检测提供器、规则与有界通知发件箱。当前合成契约见 [scene-schema-v5.md](scene-schema-v5.md)。

## Security boundary / 安全边界

Authentication remains disabled by default for loopback development. When credential files are configured, `/` and hashed static assets remain public so the application can render its login page without a browser Basic challenge. REST, WebSocket, Program/Source WHEP and metrics require either a valid HttpOnly session or explicit Basic credentials. Liveness and readiness remain public. This is still a single-operator boundary, not role-based authorization.

认证默认关闭并只用于回环开发。配置凭据后，登录页和哈希静态资源保持公开，浏览器不会弹出 Basic 对话框；REST、WebSocket、Program/Source WHEP 和指标要求 HttpOnly Session 或显式 Basic。存活与就绪探针保持公开。该实现仍是单操作员边界，不是 RBAC。

Basic credentials are cleartext on an unencrypted connection. Remote deployments must use `compose.m6-production.yaml`, set only externally visible HTTPS origins in `WEBOBS_CONTROL_ALLOWED_ORIGINS`, and prevent direct access to the backend port. The pinned Caddy process in the same product image terminates TLS with operator-mounted certificate files while `webobsd` validates the external Host/Origin relationship on container loopback. Base Compose loopback mode can remain unauthenticated; never expose that mode beyond the host.

未加密连接上的 Basic 凭据是明文。远程部署必须使用 `compose.m6-production.yaml`，只把外部可见的 HTTPS Origin 写入 `WEBOBS_CONTROL_ALLOWED_ORIGINS`，并阻止客户端绕过代理直连后端端口。同一产品镜像内固定版本 Caddy 使用操作者挂载的证书文件终止 TLS，`webobsd` 在容器回环继续校验外部 Host/Origin 关系。基础 Compose 的无认证回环模式只能留在本机。

The server applies these additional controls:

- local authorities are always accepted; authenticated remote authorities must derive from an explicitly allowlisted HTTPS origin;
- requests with Origin require that origin to match the request Host, and remote origins must also be allowlisted;
- WebSocket upgrades apply the same authentication and Host/Origin checks as HTTP;
- invalid credentials are rate-limited per client address for a bounded window; missing credentials do not consume the failure budget;
- no CORS permission is returned;
- JSON bodies are limited to 1 MiB, WHEP SDP to 64 KiB, headers to 16 KiB, and reads to 15 seconds;
- responses disable caching and include restrictive CSP, content-type, referrer, and permissions headers;
- API scene responses redact RTSP userinfo and browser URL query/fragment values, and never return stored secrets.
- the bundled editor is served from the same origin, with a restrictive CSP and no external scripts, fonts, or CDN dependencies.
- the WHEP upstream is fixed to the container loopback MediaMTX; upstream session locations are replaced with random same-origin tokens and never exposed to browsers.
- Direct MediaMTX paths use random 128-bit names, are created only for current scene sources, pull RTSP on demand, and are removed when their source leaves the scene; all MediaMTX output passes through the RTSP credential filter.

服务还会校验 Host/Origin、不返回 CORS 授权、限制请求体/请求头/读取时长、发送严格安全响应头，并隐藏来源凭据。无凭据 API 返回不含 `WWW-Authenticate` 的 `401`，避免浏览器 Basic 弹窗；显式 Basic 仍可用于 curl。错误达到阈值后返回带 `Retry-After` 的 `429`。认证不能替代 HTTPS。

## Configuration / 配置

| CLI | Environment | Default | Meaning |
| --- | --- | --- | --- |
| `--listen-address` | `WEBOBS_LISTEN_ADDRESS` | `127.0.0.1` | `127.0.0.1`, `::1`, `0.0.0.0`, or `::` |
| `--http-port` | `WEBOBS_HTTP_PORT` | `8080` | `0` disables HTTP/WebSocket |
| `--allow-insecure-remote` | `WEBOBS_ALLOW_INSECURE_REMOTE` | `false` | legacy unauthenticated non-loopback opt-in; unsafe |
| `--auth-username-file` | `WEBOBS_AUTH_USERNAME_FILE` | unset | absolute readable file; 1–64 printable ASCII bytes, no colon |
| `--auth-password-file` | `WEBOBS_AUTH_PASSWORD_FILE` | unset | absolute readable file; 16–256 bytes, no control bytes |
| `--auth-failure-limit` | `WEBOBS_AUTH_FAILURE_LIMIT` | `5` | invalid credentials allowed per client/window, 1–100 |
| `--auth-failure-window-seconds` | `WEBOBS_AUTH_FAILURE_WINDOW_SECONDS` | `60` | failure window and lockout duration, 1–3600 |
| `--session-database` | `WEBOBS_SESSION_DATABASE` | `/config/webobs/auth-sessions.db` | absolute SQLite WAL path |
| `--session-inactivity-seconds` | `WEBOBS_SESSION_INACTIVITY_SECONDS` | `604800` | sliding inactivity expiry, 300–2592000 |
| `--session-cookie-secure` | `WEBOBS_SESSION_COOKIE_SECURE` | `true` | require HTTPS when sending browser cookie |
| `--control-allowed-origins` | `WEBOBS_CONTROL_ALLOWED_ORIGINS` | empty | comma-separated external HTTPS origins; requires credentials |
| `--source-stale-seconds` | `WEBOBS_SOURCE_STALE_SECONDS` | `10` | seconds without a new visible-source frame before unhealthy, 2–300 |
| `--source-recovery-base-seconds` | `WEBOBS_SOURCE_RECOVERY_BASE_SECONDS` | `5` | first RTSP restart backoff, 1–300 |
| `--source-recovery-max-seconds` | `WEBOBS_SOURCE_RECOVERY_MAX_SECONDS` | `60` | exponential restart ceiling, 1–3600 and not below base |

The username and password files must be configured as a pair. Each may contain one trailing newline, which is removed. The values are loaded once at startup and never logged. The supplied `compose.m6-auth.yaml` mounts both through Compose secrets and disables the legacy unauthenticated opt-in. Scene mutations also require an absolute `--scene-file`; a runtime without persistent scene storage returns `503` for updates.

用户名和密码文件必须成对配置；文件末尾允许一个换行并会在读取时移除。值只在启动时加载且不会写入日志。仓库提供的 `compose.m6-auth.yaml` 会通过 Compose secrets 挂载两者，并关闭旧的无认证许可。场景变更还要求配置绝对 `--scene-file`；没有持久化场景路径的运行实例会对更新返回 `503`。

## HTTP resources / HTTP 资源

### `GET /`

Returns the bundled React/TypeScript scene editor. The non-hashed HTML entry is served with `Cache-Control: no-store`; hashed JavaScript and CSS under `/assets/` are immutable. Static requests accept only generated asset filenames, reject traversal attempts, and cap individual files at 2 MiB.

返回随产品镜像交付的 React/TypeScript 场景编辑器。未哈希的 HTML 入口使用 `Cache-Control: no-store`，`/assets/` 下的哈希 JavaScript/CSS 使用长期不可变缓存。静态资源只接受生成的文件名，拒绝目录穿越，并把单文件上限限制为 2 MiB。

### Browser session / 浏览器会话

- `POST /api/v1/auth/login` accepts bounded `{"username":"…","password":"…"}` JSON and returns a `webobs_session` cookie with `HttpOnly; Secure; SameSite=Strict; Path=/` in production.
- `GET /api/v1/auth/session` validates the hashed server-side record, updates `last_seen`, and slides `expires_at` by seven days by default.
- `POST /api/v1/auth/logout` revokes the SQLite row and clears the cookie.

SQLite stores only SHA-256 token hashes plus user, creation/last-seen/expiry timestamps and bounded client metadata. JavaScript cannot read the token. Production must keep `Secure=true`; the loopback-only HTTP test overlay explicitly disables it.

### `GET /api/v1/health`

Returns `200` while the control thread is serving:

```json
{"status":"ok","milestone":"v1-M11"}
```

This route is intentionally unauthenticated and contains no configuration details.

### `GET /api/v1/ready`

Returns public `200 {"status":"ready"}` after the control plane is active, configured Composite publication is ready, and every active OBS source is healthy. Gateway Direct-only operation is ready with `engineActive=false`; it does not initialize libobs video. It returns `503` during startup, output failure, or an active Composite source outage.

### `GET /metrics`

Returns Prometheus text metrics for process up/readiness, recording state, WebRTC configuration/readiness, aggregate visible/healthy/unhealthy source counts, automatic RTSP restart count, selected/available encoder backends, fallback state, HTTP request count, and rejected credential count. Encoder labels use only the fixed `x264`, `vaapi`, `qsv`, and `nvenc` set. This route requires authentication when credentials are configured; labels containing URLs, source IDs, usernames, device paths, or client addresses are not emitted.

### `GET /api/v1/sources/status`

Returns the authenticated per-source operational view. `state` is `idle`, `starting`, `healthy`, `stale`, or `recovering`; `lastFrameAgeMs` is `null` before the first observed RTSP frame and for synchronous browser sources. The response never contains RTSP/browser URLs, credentials, MediaMTX paths, or audit client addresses.

```json
{
  "visible": 2,
  "healthy": 2,
  "unhealthy": 0,
  "totalRestarts": 0,
  "sources": [{
    "id": "camera-front",
    "kind": "rtsp",
    "visible": true,
    "state": "healthy",
    "lastFrameAgeMs": 83,
    "restartCount": 0
  }]
}
```

`webobsd` samples frame progress every 500 ms. Once an RTSP source exceeds the stale threshold, it requests `obs_source_media_restart()` immediately and retries with exponential backoff capped by the configured maximum. Fresh frames reset the consecutive backoff and restore readiness. Browser sources participate in health/readiness using activation and output dimensions, but RTSP-style media restart is not applied to them.

`webobsd` 每 500 ms 采样一次帧进度。RTSP 来源超过陈旧阈值后会立即请求 `obs_source_media_restart()`，后续重试采用不超过配置上限的指数退避；新帧会重置连续退避并恢复 readiness。浏览器源通过激活状态与输出尺寸参与健康/readiness 判断，但不会套用 RTSP 媒体重启。

### `GET /api/v1/system/capabilities`

Returns encoder, renderer and hardware-decode decisions. Every backend reports `devicePresent`, `vaDriverLoaded`, `encodeSupported`, `decodeSupported`, `runtimeProbePassed`, `encoderAvailable`, and `ready`; device existence alone is never enough. Responses omit device paths, PCI IDs, driver versions and source URLs. Renderer is `idle` in Gateway Direct-only mode, `hardware` after a non-software GL probe, or `software` after the explicit llvmpipe fallback.

返回配置与实际选择的 H.264 编码器及固定后端能力标志。该接口要求认证，且不返回设备路径、PCI 标识、驱动版本或来源 URL。只有 `devicePresent` 与 `encoderAvailable` 同时为真时 `ready` 才为真；显式请求不可用后端时会安全选择 x264 并设置 `fallback`。

```json
{
  "videoEncoder": {
    "requested": "auto",
    "selected": "x264",
    "fallback": false,
    "backends": {
      "x264": {"devicePresent": true, "encoderAvailable": true, "ready": true},
      "vaapi": {"devicePresent": false, "encoderAvailable": true, "ready": false},
      "qsv": {"devicePresent": false, "encoderAvailable": false, "ready": false},
      "nvenc": {"devicePresent": false, "encoderAvailable": false, "ready": false}
    }
  }
}
```

### `GET /api/v1/program/status`

Returns whether WebRTC output is configured and the only browser-visible signaling route. `enabled` describes configuration, not current peer or publisher health.

```json
{"enabled":true,"endpoint":"/api/v1/program/whep"}
```

### `POST /api/v1/program/whep`

Accepts one complete recvonly WebRTC offer with `Content-Type: application/sdp`. The browser waits for ICE gathering to complete before POST; trickle ICE/PATCH is not implemented in M2. A successful response is `201 application/sdp`, contains the answer, and rewrites MediaMTX's internal location to an opaque local resource:

```http
Location: /api/v1/program/whep/session/0123456789abcdef0123456789abcdef
```

The proxy accepts no caller-selected upstream URL, credentials, query parameters, or fragments. It rejects a foreign Origin with `403`, SDP larger than 64 KiB with `413`, non-SDP content with `415`, and upstream signaling failure with `502`. At most 64 opaque sessions are retained; stale bookkeeping expires after ten minutes.

浏览器只向本站提交完整 ICE offer。代理的上游固定为容器回环 MediaMTX，内部会话地址会被替换为随机同源令牌；调用方不能选择目标或携带上游凭据。M2 尚不支持 trickle ICE/PATCH。

### `GET /api/v1/playback/capabilities`

Returns the explicit playback modes and one source-scoped same-origin endpoint for every RTSP source in the current scene. Browser sources are reported as `preferred: "composite"` and `strategy: "composite"` without an endpoint. The response contains source IDs already present in the public scene, but never contains RTSP/browser URLs, credentials, MediaMTX addresses, internal path names, or caller-selectable upstreams.

API v1 keeps the value `direct` for compatibility, but it means **Gateway Direct / Direct Relay**: MediaMTX in Docker still pulls and forwards the stream. It does not mean the v2 `true-direct` topology where Docker carries zero video payload. API v1 does not accept or advertise `true-direct`.

```json
{
  "defaultMode": "direct",
  "modes": {
    "composite": {"enabled": true, "endpoint": "/api/v1/program/whep"},
    "direct": {"enabled": true, "fallback": "composite"}
  },
  "sources": [{
    "sourceId": "camera-front",
    "endpoint": "/api/v1/sources/camera-front/whep",
    "preferred": "direct",
    "fallback": "composite",
    "strategy": "passthrough",
    "codec": "h264",
    "audioCodec": "opus"
  }]
}
```

`codec` and `audioCodec` report probed names without an address. The response also returns `deliveryMode`, independent `videoDelivery`/`audioDelivery`, server decode/encode/audio-transcode booleans, decoder/encoder, reason, LOW/MEDIUM/HIGH `serverCost`, and whether Composite is concurrently active. Hybrid copies every compatible track and transcodes only the incompatible track.

### `GET /api/v1/system/processes`

Returns five fixed process groups (`webobsd`, `mediamtx`, `ffmpeg`, `caddy`, `obs-browser`) with instance count, RSS KiB and adjacent-sample CPU percent, plus RTSP TCP session count, AMD GPU busy when readable, and `controlPlaneActive`, `engineActive`, `compositePublisherActive`. No PID, command line, URL or filesystem path is returned.

### Camera Registry / 摄像机注册表

- `GET|POST /api/v1/cameras`, `GET|PUT|DELETE /api/v1/cameras/{cameraId}` manage stable devices and profiles.
- `POST /api/v1/camera-detect` classifies a bounded IP/hostname/URL and probes media where supported. Canon WV-HTTP `/-wvhttp-01-/video.cgi` and ordinary MJPEG paths use a bounded `GET` because Server Push endpoints commonly reject `HEAD`; a successful probe requires `multipart/x-mixed-replace` plus a JPEG part marker.
- `GET /api/v1/camera-adapters` returns the supported adapter names.
- `POST /api/v1/onvif/discover` performs bounded WS-Discovery and returns at most 128 non-credential XAddr results.
- `POST /api/v1/onvif/probe` accepts `address` and `credentialsRef`, then reads authenticated Media2/Profile T profiles with Media/Profile S fallback without saving partial state.
- `POST /api/v1/cameras/{cameraId}/onvif/sync` atomically refreshes a saved ONVIF camera's profiles, capability cache, and health.

All mutations require the normal authentication and same-origin boundary. Embedded URL userinfo, credential-like query keys/fragments, unsafe IDs and traversal in `credentialsRef` are rejected. The loopback service stores SQLite WAL metadata; only internal consumers can resolve `/run/secrets/webobs-camera-credentials/<ref>.json`. ONVIF SOAP is response-size bounded, rejects DTD/entities and redirects, validates HTTPS normally, and never returns credential material. See [onvif-media.md](onvif-media.md).

返回当前明确支持的播放模式，以及场景中每个来源对应的同源端点。API v1 为兼容性保留 `direct` 值，但它表示 **Gateway Direct / 网关直通**：Docker 内 MediaMTX 仍会拉取并转发媒体，不等于 v2 中 Docker 视频负载为零的 `true-direct`。API v1 不接受或通告 `true-direct`。响应只复用公开场景已有的来源 ID，不包含 RTSP、凭据、MediaMTX 地址、内部路径或调用方可选上游。`codec` 与 `audioCodec` 只报告探测到的上游编码名称；H.264/VP8/VP9/AV1 视频和无音频/Opus/G.711 A-law/G.711 mu-law 音频可网关直通，任一现有编码不兼容时，按需 Hybrid 路由只转换必要轨道，并返回 `strategy: "hybrid"`。

### `POST /api/v1/sources/{sourceId}/whep`

Accepts the same complete SDP offer as the program endpoint. The source ID must exactly match a current RTSP source. On first use, the server creates a random internal MediaMTX path, configures an on-demand RTSP pull through the loopback-only Control API, and probes the video codec through that opaque loopback path. Browser-compatible codecs pass through; incompatible codecs use a second random path and an on-demand H.264 transcoder that stops after the final reader closes. Unknown sources return `404`; browser sources return `409 composite_only`; signaling/configuration failure returns `502`. Content, Origin, size, and global 64-session limits are identical to program WHEP.

首次使用当前场景来源时，服务会通过仅回环可达的 Control API 创建随机内部路径，并仅在 reader 存在时拉取 RTSP。浏览器不能指定内部路径或上游 URL。

### `DELETE /api/v1/sources/{sourceId}/whep/session/{token}`

Closes only a session created for the same source-scoped route. A valid token cannot be replayed through another source route; mismatches and unknown tokens return `404`.

### `DELETE /api/v1/program/whep/session/{token}`

Closes the mapped MediaMTX reader and returns `204`. Unknown or malformed tokens return `404`; the upstream location is never accepted from the client. The bundled player sends this request on reconnect and page close when the browser permits a keepalive request.

### `GET /api/v1/scene`

Returns the current public scene document with `200` and an ETag containing its decimal revision:

```http
ETag: "4"
Cache-Control: no-store
Content-Type: application/json; charset=utf-8
```

If a stored RTSP authority contains userinfo such as `name:secret@camera`, the response replaces it with `***:***@camera`. Browser URL query and fragment values are replaced with `?***` and `#***`. Unredacted values remain only in the protected scene file and active OBS source.

若存储的 RTSP 地址含有用户信息，接口会把用户信息替换为 `***:***`。未脱敏值只保留在受保护场景文件和活动 OBS 来源中。

### `PUT /api/v1/scene`

Replaces the complete scene transactionally. Send the public document obtained from GET, keep its `revision` unchanged, and repeat the ETag in `If-Match`:

```bash
curl --request PUT http://127.0.0.1:8080/api/v1/scene \
  --header 'Content-Type: application/json' \
  --header 'If-Match: "4"' \
  --data-binary @scene.json
```

On success the server:

1. validates the candidate and revision;
2. restores the stored credential only when a redacted URL still identifies the same existing source;
3. prepares a complete replacement libobs scene and prewarms every visible source while the old output remains active;
4. waits up to `connect-timeout-seconds` for candidate sources to produce a decoded frame, then primes that frame into the source texture;
5. atomically persists revision `N + 1` with private permissions;
6. atomically replaces the items inside the current output scene without dropping reused source activity or exposing an empty scene, then broadcasts `scene.updated`.

成功时，服务会验证文档与版本，仅为未改变的既有来源恢复已存凭据；旧输出继续运行期间，候选场景会预热全部可见来源、等待真实解码帧并将该帧预装到来源纹理。全部就绪后才原子保存 `N + 1` 版本，再在当前输出场景内部原子替换 items，避免暴露空场景并保持复用来源 active，最后广播事件。不可达的新来源会使整个事务回滚，活动场景、磁盘文件和 revision 均保持不变。

A redacted credential placeholder is rejected for a new source or a changed endpoint. To change credentials, submit the complete new RTSP URL over the local connection. The server never echoes that secret in its response or parse errors.

新来源或已改变端点不能使用脱敏占位符；如需更换凭据，应通过本地连接提交完整的新 RTSP URL。服务不会在响应或解析错误中回显该秘密。

Common status codes:

| Status | Code | Meaning |
| ---: | --- | --- |
| 200 | — | scene committed; response and ETag contain the new revision |
| 403 | `origin_rejected` | a present Origin is not the same local authority as Host |
| 409 | `runtime_rejected` | a candidate source timed out or libobs could not prepare the replacement; no change is committed |
| 412 | `revision_conflict` | `If-Match` or body revision is stale |
| 413 | `body_too_large` | request body exceeds 1 MiB |
| 415 | `content_type` | content type is not `application/json` |
| 422 | `invalid_scene` | schema, limits, references, or credential placeholder is invalid |
| 428 | `precondition_required` | `If-Match` is missing |
| 431 | `headers_too_large` | request headers exceed 16 KiB |
| 503 | `persistence_failed` | persistent storage is unavailable or the atomic save failed |

All error bodies use a stable envelope and include the current revision without including the rejected request:

```json
{"error":{"code":"revision_conflict","message":"scene revision does not match If-Match"},"revision":4}
```

### Studio collection endpoints / Studio 集合接口

`GET /api/v1/studio` returns the redacted Studio collection and an ETag containing the Studio revision. `PUT /api/v1/studio` replaces the complete collection using the same JSON content type, `If-Match`, body limit, secret-restoration, private atomic persistence, and error envelope as the scene endpoint. Studio saves only change Preview definitions; they do not mutate the active Program runtime.

`GET /api/v1/studio` 返回脱敏集合及 Studio revision ETag；`PUT /api/v1/studio` 使用与场景接口相同的 JSON、`If-Match`、大小限制、秘密恢复、私有原子持久化及错误信封。保存集合只修改 Preview 定义，不会直接改变活动 Program。

`POST /api/v1/studio/take`, `/undo`, and `/redo` require `If-Match` and an empty body. Take prepares the selected Preview—including nested scenes and filters—then atomically commits Cut or Fade and persists the promoted Program. Undo/redo restore both the collection and active Program transactionally; runtime or persistence failure rolls the operation back. Taking when Program and Preview have the same ID still applies a changed saved definition.

`POST /api/v1/studio/take`、`/undo`、`/redo` 均要求 `If-Match` 且不接收请求体。Take 会先准备完整 Preview，再原子提交 Cut/Fade 并持久化提升后的 Program；撤销重做会事务性恢复集合与活动 Program，运行时或持久化失败会回滚。

`GET /api/v1/studio/capabilities` returns each scene's requested Direct/Hybrid result, exactness, selected fallback, and human-readable reasons. It never returns source URLs, credentials, internal routes, or file contents.

`GET /api/v1/studio/capabilities` 返回每个场景的 Direct/Hybrid 精确性、实际选择及降级原因，绝不返回来源 URL、凭据、内部路由或文件内容。

## Device operations / 设备操作

Authenticated same-origin clients may use `GET /api/v1/cameras/{id}/onvif/presets`, `POST .../ptz`, `.../presets`, `.../snapshot`, `.../events/pull`, `.../talk`, and `GET /api/v1/cameras/{id}/operations`. PTZ continuous moves have a server-enforced 100–2000 ms auto-stop and per-camera rate limit. Snapshot and talk payloads are bounded; device tokens and credentials are private implementation state.

认证且同源的客户端可使用上述预置位、PTZ、快照、事件、对讲与操作审计接口。连续 PTZ 由服务端强制在 100–2000 ms 自动停止并逐摄像机限速；快照与对讲负载有固定上限，设备 token 与凭据始终属于私有实现状态。

## Events and automation / 事件与自动化

- `GET|POST /api/v1/events` searches or creates normalized events; search accepts `cameraId`, `type`, `zoneId`, `label`, `acknowledged`, `from`, and `to`.
- `PUT /api/v1/events/{id}/acknowledgement` changes acknowledgement and a bounded operator note with audit.
- `GET|POST /api/v1/motion-zones` manages normalized include/exclude/privacy polygons.
- `POST /api/v1/motion/evaluate` evaluates a bounded grayscale fixture/frame contract.
- `GET|POST /api/v1/detector-providers` and `POST /api/v1/detector-providers/{id}/events` expose provider schema v1.
- `GET|POST /api/v1/event-rules` manages bounded predicates/actions.
- `GET /api/v1/notification-outbox` exposes delivery state without secrets; `POST .../process` is an authenticated diagnostic retry request.

All mutations require JSON and pass the same authentication and Origin checks as Camera Registry operations. Notification endpoints are mounted Secret references; URLs and credentials are never accepted in an event or rule action. See [events-and-automation.md](events-and-automation.md).

## WebSocket / WebSocket 事件

Connect to `ws://127.0.0.1:8080/api/v1/ws` from a page served under the same local authority. The upgrade must include an exact matching `Origin`, for example both Host and Origin using `127.0.0.1:8080`.

连接建立后首先收到完整的脱敏快照：

```json
{"type":"scene.snapshot","scene":{"schemaVersion":4,"revision":4}}
```

Each successful PUT broadcasts the committed public scene to all connected clients:

```json
{"type":"scene.updated","scene":{"schemaVersion":3,"revision":5}}
```

The examples abbreviate the scene object; actual events contain the complete public scene document. M1 clients do not send mutation messages over WebSocket—write through HTTP PUT, and use WebSocket for synchronization.

示例省略了场景其余字段；实际事件包含完整的公开场景文档。M1 客户端不通过 WebSocket 写入，统一使用 HTTP PUT 变更，并以 WebSocket 同步提交结果。
