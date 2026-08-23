# Timeline, Playback & Evidence / 时间线、回放与证据

M9 turns the M8 UTC archive catalog into an operator workflow. The React workspace is available from **录像时间线** or `#archive`; all browser requests remain same-origin under `/api/v1/nvr/*` and therefore inherit the M6 authentication and trusted-HTTPS boundary. The loopback NVR listener is never published.

M9 将 M8 UTC 归档目录转化为值守工作流。React 工作区可通过“录像时间线”或 `#archive` 打开；全部浏览器请求仍使用 `/api/v1/nvr/*` 同源路径，因此继承 M6 认证与受信 HTTPS 边界。仅回环 NVR 监听器始终不发布。

## Timeline and playback / 时间线与回放

`GET /api/v1/nvr/timeline?from=<utc-ms>&to=<utc-ms>&cameraId=<id>` accepts a positive range of at most 31 days and returns at most the caller-selected known camera IDs. Storage remains UTC. Each camera result contains ordered segments, explicit offline/missing/corrupt gaps, the oldest retained boundary, and the recorded main/sub profile. Display conversion is performed with the browser `Intl` time-zone database; UTC keys and query boundaries never change when the operator selects another zone.

`GET /api/v1/nvr/timeline?from=<utc-ms>&to=<utc-ms>&cameraId=<id>` 接受最长 31 天的正向范围，并且只返回调用方选择的已知摄像机 ID。存储始终为 UTC。逐路结果包含有序片段、明确的离线/缺失/损坏断档、最早保留边界和已录主/辅码流。显示转换使用浏览器 `Intl` 时区数据库；操作者切换显示时区时，UTC 键和查询边界不会改变。

The UI opens one to four fragmented MP4 players with HTTP Range. One player is the clock master; every 250 ms the others are compared in global UTC and corrected only when drift exceeds 250 ms. Play, pause, seek, 0.25×–4× speed, and 30 FPS frame-step operate on the shared UTC cursor. A missing or corrupt segment becomes a visible gap and playback advances to the next available segment. The UI obtains 30-second playback leases and renews them every 20 seconds; transfer reader locks and unexpired leases both keep retention from deleting active media.

界面可打开 1–4 个支持 HTTP Range 的 fragmented MP4 播放器。一路作为时钟主控；每 250 ms 以全局 UTC 比较其他播放器，仅在偏差超过 250 ms 时纠正。播放、暂停、跳转、0.25×–4× 倍速和 30 FPS 逐帧均作用于共享 UTC 游标。缺失或损坏片段显示为明确断档，并在下一可用片段恢复。UI 获取 30 秒回放租约并每 20 秒续租；传输读锁和未过期租约都会阻止保留任务删除活动媒体。

## Bounded derived media / 有界派生媒体

`GET /thumbnails/{segment-id}?offsetMs=<n>` uses at most four concurrent FFmpeg jobs, scales to 320 pixels wide, and caches at most 1,000 JPEGs for 24 hours. `POST /snapshots` accepts only a catalog segment ID and bounded offset, copies a generated JPEG into the evidence root, returns its SHA-256 and a fixed download URL, and emits an audit event. Neither operation accepts a path or source URL.

`GET /thumbnails/{segment-id}?offsetMs=<n>` 最多使用四个并发 FFmpeg 任务，缩放到 320 像素宽，并最多缓存 1,000 张 JPEG、保留 24 小时。`POST /snapshots` 只接受目录中的片段 ID 和有界偏移，将生成的 JPEG 写入证据根目录，返回 SHA-256 与固定下载 URL，并产生审计事件。两种操作均不接受路径或来源 URL。

## Evidence export / 证据导出

`POST /exports` accepts one to four camera IDs, a positive range of at most 24 hours, `fast|exact`, a lock flag, and an optional safe logical `programRecordingId`. Fast mode concatenates complete compatible segments with stream copy and reports segment/keyframe-aligned effective boundaries. Exact mode decodes and re-encodes H.264 from the requested offset and reports the requested UTC boundary. Export workers use fixed argument vectors, no shell, catalog-derived paths, a five-minute process timeout, and a private per-export directory.

