# Timeline, Playback & Evidence / 时间线、回放与证据

M9 turns the M8 UTC archive catalog into an operator workflow. The React workspace is available from **录像时间线** or `#archive`; all browser requests remain same-origin under `/api/v1/nvr/*` and therefore inherit the product authentication, Origin and RBAC boundary. The loopback NVR listener is never published.

M9 将 M8 UTC 归档目录转化为值守工作流。React 工作区可通过“录像时间线”或 `#archive` 打开；全部浏览器请求仍使用 `/api/v1/nvr/*` 同源路径，因此继承 产品认证、Origin 与 RBAC 边界。仅回环 NVR 监听器始终不发布。

## Timeline and playback / 时间线与回放

`GET /api/v1/nvr/timeline?from=<utc-ms>&to=<utc-ms>&cameraId=<id>` accepts a positive range of at most 31 days and returns at most the caller-selected known camera IDs. Storage remains UTC. Each camera result contains ordered segments, explicit offline/missing/corrupt gaps, the oldest retained boundary, and the recorded main/sub profile. Display conversion is performed with the browser `Intl` time-zone database; UTC keys and query boundaries never change when the operator selects another zone.

`GET /api/v1/nvr/timeline?from=<utc-ms>&to=<utc-ms>&cameraId=<id>` 接受最长 31 天的正向范围，并且只返回调用方选择的已知摄像机 ID。存储始终为 UTC。逐路结果包含有序片段、明确的离线/缺失/损坏断档、最早保留边界和已录主/辅码流。显示转换使用浏览器 `Intl` 时区数据库；操作者切换显示时区时，UTC 键和查询边界不会改变。

The UI opens one to four fragmented MP4 players with HTTP Range. One player is the clock master; every 250 ms the others are compared in global UTC and corrected only when drift exceeds 250 ms. Play, pause, seek, 0.25×–4× speed, and 30 FPS frame-step operate on the shared UTC cursor. A missing or corrupt segment becomes a visible gap and playback advances to the next available segment. The UI obtains 40-second playback leases and renews them every 20 seconds; transfer reader locks and unexpired leases both keep retention from deleting active media.

界面可打开 1–4 个支持 HTTP Range 的 fragmented MP4 播放器。一路作为时钟主控；每 250 ms 以全局 UTC 比较其他播放器，仅在偏差超过 250 ms 时纠正。播放、暂停、跳转、0.25×–4× 倍速和 30 FPS 逐帧均作用于共享 UTC 游标。缺失或损坏片段显示为明确断档，并在下一可用片段恢复。UI 获取 40 秒回放租约并每 20 秒续租；传输读锁和未过期租约都会阻止保留任务删除活动媒体。

## Bounded derived media / 有界派生媒体

`GET /thumbnails/{segment-id}?offsetMs=<n>` uses at most four concurrent FFmpeg jobs, scales to 320 pixels wide, and caches at most 1,000 JPEGs for 24 hours. `POST /snapshots` accepts only a catalog segment ID and bounded offset, copies a generated JPEG into the evidence root, returns its SHA-256 and a fixed download URL, and emits an audit event. Neither operation accepts a path or source URL.

`GET /thumbnails/{segment-id}?offsetMs=<n>` 最多使用四个并发 FFmpeg 任务，缩放到 320 像素宽，并最多缓存 1,000 张 JPEG、保留 24 小时。`POST /snapshots` 只接受目录中的片段 ID 和有界偏移，将生成的 JPEG 写入证据根目录，返回 SHA-256 与固定下载 URL，并产生审计事件。两种操作均不接受路径或来源 URL。

## Evidence export / 证据导出

The WebUI submits `POST /api/v1/nvr/exports/jobs`, then reads `GET /exports/jobs` or `GET /exports/jobs/{id}`. `POST /exports/jobs/{id}/cancel` cancels queued or active conversion. Jobs are persisted in the private NVR SQLite catalog, survive page navigation/reload and retain completed results after service restart. A stable `requestId` is unique per authenticated owner: retrying the same request returns its original job; changing its range returns a conflict. An uncertain browser submission is retained per account in private tab storage and recovered explicitly. Interrupted jobs require a new explicit export rather than automatically rerunning.

WebUI 使用 `POST /api/v1/nvr/exports/jobs` 提交，再通过 `GET /exports/jobs` 或 `GET /exports/jobs/{id}` 查询；`POST /exports/jobs/{id}/cancel` 取消排队或正在转换的任务。任务保存在私有 NVR SQLite 目录中，切页、刷新后可恢复，服务重启后保留已完成结果。同一账号的稳定 `requestId` 用于去重：相同请求返回原任务，改变范围返回冲突。结果待确认的浏览器提交按账号暂存于私有标签页存储，由用户显式恢复。重启中断任务需要用户重新导出，不自动执行。

