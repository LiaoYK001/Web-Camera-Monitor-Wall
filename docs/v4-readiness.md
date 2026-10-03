# v4.0 maturity and release readiness / v4.0 成熟度与发布验收

## Objective / 目标

v4.0 is a maturity release for the complete monitoring product: coherent workflows, multi-client responsive UI, efficient playback, basic security, reliability, actionable errors and maintainable diagnostics. Existing features and green unit tests alone do not establish release readiness. Keep the Windows, Android, browser/PWA and Linux container product paths in scope.

v4.0 面向整个监控产品的成熟度：操作逻辑、多客户端响应式界面、播放性能、基本安全、鲁棒性、直观报错和持续开发诊断。已有功能或单元测试通过不能单独证明可发布；Windows、Android、浏览器/PWA 与 Linux 容器均在范围内。

The evidence workflow now has durable owner-bound export jobs, response-loss idempotency, explicit cancellation/restart recovery, per-camera resource authorization, large-file streaming, verified source digests, gap-aware manifests, exact audio preservation and atomic publication/locking. Archive selection changes remove stale media immediately, and query/action failures have bounded deadlines and explicit recovery. Focused validation uses real synthetic FFmpeg media, complete isolated Linux product services, fixture-based browser failures and actual Chromium/Android WebView playback; see [timeline evidence](timeline-evidence.md). Physical-camera/ARM/long-run qualification and the current revision's fresh Windows gate remain open.

证据工作流已新增持久化账号任务、响应丢失去重、显式取消/重启恢复、逐路资源授权、大文件流式传输、来源摘要校验、断档清单、精确音轨保留，以及发布/锁定事务。归档选择变化立即清除旧媒体，查询和操作失败均有时限与恢复入口。专项验证包括真实 FFmpeg 合成媒体、隔离完整 Linux 产品服务、浏览器故障夹具，以及 Chromium/Android WebView 实际播放，见[时间线与证据](timeline-evidence.md)。真实摄像机/ARM/长期验证及当前版本重新构建的 Windows 门禁仍待完成。

