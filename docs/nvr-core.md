# NVR Core / NVR 核心

M8 adds an independent per-camera archive process to the existing single product container. Canvas edits, Preview/Program transitions, and the libobs program recorder do not own NVR workers. The browser-facing `webobsd` control plane authenticates and proxies the fixed `/api/v1/nvr/*` namespace to a loopback-only service; NVR never publishes another container port.

M8 在现有单产品容器内增加独立逐路归档进程。画布编辑、Preview/Program 转场和 libobs 节目录制器均不拥有 NVR worker。面向浏览器的 `webobsd` 控制面负责认证，并把固定的 `/api/v1/nvr/*` 命名空间代理到仅回环监听的服务；NVR 不发布额外容器端口。

## Enable and storage / 启用与存储

Set the following only in the untracked `.env` file. The default remains disabled so existing M0–M7 deployments do not start archive jobs unexpectedly.

仅在不受 Git 跟踪的 `.env` 中设置以下值。默认保持关闭，避免已有 M0–M7 部署意外启动归档任务。

```dotenv
WEBOBS_NVR_ENABLED=true
WEBOBS_NVR_CONFIG=/config/webobs/nvr.json
WEBOBS_NVR_STORAGE=/recordings/nvr
```

`nvr.json` is atomically stored with mode `0600`. Media is finalized as fragmented MP4 under `<camera-id>/YYYY/MM/DD/`; `catalog.sqlite3` uses WAL and mode `0600`. `.partial`, `.pre-event`, `.quarantine`, thumbnail, and export paths are internal implementation details and must not be served as static files. The complete recordings volume requires a separate encrypted backup policy; copying a live SQLite file is not a valid catalog backup.

`nvr.json` 以 `0600` 权限原子保存。媒体以 fragmented MP4 封装到 `<camera-id>/YYYY/MM/DD/`，`catalog.sqlite3` 使用 WAL 且权限为 `0600`。`.partial`、`.pre-event`、`.quarantine`、缩略图和导出路径均是内部实现细节，不能作为静态目录提供。完整录像卷必须使用独立的加密备份策略；直接复制运行中的 SQLite 文件不是有效目录备份。

## Configuration contract / 配置契约

The strict schema is version 1 and accepts at most 64 stable camera IDs. Global and per-camera values are bounded. Schedules use UTC weekdays (`0` Monday through `6` Sunday) and `HH:MM` windows. `maxBytes: 0` means no byte quota; retention still honors age and minimum-free-space settings. Locked evidence is never an eligible retention victim.

严格配置为 schema v1，最多接受 64 个稳定摄像机 ID。全局与逐路字段均有边界。计划表使用 UTC 星期（`0` 为周一、`6` 为周日）和 `HH:MM` 窗口。`maxBytes: 0` 表示不启用字节配额；时长和最低剩余空间策略仍有效。已锁定证据永远不是可清理项。

```json
{
  "schemaVersion": 1,
  "segmentSeconds": 60,
  "maxAgeHours": 720,
  "maxBytes": 0,
  "minFreeBytes": 1073741824,
  "cameras": [
    {
      "id": "entrance",
      "name": "Entrance",
      "policy": "continuous",
      "mainUrl": "rtsp://camera.example/stream",
      "subUrl": "",
      "stream": "main",
      "mode": "auto",
      "transport": "tcp",
      "segmentSeconds": 60,
      "maxAgeHours": 720,
      "maxBytes": 0,
      "preEventSeconds": 0,
      "schedule": []
    }
  ]
}
```

Policies are `continuous`, `scheduled`, `event`, and `off`; modes are `auto`, `copy`, and `transcode`. Auto mode probes the source and prefers stream copy for H.264/H.265. A failed compatible copy attempt falls back to bounded x264 transcoding. Commands use fixed argument vectors without a shell. URLs never appear in public responses, NVR audit events, status, or metric labels.

