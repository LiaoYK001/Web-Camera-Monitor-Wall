# Control API v1 / 控制接口 v1

M1 exposes a small HTTP/1.1 and WebSocket control plane from `webobsd`. It uses the same [scene document](scene-schema-v1.md) that libobs renders and that the atomic scene store persists.

M1 由 `webobsd` 提供一组精简的 HTTP/1.1 与 WebSocket 控制接口。接口、libobs 渲染和原子场景存储共用同一份[场景文档](scene-schema-v1.md)。

## Security boundary / 安全边界

The API has no authentication, authorization, or TLS in M1. Direct CLI usage binds to `127.0.0.1:8080` by default. Product Compose binds inside the container and publishes only `127.0.0.1:8080` on the host. Keep that loopback mapping intact; do not expose the port through a LAN address, public proxy, tunnel, or router.

M1 接口尚无认证、授权或 TLS。直接运行默认监听 `127.0.0.1:8080`；产品 Compose 在容器内监听，并仅发布到主机 `127.0.0.1:8080`。请保留该回环映射，不得通过局域网地址、公共反向代理、隧道或路由器暴露端口。

The server applies these additional controls:

- only `localhost`, `127.0.0.1`, and `[::1]` Host authorities are accepted;
- mutation requests reject a present foreign Origin;
- WebSocket upgrades require an Origin exactly matching the local Host;
- no CORS permission is returned;
- JSON bodies are limited to 1 MiB, headers to 16 KiB, and reads to 15 seconds;
- responses disable caching and include restrictive CSP, content-type, referrer, and permissions headers;
- API scene responses redact RTSP userinfo and never return stored credentials.

服务还会限制本地 Host、校验 Origin、不返回 CORS 授权、限制请求体/请求头/读取时长、发送严格安全响应头，并在所有 API 场景响应中隐藏 RTSP 凭据。这些措施只降低本机误用和浏览器跨站请求风险，不能代替 M6 的身份认证与加密。

## Configuration / 配置

| CLI | Environment | Default | Meaning |
| --- | --- | --- | --- |
| `--listen-address` | `WEBOBS_LISTEN_ADDRESS` | `127.0.0.1` | `127.0.0.1`, `::1`, `0.0.0.0`, or `::` |
| `--http-port` | `WEBOBS_HTTP_PORT` | `8080` | `0` disables HTTP/WebSocket |
| `--allow-insecure-remote` | `WEBOBS_ALLOW_INSECURE_REMOTE` | `false` | must be explicitly true for a non-loopback bind |

The explicit remote-bind flag is a guardrail for container networking, not an approval to expose M1 remotely. Scene mutations also require an absolute `--scene-file`; a runtime without persistent scene storage returns `503` for updates.

非回环确认开关只是容器网络防误配措施，不代表 M1 可以安全远程暴露。场景变更还要求配置绝对 `--scene-file`；没有持久化场景路径的运行实例会对更新返回 `503`。

## HTTP resources / HTTP 资源

### `GET /api/v1/health`

Returns `200` while the control thread is serving:

```json
{"status":"ok","milestone":"M1"}
```

### `GET /api/v1/scene`

Returns the current public scene document with `200` and an ETag containing its decimal revision:

```http
ETag: "4"
Cache-Control: no-store
Content-Type: application/json; charset=utf-8
```

If a stored RTSP authority contains userinfo such as `name:secret@camera`, the response replaces it with `***:***@camera`. The unredacted value remains only in the protected scene file and the active OBS source.

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
3. prepares a complete replacement libobs scene without changing the active output;
4. atomically persists revision `N + 1` with private permissions;
5. swaps the active OBS scene and broadcasts `scene.updated`.

成功时，服务会验证文档与版本，仅为未改变的既有来源恢复已存凭据，在不影响当前输出的前提下准备新 libobs 场景，原子保存 `N + 1` 版本，然后切换活动场景并广播事件。

A redacted credential placeholder is rejected for a new source or a changed endpoint. To change credentials, submit the complete new RTSP URL over the local connection. The server never echoes that secret in its response or parse errors.

新来源或已改变端点不能使用脱敏占位符；如需更换凭据，应通过本地连接提交完整的新 RTSP URL。服务不会在响应或解析错误中回显该秘密。

Common status codes:

| Status | Code | Meaning |
| ---: | --- | --- |
| 200 | — | scene committed; response and ETag contain the new revision |
| 403 | `origin_rejected` | a present Origin is not the same local authority as Host |
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

## WebSocket / WebSocket 事件

Connect to `ws://127.0.0.1:8080/api/v1/ws` from a page served under the same local authority. The upgrade must include an exact matching `Origin`, for example both Host and Origin using `127.0.0.1:8080`.

连接建立后首先收到完整的脱敏快照：

```json
{"type":"scene.snapshot","scene":{"schemaVersion":1,"revision":4}}
```

Each successful PUT broadcasts the committed public scene to all connected clients:

```json
{"type":"scene.updated","scene":{"schemaVersion":1,"revision":5}}
```

The examples abbreviate the scene object; actual events contain the complete public scene document. M1 clients do not send mutation messages over WebSocket—write through HTTP PUT, and use WebSocket for synchronization.

示例省略了场景其余字段；实际事件包含完整的公开场景文档。M1 客户端不通过 WebSocket 写入，统一使用 HTTP PUT 变更，并以 WebSocket 同步提交结果。