The service runs one export worker with at most eight outstanding jobs and lists the most recent 50 jobs for their owner. It accepts one to four camera IDs, a positive range of at most 24 hours and at most 5,000 selected segments per camera. The UI defaults to ten seconds, adjustable from one second to one hour. Legacy synchronous `POST /exports` remains for small existing clients; it retains the product proxy's 30-second deadline and should not be used for long conversions.

服务仅使用一个导出 worker，最多八个未完成任务，按任务账号展示最近 50 项。请求支持 1–4 路摄像机、最长 24 小时的正向范围，每路最多选择 5,000 个片段。界面默认十秒，可调整为一秒至一小时。旧同步 `POST /exports` 为已有小型调用保留，仍受产品代理 30 秒时限约束，长转换应使用后台任务接口。

Job results are compact summaries with output hashes, total gap counts and at most ten coverage examples per file; the downloadable manifest retains complete source/coverage details. This keeps history bounded even for a full-day export. Files exceeding the existing 64 MiB product response bound fail explicitly before publication, preserving source locks and recording data; shorten the range until streaming downloads are implemented.

任务结果为精简摘要，保留输出摘要、断档总数及每个文件最多十项覆盖示例；可下载清单保留完整来源与覆盖详情，避免整日导出的历史列表失控。超过现有产品 64 MiB 响应边界的文件在发布前明确失败，不改变来源证据锁、不删除录像；大文件流式下载完成前请缩短范围。

Fast mode copies complete compatible segments and reports expanded effective boundaries, per-camera coverage and explicit gaps/overlaps. The resulting file contains existing media only; gaps are not a continuous UTC recording. Exact mode requires full non-overlapping coverage on every selected camera, retains available audio as AAC, encodes H.264 and validates actual video duration within one output frame plus two milliseconds of rounding. Every FFmpeg process has a five-minute deadline, fixed argument vectors and explicit cancellation. Concatenation supports Unicode, spaces and apostrophes in private storage paths.

快速模式复制完整兼容片段，报告扩展后的实际边界、逐路覆盖范围及断档/重叠；文件只包含已有媒体，断档不应被解释为连续 UTC 录像。精确模式要求每路在请求范围内完整且不重叠，将已有音轨保留为 AAC、视频编码为 H.264，并验证实际视频时长与请求的误差不超过一个输出帧加两毫秒舍入容差。FFmpeg 使用固定参数数组、五分钟进程时限和显式取消，私有存储路径支持中文、空格和单引号。

Schema-v2 manifests contain build identity (`unknown` only when an external launcher supplies no build version), requested/effective UTC ranges, source IDs and verified source SHA-256/size, output track codecs and SHA-256, actual duration, coverage gaps and fixed product download URLs. They omit source URLs, credentials, filesystem paths and FFmpeg output. Storage preflight preserves the configured free-space reserve on the export volume; exact encoding uses an input-size estimate, not a guaranteed output-size prediction. Failure/cancellation publishes no downloads or evidence locks. Source reader pins protect every selected camera during conversion; source locks, catalog publication and completed job result commit together.

schema-v2 清单包含构建版本（仅外部启动器未提供版本时为 `unknown`）、请求/实际 UTC 范围、来源 ID 与校验后的来源 SHA-256/字节数、输出轨道编码/摘要、实际时长、覆盖断档和固定产品下载地址，不包含源 URL、凭据、文件系统路径或 FFmpeg 输出。空间预检在导出所在卷保留配置的剩余空间下限，精确编码采用输入大小估计，不保证输出大小预测。失败/取消不会发布下载或证据锁。转换期间所有摄像机源片段均受读保护；证据锁、导出目录发布和任务完成结果在同一事务提交。

## Authorization, audit and deletion / 授权、审计与删除

The core replaces client-supplied `X-WebObs-Nvr-Principal` with its authenticated principal and forwards only that internal identity, validated Range and content type. With RBAC enabled the NVR checks `export.create` against every camera at submission, execution, job retrieval and download. Status, cancellation and new artifacts belong to the submitting account, including when another account is an administrator. Existing pre-migration artifacts without an owner retain their legacy authenticated playback access. Deployments without RBAC retain the product authentication/Origin boundary. Exporting locks source evidence by default under the export permission; unlocking remains a separate `recording.lock` operation. Playback lease release requires playback permission, not recording-delete permission.

核心将用户提交的 `X-WebObs-Nvr-Principal` 替换为已认证身份，只转发内部身份、校验后的 Range 和内容类型。启用 RBAC 时，NVR 在提交、执行、读取任务和下载时逐路检查 `export.create`。状态、取消及新文件属于提交账号，其他管理员账号也不能读取。迁移前未记录归属的旧文件保留原认证回放访问；未启用 RBAC 的部署保留产品认证/Origin 边界。导出权限默认允许锁定来源证据，解锁仍需独立的 `recording.lock`；释放回放租约要求回放权限，不要求删除录像权限。