`POST /exports` 接受 1–4 个摄像机 ID、最长 24 小时的正向范围、`fast|exact`、锁定标志及可选的安全逻辑 `programRecordingId`。快速模式通过码流复制连接完整兼容片段，并报告按片段/关键帧对齐的实际边界；精确模式从请求偏移解码并重新编码 H.264，报告请求的 UTC 边界。导出 worker 使用固定参数数组、不经过 shell、路径只来自目录记录、进程超时五分钟，并写入私有逐导出目录。

Every export returns a schema-v1 JSON manifest with export/audit IDs, software version, mode, requested/effective UTC range, camera and source-segment IDs, logical program association, track codecs, byte sizes, per-file SHA-256 values, and fixed download URLs. The response also gives the manifest SHA-256. It intentionally omits RTSP URLs, credentials, filesystem paths, user-selected filenames, and FFmpeg diagnostics. Evidence source segments are locked by default.

每次导出返回 schema-v1 JSON 清单，包含导出/审计 ID、软件版本、模式、请求/实际 UTC 范围、摄像机与来源片段 ID、逻辑节目录像关联、轨道编码、字节数、逐文件 SHA-256 和固定下载 URL；响应另返回清单自身 SHA-256。清单明确不含 RTSP URL、凭据、文件系统路径、用户自选文件名和 FFmpeg 诊断。来源证据片段默认锁定。

## Authorization, audit and deletion / 授权、审计与删除

M9 uses the current single-operator M6 authorization boundary: all timeline, media, thumbnail and artifact reads require authentication when configured; every mutation additionally requires the same-origin check. Playback, snapshot, export, artifact download, lock/unlock, retention and delete write structured stable-ID audit events. A locked or actively read segment returns a conflict instead of being deleted. Authorized deletion removes the media and marks the catalog row deleted; it is intentionally irreversible.

M9 使用当前 M6 单操作者授权边界：配置认证后，时间线、媒体、缩略图与证据读取均要求认证；全部变更还要求同源检查。回放、截图、导出、证据下载、锁定/解锁、保留和删除均写入只含稳定 ID 的结构化审计事件。锁定中或正在读取的片段会返回冲突而不删除。已授权删除会移除媒体并把目录行标记为已删除；该操作明确不可逆。

## Acceptance / 验收

```powershell
pwsh ./tests/run-m9-timeline.ps1
```

The deterministic gate records four synthetic cameras, freezes the archive, measures 40 local timeline queries against a 500 ms p95 budget, verifies UTC/leap-day and corrupt-gap behavior, HTTP Range, JPEG thumbnail/snapshot hashes, four-camera fast export, exact-boundary export, logical program association, manifest and file SHA-256, FFprobe playback, evidence lock/delete conflicts, and credential/path-free audit events. The published p95 number is environment-specific and must be remeasured on deployment storage. Browser synchronization uses the explicit 250 ms correction threshold; production release qualification should additionally observe a real four-player session across target browsers and daylight-saving zones.

确定性门禁录制四路合成摄像机并冻结归档，测量 40 次本地时间线查询与 500 ms p95 预算，验证 UTC/闰日及损坏断档、HTTP Range、JPEG 缩略图/截图哈希、四路快速导出、精确边界导出、逻辑节目录像关联、清单与文件 SHA-256、FFprobe 播放、证据锁/删除冲突及不含凭据/路径的审计事件。公开 p95 数值与环境相关，部署存储上必须重新测量。浏览器同步使用明确的 250 ms 纠正阈值；生产发布资格还应在目标浏览器及夏令时时区观察真实四播放器会话。

The current-worktree image regression on 2026-08-23 passed the complete gate and measured 4.8 ms p95 for 40 local timeline queries. The result records this development machine and Docker storage only; it does not replace target-host storage measurement or real-browser/DST observation.

2026-08-23 的当前工作树镜像回归通过完整门禁，40 次本地时间线查询 p95 为 4.8 ms。该结果只记录本开发机与 Docker 存储，不替代目标主机存储测量及真实浏览器/夏令时观察。
