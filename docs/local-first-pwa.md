# v2.0 Local-first PWA / v2.0 本地优先 PWA

> Status / 状态：v2-M2/M3 shipped in `v2.0.1`; v2-M5 monitor enhancements continue on `dev` / v2-M2/M3 已随 `v2.0.1` 发布；v2-M5 监控增强继续在 `dev` 开发

## Product boundary / 产品边界

The v2.0 deliverable is one OCI image containing the Docker control/NVR services and the production PWA. It does not include EXE, AppImage, Flatpak, APK or a production IWA bundle. The frozen Qt/GStreamer/Android sources remain available for security maintenance and research only.

v2.0 只交付一个 OCI 镜像，其中包含 Docker 控制/NVR 服务与正式 PWA；不交付 EXE、AppImage、Flatpak、APK 或生产 IWA Bundle。冻结的 Qt/GStreamer/Android 源码仅保留安全维护与研究用途。

```text
first visit and sync: Browser <-HTTPS-> Docker
                       Browser caches hashed app shell and encrypted snapshots

true direct:          Camera --WHEP/HLS/MJPEG--> Browser
                      Docker --grant/scene/policy--> Browser

ordinary RTSP:        Camera --> Docker Gateway/Hybrid --> Browser
```

“Local-first” means UI code, canvas transforms and authorized snapshots execute from browser storage. Live video remains streaming media and is never an offline-cache payload. An installed PWA does not make RTSP browser-compatible.

“本地优先”表示 UI 代码、画布变换和获批快照从浏览器存储执行；实时视频仍是流媒体，绝不作为离线缓存内容。安装 PWA 不会让 RTSP 自动变成浏览器兼容协议。

## Cache and update contract / 缓存与升级契约

- Hashed JS/CSS use cache-first and immutable HTTP caching; versioned icons belong to the precached shell. Navigation uses network-first with the previous complete app shell and a bounded offline fallback / 哈希 JS/CSS 使用 cache-first 和 immutable HTTP 缓存，版本化图标属于预缓存应用壳；导航使用 network-first，并保留上一套完整应用壳及有界离线页。
- `/api/**`, sessions, WHEP, recordings, events, metrics and every cross-origin media request are network-only / `/api/**`、会话、WHEP、录像、事件、指标和全部跨源媒体请求均为 network-only。
- The repository owns `src/sw.ts`; runtime code is never fetched from a CDN. A new worker waits until the user accepts the update, so active playback never mixes two builds / `src/sw.ts` 由仓库维护，运行代码不从 CDN 获取；新 Worker 等待用户确认后激活，活动播放不会混用两个构建版本。
- Production requires a browser-trusted HTTPS certificate. For IP access, the IP must be in the certificate SAN. Scheme, host/IP or port changes create a new Origin and require a new cache and pairing / 生产环境要求浏览器信任的 HTTPS 证书；使用 IP 时证书 SAN 必须包含该 IP。Scheme、主机/IP 或端口变化会形成新 Origin，必须重新缓存与配对。

## Local data and expiry / 本地数据与过期

IndexedDB `webobs-local-v1` contains only five bounded stores: `identity`, `snapshot`, `localScenes`, `auditQueue` and `runtimeMeta`. Private records use AES-GCM with a non-extractable WebCrypto wrapping key. Browser enrollment creates Ed25519 and X25519 keys through the repository-locked libsodium WASM dependency. The encrypted browser Grant format is `webobs-browser-grant-v1`, has a seven-day sliding offline expiry, and contains no camera credentials.

IndexedDB `webobs-local-v1` 只有五个有界 Store：`identity`、`snapshot`、`localScenes`、`auditQueue`、`runtimeMeta`。私有记录使用 AES-GCM，并由不可导出的 WebCrypto 包装密钥保护。浏览器配对通过仓库锁定的 libsodium WASM 生成 Ed25519 与 X25519 密钥。加密浏览器 Grant 格式为 `webobs-browser-grant-v1`，离线有效期按七天滑动，且不包含摄像机凭据。

Offline Scene snapshots retain stable Camera/Profile IDs, transforms, text, colors and nesting. Raw RTSP/browser URLs and server file paths are removed before encryption. An expired lease keeps only the public app shell and deletes/hides identity, grants and private snapshots. Logout and online revocation use the same private-state deletion boundary.