Playback, snapshots, completed exports, downloads, lock/unlock, retention and deletion emit stable-ID audit events. Locked or pinned segments cannot be deleted; deletion rechecks the catalog under the same reader lock as unlink. The UI pauses and releases its leases before deleting a selected unlocked segment. This remains irreversible.

回放、截图、完成导出、下载、锁定/解锁、保留和删除写入稳定 ID 审计。锁定或受读保护的片段不可删除；删除在与移除文件相同的读锁内重新检查目录状态。界面删除当前未锁定片段前暂停并释放自身租约，删除仍不可撤销。

## v4 evidence validation / v4 证据验证

`python tests/test_nvr_evidence.py` exercises real synthetic H.264/AAC media, silent input, half-open ranges, gaps, Unicode/apostrophe paths, source protection, cancellation, disk pressure, atomic failure rollback, owner checks, interrupted restart and shutdown refusal. `python tests/test_nvr_evidence_integration.py --docker <executable> --image <candidate>` uses an isolated complete product image to validate core identity replacement, every-camera scopes, owner-only operations/downloads, idempotency, real output hashes, viewer lease release and restart persistence. No external camera or existing recordings are used.

`python tests/test_nvr_evidence.py` 使用真实合成 H.264/AAC 媒体检查无声输入、半开时间范围、断档、中文/单引号路径、来源保护、取消、磁盘不足、失败事务回滚、归属、重启中断和拒绝未完成停服。`python tests/test_nvr_evidence_integration.py --docker <程序> --image <候选>` 使用隔离完整产品镜像检查核心身份替换、逐路权限、归属/下载、去重、实际输出摘要、查看者租约释放及重启恢复，不连接外部摄像机、不使用现有录像。

The focused Chromium suite is `nvr-evidence.spec.ts`; its media elements and backend are fixtures, not camera qualification. The Windows native runtime gate additionally exercises bundled FFmpeg/Python, authenticated export and result restoration with `native-evidence-contract.cjs`. A fresh native core build is required; an earlier runtime cannot validate the new principal header. Large-file streaming beyond the current 64 MiB proxy response bound, exhaustive playback-resource scopes, physical-camera/ARM/DST behavior and prolonged recording/storage fault qualification remain v4 work.

Chromium 专项为 `nvr-evidence.spec.ts`，其媒体元素与后端为夹具，不代替摄像机验收。Windows 原生门禁新增 `native-evidence-contract.cjs`，使用捆绑 FFmpeg/Python 验证认证导出与结果恢复；必须重新构建原生核心，旧运行时无法验证新增身份头。超过当前代理 64 MiB 响应边界的大文件流式传输、完整回放资源权限、真实摄像机/ARM/夏令时行为，以及长期录像/存储故障验收仍属于 v4 后续工作。

## Acceptance / 验收

```powershell
pwsh ./tests/run-m9-timeline.ps1
```

The deterministic gate records four synthetic cameras, freezes the archive, measures 40 local timeline queries against a 500 ms p95 budget, verifies UTC/leap-day and corrupt-gap behavior, HTTP Range, JPEG thumbnail/snapshot hashes, four-camera fast export, exact-boundary export, logical program association, manifest and file SHA-256, FFprobe playback, evidence lock/delete conflicts, and credential/path-free audit events. The published p95 number is environment-specific and must be remeasured on deployment storage. Browser synchronization uses the explicit 250 ms correction threshold; production release qualification should additionally observe a real four-player session across target browsers and daylight-saving zones.

确定性门禁录制四路合成摄像机并冻结归档，测量 40 次本地时间线查询与 500 ms p95 预算，验证 UTC/闰日及损坏断档、HTTP Range、JPEG 缩略图/截图哈希、四路快速导出、精确边界导出、逻辑节目录像关联、清单与文件 SHA-256、FFprobe 播放、证据锁/删除冲突及不含凭据/路径的审计事件。公开 p95 数值与环境相关，部署存储上必须重新测量。浏览器同步使用明确的 250 ms 纠正阈值；生产发布资格还应在目标浏览器及夏令时时区观察真实四播放器会话。

The current-worktree image regression on 2026-08-23 passed the complete gate and measured 4.8 ms p95 for 40 local timeline queries. The result records this development machine and Docker storage only; it does not replace target-host storage measurement or real-browser/DST observation.

2026-08-23 的当前工作树镜像回归通过完整门禁，40 次本地时间线查询 p95 为 4.8 ms。该结果只记录本开发机与 Docker 存储，不替代目标主机存储测量及真实浏览器/夏令时观察。