Use [OBS projectors](https://obsproject.com/kb/power-of-projectors) and [scene/source workflows](https://obsproject.com/kb/sources-guide) as references for deliberate scene selection, editing and separate outputs. Use [tinyCam settings](https://www.tinycammonitor.com/manual/app_settings.html) and [background/DVR behavior](https://www.tinycammonitor.com/manual/background_mode.html) as references for everyday camera monitoring and lifecycle behavior. These are workflow references; this product keeps independent NVR recording and does not turn Android into an unannounced recorder.

参考 OBS 的场景编排与独立投影，以及 tinyCam 的日常监控和生命周期操作。参考其用户操作逻辑；本产品继续采用独立 NVR 采集，Android 不会隐式开始后台录像。

## Evidence matrix / 证据与缺口

Every row needs current source review, failure-path tests and relevant real product checks. The existing evidence below is a starting point, not a completion claim. Record dates, commit, environment and limitations with each qualification result.

每行均需当前源码检查、失败路径测试及对应实际产品验收。下列已有证据只作为起点，尚不能宣告完成；验收结果需记录日期、提交、环境和边界。

| Area / 方向 | Required outcome / 必须实现 | Starting evidence / 已有证据 | Remaining qualification / 尚需验收 |
| --- | --- | --- | --- |
| Daily workflows / 日常操作 | Consistent discover → add → organize → monitor → playback flow, visible saves and recoverable failures / 发现、接入、编排、监控、回放一致；保存和失败状态明确 | SourceCatalog, go2rtc imports, Scenes, account/settings regression suites | Audit PTZ, device edits, exports and all destructive operations for duplicate actions, permissions and draft protection / 继续审查 PTZ、设备编辑、导出与破坏性操作 |
| Scene control / 场景控制 | Preview/program distinction, reusable named scenes, independent fixed projectors / 预览与节目明确；可命名复用场景、多个独立固定投影 | SceneCollection, ProjectorView, actual Windows two-projector smoke | Physical multi-display/DPI/fullscreen and deletion/restore during monitoring / 真实多显示器、DPI、全屏与值守中删除恢复 |
| Account continuity / 账号连续性 | Audio/output/view preferences and drafts behave predictably across refresh/restart; conflicts are explicit / 刷新重启后偏好一致，草稿和冲突处理明确 | Account, audio, monitor preferences; native Windows and MuMu restart checks | Two-device same-account edits, denied permissions, expired sessions and offline-to-online conflicts / 同账号多设备冲突、权限拒绝、会话过期与离线恢复 |
| Playback and weak networks / 播放与弱网 | Actual frame delivery, low-FPS tolerance, bounded retries, optional default-on optimization / 实际帧检测、低帧率容忍、有界重试、默认开启但可关闭优化 | WHEP/HLS/MSE logic, frame/optimization tests, synthetic H.264 emulator playback | Physical camera/codec matrix, real bandwidth restriction and loss, network changes, deliberate fallback / 真实摄像机编码、限速丢包、网络切换和回退 |
| Performance / 性能 | No duplicate decode paths; visibility-aware work; stable CPU/memory/socket counts with many sources / 无重复解码链；后台工作受控；多路下资源稳定 | Layout/audio/stats/polling regression suites | 4/9/16-camera budgets on reference devices, frame latency and 24-hour continuous observation / 参考设备多路性能预算、帧延迟和 24 小时观察 |
| Control resilience / 控制同步鲁棒性 | Valid snapshot before online; bounded jittered retries, timeouts, offline pause, safe resume/cleanup / 有效场景才上线；有界渐进重试、超时、断网暂停、恢复和清理 | sceneEvents + control-recovery suite; authenticated native checks | Long sleep, network adapter switch and real server restart while media/recording continue / 长休眠、网卡切换、录像播放中的真实服务重启 |
| Recording/playback / 录像回放 | Capture survives editor/analytics failure; gaps, storage pressure and export integrity are clear / 采集不依赖编辑分析；断档、磁盘压力与导出完整性明确 | NVR timeline/service and export/soak test infrastructure | Full disk, interrupted exports, corrupted segments, clock/timezone and retention recovery / 满盘、中断导出、损坏片段、时钟时区、保留策略恢复 |
| Basic security / 基本安全 | Auth/Origin/RBAC, safe paths and bounded inputs; credentials kept out of diagnostic exports / 认证、来源校验、权限、路径和输入边界；诊断不泄密 | Public audits, proxy/security tests, private config volumes | Audit all support exports and error payloads; triage newly disclosed dependencies; verify LAN trust boundary / 全部诊断与报错审查、依赖告警、局域网信任边界 |
| Responsive visuals / 响应式与美观 | Shared hierarchy, keyboard/touch usability, clear focus and reduced motion / 统一层级、键盘触屏、焦点和减少动效 | Workspace navigation/modal/mobile/settings tests | Every workspace at phone/tablet/desktop widths, magnification, contrast and screen-reader review / 全页面手机平板桌面、放大对比度和读屏审查 |
| Actionable errors / 直观报错 | Explain failure, affected function and safe next action; retain useful state / 解释原因、影响和下一步；保留可恢复状态 | ProblemCenter, source/media issues, explicit retry UI | Permission/network/timeout/disk cases in every workspace and prevention of false success / 每页权限、网络、超时、磁盘故障及虚假成功排查 |
| Developer support / 开发者调试 | Opt-in bounded counters, exact build/client identity, safe export, reproducible failures / 按需开启、有界计数、构建与客户端标识、安全导出、可复现故障 | Settings control diagnostics; focused failure fixtures | Unified redacted diagnostics across media, services and native logs with meaningful timestamps / 媒体、服务及原生日志统一脱敏诊断与时间关联 |
| Sustainable development / 持续开发 | Clear module boundaries, pinned dependencies, bilingual changes, CI gates tied to behavior / 模块边界、依赖锁定、双语变更、行为对应 CI | AGENTS, locked submodules, public CI and native/emulator gates | Complete architecture/API ownership review and eliminate duplicate state/lifecycle implementations / 完整架构 API 归属审查，消除重复状态和生命周期逻辑 |
| Installation and updates / 安装升级 | Verified updates require confirmation, backup and normal shutdown; data retained and recovery usable / 校验、确认、备份、正常停服、数据保留及恢复 | v3.5 local two-version NSIS and public provider download checks | Two actual public-feed v4 candidates; failure injection; clean Windows 10/11 and physical Android qualification / v4 两版公开源升级、故障注入、干净 Win10/11 与安卓真机 |

## Control recovery and debugging / 控制恢复与调试

Core currently emits scene schema v6 (explicit `audioInputs`) and accepts legacy v5. WebUI event validation, scene types, local profile import/export and synchronized scene caching accept both without rewriting audio selections. Unknown future versions fail validation. The v2 field-sync service now validates both versions, preserves the actual SQLite version and upgrades explicit inputs without losing the legacy output slot. The independent Qt model retains audio settings during layout/local-save operations. See [the v6 contract](scene-schema-v6.md) for limits and migration behavior.

当前 Core 输出场景 schema v6（显式 `audioInputs`），同时接受 v5。WebUI 类型、事件校验、本地配置导入导出与同步缓存兼容两版；未知新版本拒绝。v2 字段同步服务已补齐两版校验、SQLite 实际版本保存及显式音轨升级，保留旧输出槽位；独立 Qt 模型在布局编辑与本地保存时保留音频设置。音轨边界与迁移行为见 v6 契约。

The 2026-10-03 contract work is qualified by Python service tests, Chromium encrypted-queue tests (reload/retry, two-window saves, overlapping sync calls and explicit conflicts), and an actual bundled Windows runtime HTTP check: two signed device enrollments, scoped credential-free grants, multi-track save/idempotent retry/conflict and persistence after normal restart. Qt model tests run in the existing Linux compile image with dependency pins disabled for compile diagnostics; this is not a Qt release/media qualification. The main UI now integrates [paired offline device workspaces](offline-workspace.md), atomic layout/queue saving, Settings conflict choices and deliberate copying to server Preview. Actual Windows UI pairing/decryption/upload/reload/Preview checks supplement the synthetic browser failure cases. The MuMu WebView 110 debug APK regression passes with compatible request deadlines. Physical multi-track audio, two real client devices, ARM and long-run qualification remain open.

2026-10-03 契约验证包括 Python 服务测试、Chromium 加密队列测试（刷新重试、双窗口保存、重叠同步与显式冲突），以及 Windows 捆绑运行时真实 HTTP 检查：两个签名配对、限定设备范围的无凭据授权、多音轨保存、幂等重试、冲突和正常重启后保留。Qt 模型使用现有 Linux 编译镜像关闭依赖锁作编译诊断，不等于 Qt 发布或媒体验收。正式 UI 已接入[配对离线设备工作区](offline-workspace.md)、布局/队列原子保存、设置中的冲突选择及明确复制到服务器 Preview；Windows 实际界面的配对、解密、上传、刷新与复制检查补充浏览器失败夹具。兼容请求时限后 MuMu WebView 110 debug APK 回归通过；真实多音轨播放、两台实机、ARM 和长期运行验收仍待完成。

The control subscription waits up to 15 seconds for the WebSocket upgrade and another 15 seconds for a structurally valid scene. Short-lived connections retain exponential retry delay (500 ms baseline, ±20% jitter, capped at 30 seconds); only 30 seconds of established scene delivery resets the delay. Offline devices and failed background connections do not retry until network/foreground returns. A connected subscription is retained during short background intervals; returning after 30 seconds refreshes it. Neither these timers nor the manual control reconnect starts/stops video, audio or NVR services.

控制订阅等待连接和有效场景各最多 15 秒。短暂连接不会重置渐进重试（起始 500 毫秒、±20% 抖动、上限 30 秒）；有效订阅持续 30 秒才重置。断网或后台失败时暂停重试，网络恢复或返回前台后重试。短暂后台保留正常订阅；超过 30 秒后返回会刷新订阅。自动恢复及手动重连只控制场景同步，不启停媒体或 NVR 服务。

In Settings → Developer diagnostics, enable the current-window control counters, reproduce the issue, and copy the counters or manually copy the expanded data. The session-only diagnostic schema contains fixed status/reason codes, timestamps and counts. It excludes URLs, arbitrary transport error/close messages, scene/source payloads, account names and credentials. Counters disappear when a subscription closes and never persist to account storage. A maximum of 32 active records is retained per window; disabled diagnostics do not run an extra polling timer. Browser failures, native lifecycle checks and synthetic video tests remain distinct from physical camera qualification.

设置 → 开发者诊断中按需显示当前窗口计数，复现问题后复制或手动选取数据。会话内诊断只含固定状态码、时间和计数，不保存地址、任意连接报错、场景、账号或密钥。关闭订阅即移除，单窗口最多保留 32 条；未开启时不增加轮询。浏览器故障夹具、原生生命周期和合成视频测试均不等同真实摄像机验收。

## Release gate / 发布门槛

Recording maturity now includes durable evidence jobs, audio-preserving exact exports, large media streaming, per-camera playback resource authorization, owner-bound snapshots/leases and conditional resume. On 2026-10-03 the complete isolated Linux product verified a 117 MiB synthetic H.264 export and 16 slow readers with bounded core RSS and responsive authenticated control. Fresh Windows candidates for evidence, media proxy, archive controls, archive audio/visibility, field-aware account preferences and first-read recovery passed native, main-window, ASAR and actual NSIS install/uninstall checks (runs 37118305163, 37120673852, 37122169477, 37125358436, 37134460019 and 37137488039). On 2026-10-04, compact preference writes passed 37 cluster tests, 74 Chromium checks, production Linux API/UI checks and 16 installed MuMu APK checks; their own fresh Windows candidate remains required. These are host/synthetic checks; camera, clean Windows 10/11, Android ARM, prolonged storage and every-row qualification remain open.

录像成熟度已增加持久化证据任务、精确导出声音、大媒体流式传输、逐摄像机回放资源授权、绑定账号的截图/租约及条件续传。2026-10-03 的隔离完整 Linux 产品验证了 117 MiB 合成 H.264 导出，以及 16 个慢速读取下有界核心 RSS 和正常认证控制。证据、媒体代理、归档控制、声音/可见性、账号偏好字段合并及首次读取故障恢复的全新 Windows 候选已通过原生、主窗口、ASAR、实际 NSIS 安装卸载（运行 37118305163、37120673852、37122169477、37125358436、37134460019、37137488039）。2026-10-04 的紧凑偏好请求已通过 37 项 cluster、74 项 Chromium、Linux 生产 API/UI 及已安装 MuMu APK 的 16 项检查，仍需自己的全新 Windows 候选验证。这些为主机/合成检查，真实摄像机、干净 Windows 10/11、Android ARM、长期存储及全部方向验收仍待完成。

Do not mark v4.0 ready while any matrix row lacks sufficient evidence. Maintain existing Docker/Podman and Direct-only operation. Record the exact tested artifacts and source revisions, attach matching source/licenses/SBOM/digests, and separately report Windows 10/11, Android/ARM, cameras, LAN and long-run results. No v4 tag or installer is published merely because one incremental PR passes.

证据不足的方向不能标记为 v4.0 完成。保留 Docker/Podman 和仅 Direct 模式；记录实测产物、源码版本、许可证、SBOM、摘要，并分别报告系统、真机、摄像机、局域网与长时间验证。本轮 PR 通过不会自动发布 v4 标签或安装包。