离线 Scene 快照保留稳定 Camera/Profile ID、变换、文字、色块和嵌套；原始 RTSP/网页 URL 与服务端文件路径在加密前移除。租约过期后只保留公开应用壳，并删除或隐藏身份、Grant 与私有快照；登出及在线撤销使用同一私有状态清除边界。

## Browser media contract / 浏览器媒体契约

The server, never a client boolean, decides direct eligibility. The adapter must be `whep`, `hls` or `mjpeg`; the endpoint must be exact HTTPS without embedded credentials/query/fragment; the Camera Registry must have no long-term credential dependency; and its per-profile TLS/CORS probe must pass. The PWA still requires a decoded first frame within three seconds.

真直连资格由服务端决定，不能信任客户端布尔值。Adapter 必须是 `whep`、`hls` 或 `mjpeg`；Endpoint 必须是无内嵌凭据、query、fragment 的精确 HTTPS 地址；Camera Registry 不得依赖长期凭据，逐 Profile TLS/CORS 探测必须通过。PWA 仍需在三秒内取得实际首帧。

Only one live chain may exist for a tile. A failed direct attempt is closed before a device-authenticated Gateway lease and WHEP session are created. UI diagnostics always display the media arrow, protocol, execution owner, decoder/encoder and fallback reason. Ordinary PWA RTSP always reports `Camera → Docker → Browser`.

每个 Tile 同时只允许一条实时链。直连失败后先关闭该尝试，再创建受设备认证的 Gateway lease 与 WHEP Session。UI 始终显示媒体箭头、协议、执行 Owner、解码/编码器及回退原因；普通 PWA 的 RTSP 永远显示 `Camera → Docker → Browser`。

`WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS` is a comma-separated list of exact HTTPS camera origins used to construct CSP `connect-src`, `img-src` and `media-src`. A wildcard such as `https:` or `https://*` is invalid policy and must not be used.

`WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS` 是用于构造 CSP `connect-src`、`img-src` 和 `media-src` 的精确 HTTPS 摄像机 Origin 逗号列表。不得使用 `https:` 或 `https://*` 等全局通配策略。

`WEBOBS_PWA_PUBLIC_ORIGIN` is the one exact browser-facing HTTPS Origin (for example, `https://monitor.example.com:28777`) sent during Camera Registry CORS qualification. The UI qualification action performs a bounded TLS/CORS/media probe and records an origin-bound proof for 24 hours. User-submitted Camera capability JSON cannot create or overwrite that proof.

`WEBOBS_PWA_PUBLIC_ORIGIN` 是浏览器实际访问的一条精确 HTTPS Origin（例如 `https://monitor.example.com:28777`），用于 Camera Registry 的 CORS 资格探测。UI 探测会执行有界 TLS/CORS/媒体检查，并记录与该 Origin 绑定、有效期 24 小时的证明；用户提交的 Camera capability JSON 不能创建或覆盖此证明。

## CI and release / CI 与发布

- Fork PR and protected branches: GitHub-hosted audit, dependency install, typecheck and deterministic PWA build only; no secrets and no private media fixtures / Fork PR 与受保护分支只在 GitHub-hosted Runner 执行审计、依赖安装、类型检查和确定性 PWA 构建；无 Secret，也不接触私有媒体夹具。
- Local WSL2 Linux: Linux shell, Chromium and Linux media acceptance; Windows Docker Desktop owns container builds / 本机 WSL2 Linux：Linux shell、Chromium 与 Linux 媒体验收；容器构建由 Windows Docker Desktop 负责。
- Local Windows: installed Chrome/Edge, offline/update compatibility and long-run acceptance / 本机 Windows：已安装 Chrome/Edge、离线/升级兼容与长稳验收。
- OCI publication is local-only and requires fresh revision-bound receipts from both hosts / OCI 仅允许本地发布，并要求同一提交的两份新鲜门禁收据。
- A v2 tag cannot be created until both local browser gates pass. Native-client workflow has no v2 tag trigger / 两个本机浏览器门禁全部通过前不得创建 v2 Tag；原生客户端工作流没有 v2 Tag 触发器。

The Chromium IWA RTSP/TCP worker is an experiment limited to an unauthenticated synthetic H.264 fixture and exact Grant host/port. It is neither cached into the production PWA nor released as `.swbn`, and its failure never lowers the v2.0 stable gate.

Chromium IWA RTSP/TCP Worker 仅用于无认证合成 H.264 夹具，并严格限制到 Grant 指定 host/port；它不会进入正式 PWA 缓存，也不发布 `.swbn`，其失败不会降低 v2.0 稳定门禁。