策略包括 `continuous`、`scheduled`、`event` 和 `off`；模式包括 `auto`、`copy` 和 `transcode`。自动模式先探测来源，对 H.264/H.265 优先码流复制；兼容复制失败后有界回退 x264 转码。命令使用固定参数数组且不经过 shell。URL 不会出现在公开响应、NVR 审计事件、状态或指标标签中。

## API and operations / API 与运维

All paths below are under `/api/v1/nvr` and inherit the M6 authentication, Host/Origin, rate-limit, and HTTPS boundary.

下列路径均位于 `/api/v1/nvr`，继承 M6 的认证、Host/Origin、限流和 HTTPS 边界。

| Method and path | Purpose / 用途 |
| --- | --- |
| `GET /health`, `GET /status` | Aggregate and per-camera health without endpoints / 不含端点的整体与逐路健康 |
| `GET /config`, `PUT /config` | Redacted read and strict atomic update / 脱敏读取与严格原子更新 |
| `GET /segments`, `GET /timeline` | Bounded UTC catalog query / 有界 UTC 目录查询 |
| `GET /media/{segment-id}` | MP4 playback with HTTP Range / 支持 HTTP Range 的 MP4 回放 |
| `PUT /locks/{segment-id}` | Evidence lock or unlock / 证据锁定或解锁 |
| `POST /events/{camera-id}` | Activate/deactivate an event-policy job / 激活或停用事件策略任务 |
| `GET /metrics` | Stable-label Prometheus metrics / 固定标签 Prometheus 指标 |

`GET /config` replaces stored endpoints with `rtsp://***`. Sending that document back with `PUT /config` preserves the existing private value for the same camera and field. A placeholder cannot create a new secret. Source changes must submit the complete new URL over the trusted authenticated connection.

`GET /config` 会把已存端点替换为 `rtsp://***`。将该文档通过 `PUT /config` 原样送回时，同一摄像机同一字段的私有值会被保留；占位符不能创建新密钥。变更来源时必须通过可信且已认证的连接提交完整新 URL。

On startup, valid partial MP4 files are finalized and cataloged; invalid or foreign fragments are quarantined. Orphan files and missing catalog rows are reconciled idempotently. A read-only or otherwise unwritable storage root fails closed. `SIGTERM` terminates active FFmpeg processes and lets the container supervise program/NVR shutdown separately.

启动时会封装并登记有效 MP4 残片，无效或不属于现有摄像机的残片进入隔离区。孤立文件与缺失目录记录会幂等对账。只读或不可写存储根目录会失败关闭。`SIGTERM` 会终止活动 FFmpeg 进程，容器分别监督节目与 NVR 关闭。

## Verification / 验证

The deterministic gate uses only an in-repository synthetic MediaMTX fixture and does not consume a private endpoint:

确定性门禁只使用仓库内合成 MediaMTX 夹具，不读取私有端点：

```powershell
pwsh ./tests/run-m8-nvr.ps1
# Extended release soak (six hours):
pwsh ./tests/run-m8-nvr.ps1 -SkipBuild -SoakMinutes 360
```

The short gate covers four concurrent cameras, copy/transcode, all recording policies, event pre-roll, unique IDs, MP4 decoding, WAL, arbitrary-phase kill/restart, recovery, quota/free-space retention, evidence locks, read-only storage, metrics, and redaction. A private 24-hour burn-in remains an operator release-qualification activity: provide URLs only through ignored local configuration, retain sanitized aggregate results, and never publish recordings or raw logs.

短门禁覆盖四路并发、复制/转码、全部录像策略、事件预录、唯一 ID、MP4 解码、WAL、任意阶段强杀/重启、恢复、配额/剩余空间保留、证据锁、只读存储、指标和脱敏。私有 24 小时耐久仍是操作者的发布资格活动：端点只通过忽略的本地配置提供，仅保留脱敏汇总结果，绝不发布录像或原始日志。
