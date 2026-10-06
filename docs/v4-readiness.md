# v4.0 maturity and release readiness / v4.0 成熟度与发布验收

## Objective / 目标

v4.0 is a maturity release for the complete monitoring product: coherent workflows, multi-client responsive UI, efficient playback, basic security, reliability, actionable errors and maintainable diagnostics. Existing features and green unit tests alone do not establish release readiness. Keep the Windows, Android, browser/PWA and Linux container product paths in scope.

v4.0 面向整个监控产品的成熟度：操作逻辑、多客户端响应式界面、播放性能、基本安全、鲁棒性、直观报错和持续开发诊断。已有功能或单元测试通过不能单独证明可发布；Windows、Android、浏览器/PWA 与 Linux 容器均在范围内。

The evidence workflow now has durable owner-bound export jobs, response-loss idempotency, explicit cancellation/restart recovery, per-camera resource authorization, large-file streaming, verified source digests, gap-aware manifests, exact audio preservation and atomic publication/locking. Archive selection changes remove stale media immediately, and query/action failures have bounded deadlines and explicit recovery. Focused validation uses real synthetic FFmpeg media, complete isolated Linux product services, fixture-based browser failures and actual Chromium/Android WebView playback; see [timeline evidence](timeline-evidence.md). Physical-camera/ARM/long-run qualification and the current revision's fresh Windows gate remain open.

证据工作流已新增持久化账号任务、响应丢失去重、显式取消/重启恢复、逐路资源授权、大文件流式传输、来源摘要校验、断档清单、精确音轨保留，以及发布/锁定事务。归档选择变化立即清除旧媒体，查询和操作失败均有时限与恢复入口。专项验证包括真实 FFmpeg 合成媒体、隔离完整 Linux 产品服务、浏览器故障夹具，以及 Chromium/Android WebView 实际播放，见[时间线与证据](timeline-evidence.md)。真实摄像机/ARM/长期验证及当前版本重新构建的 Windows 门禁仍待完成。

Use [OBS projectors](https://obsproject.com/kb/power-of-projectors) and [scene/source workflows](https://obsproject.com/kb/sources-guide) as references for deliberate scene selection, editing and separate outputs. Use [tinyCam settings](https://www.tinycammonitor.com/manual/app_settings.html) and [background/DVR behavior](https://www.tinycammonitor.com/manual/background_mode.html) as references for everyday camera monitoring and lifecycle behavior. These are workflow references; this product keeps independent NVR recording and does not turn Android into an unannounced recorder.

参考 OBS 的场景编排与独立投影，以及 tinyCam 的日常监控和生命周期操作。参考其用户操作逻辑；本产品继续采用独立 NVR 采集，Android 不会隐式开始后台录像。

## Evidence matrix / 证据与缺口

2026-10-05 交付范围：当前容器重启/异常退出修复留到 v4.0，暂不操作 v3.5 热修。v4 基线之后使用 `vA.B.C` 快速 bug/安全补丁，优先 Windows/Android，见[补丁规则](patch-releases-v4.md)。新增验收项为实际 `4.0.0 → 4.0.1 → 4.0.2`、账号/数据保留、Windows 差量失败回退及 Android 同密钥/错误密钥与版本码；版本/协议测试和候选构建不能替代安装验收。[Android 应用内更新](android-updates.md)已实现可关闭的自动检查/下载、验证、确认安装与恢复，隔离包实测与公开源/生产包/真机验收分别记录。

Hold the restart fixes for v4.0 and qualify regular v4+ patches through actual successive installed upgrades, retention and failure paths. Version/protocol tests and candidate builds are separate evidence. Android verified in-app delivery is implemented; isolated installed-upgrade evidence remains distinct from public-feed, production-package and physical-device qualification.

2026-10-05 Android 更新专项：独立 MuMu API 35 x86_64 包实测系统下载/错误摘要签名包名版本/降级/丢失附件/超量/取消、临时查询失败、暂存丢失、进程重启、权限及草稿阻止、系统确认 `4.0.0 → 4.0.1 → 4.0.2` 和连接/偏好/WebView Cookie 保留通过；4 项相关 Chromium、release JUnit/lint/签名检查通过。使用私密一次性密钥与合成 feed，未改已有产品或发布。公开源、生产包、Wi-Fi/实际断网、磁盘故障及 ARM 真机继续待验收，见 [Android 更新](android-updates.md)。

The isolated Android update gate passed real system download/confirmed successive installation, failure/recovery/retention checks and related unit/lint/browser validation. Public-feed, production-package, actual network/storage failures and physical ARM gates remain open.

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

Studio TAKE now uses [stable runtime identities](studio-runtime-identities.md) for long and dotted source/item IDs and distinct nested item instances. Shared sources stay deduplicated independently of layer order. Existing snapshots and account records are retained; ambiguous historical counters require an explicit review of source settings after TAKE.

Studio TAKE 为较长/含点标识和嵌套项实例采用[稳定运行标识](studio-runtime-identities.md)，来源复用不再取决于层级顺序。原快照与账号记录保留；旧序号存在歧义，TAKE 后需明确核对来源设置。

Core currently emits scene schema v6 (explicit `audioInputs`) and accepts legacy v5. WebUI event validation, scene types, local profile import/export and synchronized scene caching accept both without rewriting audio selections. Unknown future versions fail validation. The v2 field-sync service now validates both versions, preserves the actual SQLite version and upgrades explicit inputs without losing the legacy output slot. The independent Qt model retains audio settings during layout/local-save operations. See [the v6 contract](scene-schema-v6.md) for limits and migration behavior.

当前 Core 输出场景 schema v6（显式 `audioInputs`），同时接受 v5。WebUI 类型、事件校验、本地配置导入导出与同步缓存兼容两版；未知新版本拒绝。v2 字段同步服务已补齐两版校验、SQLite 实际版本保存及显式音轨升级，保留旧输出槽位；独立 Qt 模型在布局编辑与本地保存时保留音频设置。音轨边界与迁移行为见 v6 契约。

The 2026-10-03 contract work is qualified by Python service tests, Chromium encrypted-queue tests (reload/retry, two-window saves, overlapping sync calls and explicit conflicts), and an actual bundled Windows runtime HTTP check: two signed device enrollments, scoped credential-free grants, multi-track save/idempotent retry/conflict and persistence after normal restart. Qt model tests run in the existing Linux compile image with dependency pins disabled for compile diagnostics; this is not a Qt release/media qualification. The main UI now integrates [paired offline device workspaces](offline-workspace.md), atomic layout/queue saving, Settings conflict choices and deliberate copying to server Preview. Actual Windows UI pairing/decryption/upload/reload/Preview checks supplement the synthetic browser failure cases. The MuMu WebView 110 debug APK regression passes with compatible request deadlines. Physical multi-track audio, two real client devices, ARM and long-run qualification remain open.

2026-10-03 契约验证包括 Python 服务测试、Chromium 加密队列测试（刷新重试、双窗口保存、重叠同步与显式冲突），以及 Windows 捆绑运行时真实 HTTP 检查：两个签名配对、限定设备范围的无凭据授权、多音轨保存、幂等重试、冲突和正常重启后保留。Qt 模型使用现有 Linux 编译镜像关闭依赖锁作编译诊断，不等于 Qt 发布或媒体验收。正式 UI 已接入[配对离线设备工作区](offline-workspace.md)、布局/队列原子保存、设置中的冲突选择及明确复制到服务器 Preview；Windows 实际界面的配对、解密、上传、刷新与复制检查补充浏览器失败夹具。兼容请求时限后 MuMu WebView 110 debug APK 回归通过；真实多音轨播放、两台实机、ARM 和长期运行验收仍待完成。

The control subscription waits up to 15 seconds for the WebSocket upgrade and another 15 seconds for a structurally valid scene. Short-lived connections retain exponential retry delay (500 ms baseline, ±20% jitter, capped at 30 seconds); only 30 seconds of established scene delivery resets the delay. Offline devices and failed background connections do not retry until network/foreground returns. A connected subscription is retained during short background intervals; returning after 30 seconds refreshes it. Neither these timers nor the manual control reconnect starts/stops video, audio or NVR services.

控制订阅等待连接和有效场景各最多 15 秒。短暂连接不会重置渐进重试（起始 500 毫秒、±20% 抖动、上限 30 秒）；有效订阅持续 30 秒才重置。断网或后台失败时暂停重试，网络恢复或返回前台后重试。短暂后台保留正常订阅；超过 30 秒后返回会刷新订阅。自动恢复及手动重连只控制场景同步，不启停媒体或 NVR 服务。

Shared [request deadlines](request-deadlines.md) also bound the UI wait when a transport ignores cancellation and retain the original timeout/owner reason. A client timeout never implies that a server mutation was cancelled; explicit job cancellation and unconfirmed-result recovery remain necessary.

共享的[请求时限](request-deadlines.md)在传输忽略取消时仍限制界面等待，并保留真实超时或所属对象的取消原因。客户端超时不代表服务端修改已取消；仍需明确的任务取消与未确认结果恢复。

In Settings → Developer diagnostics, enable the current-window control counters, reproduce the issue, and copy the counters or manually copy the expanded data. The session-only diagnostic schema contains fixed status/reason codes, timestamps and counts. It excludes URLs, arbitrary transport error/close messages, scene/source payloads, account names and credentials. Counters disappear when a subscription closes and never persist to account storage. A maximum of 32 active records is retained per window; disabled diagnostics do not run an extra polling timer. Browser failures, native lifecycle checks and synthetic video tests remain distinct from physical camera qualification.

设置 → 开发者诊断中按需显示当前窗口计数，复现问题后复制或手动选取数据。会话内诊断只含固定状态码、时间和计数，不保存地址、任意连接报错、场景、账号或密钥。关闭订阅即移除，单窗口最多保留 32 条；未开启时不增加轮询。浏览器故障夹具、原生生命周期和合成视频测试均不等同真实摄像机验收。

## Release gate / 发布门槛

2026-10-05 设备接入后续：更换地址清除旧凭据、拒绝晚到检测、提交去重和删除权限失败均有失败回归。
新增[设备接入恢复](device-onboarding-recovery.md)、20 秒等待、未确认创建的固定 ID 核对、
账号偏好字段合并和草稿刷新保护；建档、go2rtc 导入及控制/录音向原生安装预检报告在途工作。
部署及实体设备验收仍独立记录，不能由回归检查推断整体完成。

Device-onboarding follow-up reproduces credential destination, late detection, duplicate
submission and permission failure. Bounded ownership, fixed-ID unconfirmed recovery,
account-field merging and draft rebase protect the workflow; in-flight import/control/audio
work is reported to native installation preflight. Deployment and device qualification remain separate.

Recording maturity now includes durable evidence jobs, audio-preserving exact exports, large media streaming, per-camera playback resource authorization, owner-bound snapshots/leases and conditional resume. On 2026-10-03 the complete isolated Linux product verified a 117 MiB synthetic H.264 export and 16 slow readers with bounded core RSS and responsive authenticated control. Fresh Windows candidates for evidence, media proxy, archive controls, archive audio/visibility, field-aware account preferences and first-read recovery passed native, main-window, ASAR and actual NSIS install/uninstall checks (runs 37118305163, 37120673852, 37122169477, 37125358436, 37134460019 and 37137488039). Compact preference writes subsequently passed their own full Windows candidate (37140271869), supplementing 37 cluster tests, 74 Chromium checks, production Linux API/UI checks and 16 installed MuMu APK checks. These are host/synthetic checks; camera, clean Windows 10/11, Android ARM, prolonged storage and every-row qualification remain open.

录像成熟度已增加持久化证据任务、精确导出声音、大媒体流式传输、逐摄像机回放资源授权、绑定账号的截图/租约及条件续传。2026-10-03 的隔离完整 Linux 产品验证了 117 MiB 合成 H.264 导出，以及 16 个慢速读取下有界核心 RSS 和正常认证控制。证据、媒体代理、归档控制、声音/可见性、账号偏好字段合并及首次读取故障恢复的全新 Windows 候选已通过原生、主窗口、ASAR、实际 NSIS 安装卸载（运行 37118305163、37120673852、37122169477、37125358436、37134460019、37137488039）。紧凑偏好请求随后也通过自己的完整 Windows 候选（37140271869），补充此前 37 项 cluster、74 项 Chromium、Linux 生产 API/UI 及已安装 MuMu APK 的 16 项检查。这些为主机/合成检查，真实摄像机、干净 Windows 10/11、Android ARM、长期存储及全部方向验收仍待完成。

2026-10-04: Identifier and account-audio follow-up fixes retain own source records, all valid audio controls beyond 256, and a received frozen Program during slower Studio reads/saves. The audio truncation and both Program ordering cases failed before their fixes; 61 related Chromium regressions, typecheck/build, actual Linux H.264/API/UI checks and 17 installed MuMu development APK checks passed. Fresh complete Windows verification is tracked in PR #37; failed earlier candidates are not qualification. No stable installer/feed, APK, tag or GHCR release is published by this follow-up.

2026-10-04：来源标识与声音偏好的后续修复保留自己的来源记录、256 路之后全部有效声音设置，以及较慢 Studio 读取/保存期间已收到的实际 Program。声音截断和两个 Program 时序用例在修复前失败；61 项相关 Chromium、类型/构建、Linux 实际 H.264/API/UI 和已安装 MuMu 开发 APK 的 17 项检查通过。完整 Windows 新候选结果记录在 PR #37，先前失败的候选不计验收。本次后续修复不发布稳定安装包/更新源、APK、标签或 GHCR。

Do not mark v4.0 ready while any matrix row lacks sufficient evidence. Maintain existing Docker/Podman and Direct-only operation. Record the exact tested artifacts and source revisions, attach matching source/licenses/SBOM/digests, and separately report Windows 10/11, Android/ARM, cameras, LAN and long-run results. No v4 tag or installer is published merely because one incremental PR passes.

证据不足的方向不能标记为 v4.0 完成。保留 Docker/Podman 和仅 Direct 模式；记录实测产物、源码版本、许可证、SBOM、摘要，并分别报告系统、真机、摄像机、局域网与长时间验证。本轮 PR 通过不会自动发布 v4 标签或安装包。

2026-10-04 设备控制复核：新增[设备控制与对讲](device-controls.md)的有界操作、停止反馈和麦克风生命周期；非法 PTZ 持续时间/非有限数值在发送前拒绝。原问题由五种后端失败情况和四项浏览器失败回归复现，修复不代表完成真实设备停止、并发命令排序、音频硬件或整体验收。

Device-control follow-up adds bounded UI ownership, stop feedback and microphone cleanup, and rejects invalid continuous moves before SOAP. Reproduced backend/browser failures justify the changes; physical stopping, concurrent command ordering, audio hardware and the remaining maturity matrix still require qualification.

2026-10-05 PTZ 后续：响应丢失后未停止、同设备停止越过在途移动均由失败回归复现。后台增加发送前计时器、异常/晚到响应恢复、停止优先的逐设备协调及失效计时器归属检查；故障审计与状态清理有单独回归。网络拖延、产品崩溃、设备侧 Timeout 范围协商及真实停止仍是未完成的保障与验收项。

PTZ follow-up reproduces missing stop after response loss and stop overtaking an in-flight movement. Pre-dispatch timers, failure/late-response recovery, bounded per-device stop priority and timer ownership improve backend behavior. Transport stalls, product crashes, device-side timeout negotiation and physical stopping remain open.

2026-10-05 设备超时后续：同步时读取 Media1/Media2 Profile 的 PTZ 配置范围，保存私密数字限制，连续移动同时提交设备 Timeout 与后台停止。界面显示实际范围、可选时长和未确认状态，不支持短时移动时保留停止/预置位；范围外请求、旧记录迁移和禁止无超时重试有专门回归。设备规范执行、后续配置变化、实际崩溃和真实物理停止仍待专门验收，完整矩阵保持未完成。

Device-timeout follow-up negotiates Media1/Media2 profile ranges, persists private numeric limits and submits Timeout alongside the backend stop. Visible ranges/pulses and unverified states retain Stop/presets when short movement is incompatible. Regression contracts cover rejected durations, legacy migration and no timeout-free retry. Vendor execution, later configuration changes, actual crashes and physical stopping remain separate qualification; the complete matrix is still open.

## 2026-10-06 v4 非真机收口 / 2026-10-06 non-device hardening round

本轮只做源码、自动化与文档层面的收口，**没有**真机、长时间、干净系统、真实升级或候选构建验收，也未提交/发布任何内容。

### 依赖安全（评审 §2）

`web/` 与 `desktop/` 的全量与生产依赖审计均返回无已知漏洞（退出码 0）。web 以 `source-map-js@1.2.2` 覆盖 1.x 消费者并新增 4 项真实构建链回归（Vite→PostCSS 解析路径版本、索引映射越界拒绝、合法边界、真实映射往返）。desktop 将 `@electron/get` 路径下的 `global-agent` 提升到 4.1.3 以彻底移除 `sprintf-js`/`roarr`；因该主版本把 TLS 选项守卫改成恒假的 `configuration.secureEndpoint`（代理路径会静默丢弃 ca/rejectUnauthorized/servername），额外提交 `desktop/patches/global-agent@4.1.3.patch` 恢复守卫并补回用于主机名校验的 `host`，锁文件记录补丁哈希。真实下载器夹具覆盖直连、HTTP 代理、NO_PROXY、受信/不受信证书与主机名不匹配，9 项通过。细节见[依赖安全](dependency-security.md)。完整 `electron-builder` 打包与真实公网下载仍属候选门禁。

### 管理操作与资源边界（评审 §3.1 / §3.2）

管理页与客户端配对页统一为逐资源在途锁、有界等待、归属取消、部分读取失败隔离与草稿保护；非幂等创建区分“已失败”和“提交后结果未确认”，只提供只读核对，绝不盲目重发。新增 `playwright.management.config.ts` 的 14 项浏览器回归覆盖双击/陈旧 DOM 重复激活、真实 20 秒时限挂起、响应丢失但服务端已应用、409 revision 冲突、部分读取失败保留其余区块、以及切页与 beforeunload 保护；每条都在**临时副本**中删除对应加固后复现失败（去掉逐资源锁→用例 1–2 失败且收到 2 次 POST；删除只读核对控件→用例 3/4/5/6/7/14 失败；移除 useDraftGuard→用例 12–13 失败），仓库 `web/src` 未被修改。已知限制：节点注册批准与本地备份没有服务端请求关联标识，核对无法返回“已解决”，这两类控件在 5xx/超时后保持禁用（界面已说明），不宣称能证明未创建。浏览器 S3 归档回放改为流式读取：按票据/32 MiB 硬上限在复制前逐块拒绝、单一 60 秒总时限（票据+响应+完整 SHA-256）、取消不等待、按选择归属且只保留最新结果的 Object URL，页面离开即释放；`ClusterAdmin` 已接入该 hook。上限是保守工程限制，**不是**任何手机/WebView 的实测安全上限。细节见[归档回放边界](archive-playback.md)。

### PWA 安全更新连续性（评审 §3.4）

安全替换仍立即 `skipWaiting` 并重新导航所有窗口，不允许草稿延迟淘汰旧认证门；新增的持久记录（Cache Storage，仅含替换时间戳）让重载后的外壳显示 `role="status"` 的“安全更新恢复提示”，明确区分**已丢失且无法恢复**的未保存输入与**已保留**的加密本机档案/离线队列，并指向任务列表核对服务器端导出/备份。恢复记录只由用户显式操作清除：存在期间 `useDeviceSync` 不启动挂载/定时上传，队列保留在本机直到用户显式同步；响应丢失的导出不再提供盲目重发，只做只读核对。生产构建 SW 的 4 项连续性用例通过（含真实投影窗口、旧客户端无确认、私有路由不缓存、密码哨兵不入存储）。

Raw HTTP POST 次数**不是**产品契约：夹具在无响应时销毁套接字，实测 Chromium 自行重发同一请求（5 次原始 POST、1 个请求标识、1 个被受理任务，且在没有 Service Worker 时同样复现），因此用例断言请求标识、被受理任务数与更新路径零提交，而不是页面无法控制的计数。见 [PWA 更新连续性](pwa-update-continuity.md)。

### 支持诊断（评审 §3.3）

新增用户主动导出的有界脱敏支持报告：只保留固定枚举状态/原因码、时间戳与有界计数，条数与 48 KiB 字节上限失败关闭；源码 revision、后端、APK、WebView、Electron 版本与重启原因在未注入时明确为 `unavailable`，不从 User-Agent 推测；原生状态只在用户请求时经只读 IPC 读取（1.5 秒上限，迟到结果不能伪造状态）。Chromium 夹具 6 项通过，含敏感哨兵扫描与最大条数/字节边界；报告不读取服务日志、媒体或额外接口。见[支持诊断](support-diagnostics.md)。

### 部署默认值与文档一致性（评审 §3.5）

发现并修复一处会在首次部署时关闭账号控制面的默认值冲突：基础 `compose.yaml` 默认 `WEBOBS_CLUSTER_ENABLED=true`/旧式 Basic Auth 关闭，但 `.env.example` 曾写 `false`，复制示例文件会覆盖 Compose 默认并得到无认证入口。新增 `tests/test_container_entrypoint.py::DeploymentDefaultsTests` 先复现失败再修复，并断言回环绑定与 Composite 默认关闭。README、ROADMAP、handover、本地开发、容器部署、go2rtc 与容器重启文档统一改为“首次创建管理员、无预置密码、旧 `.env` 需迁移”；新增[升级与恢复](upgrade-and-recovery.md)覆盖容器/Windows/Android/浏览器的一致性备份、匹配快照回退与失败处理；旧 v3.2 时代交接快照归档为[历史文件](history/handover-pre-v4.md)，不再作为操作手册。

### 本轮实际运行 / Commands actually run

~~~powershell
# web/
& "$env:APPDATA/npm/pnpm.cmd" typecheck                     # exit 0
& "$env:APPDATA/npm/pnpm.cmd" audit --audit-level=low       # no known vulnerabilities
& "$env:APPDATA/npm/pnpm.cmd" audit --prod --audit-level=low
node --test tests/dependency-security.test.mjs              # 4 passed
node node_modules/@playwright/test/cli.js test -c playwright.archive.config.ts --project=chromium   # 22 passed
node node_modules/@playwright/test/cli.js test -c playwright.support.config.ts --project=chromium   # 6 passed
# desktop/
& "$env:APPDATA/npm/pnpm.cmd" audit --audit-level=low       # no known vulnerabilities
& "$env:APPDATA/npm/pnpm.cmd" audit --prod --audit-level=low
node --test tests/build-proxy.test.mjs                      # 9 passed
& "$env:APPDATA/npm/pnpm.cmd" test                          # passed
# repository root
python -m unittest discover -s tests -p test_cluster_service.py   # 42 passed
python tests/test_container_entrypoint.py                         # deployment defaults pass (Linux lifecycle skipped on Windows)
python tests/test_release_identity.py                             # 2 passed
& ./tests/run-public-audit.ps1                                    # passed
~~~

### 本机既有失败（非本轮回归）/ Pre-existing local failures

完整 `playwright.local.config.ts` 套件在本机为 **252 通过 / 3 失败 / 1 跳过**（19.3 分钟）。

其中 1 项（`polling-performance.spec.ts` 的 clients）由本轮“有界请求”改动**有意**变更契约并已重写：原断言依赖“请求永久挂起”，而 `clientAdminRequest` 现在有 20 秒读上限、管理刷新层有 15 秒上限，永久慢读会在时限后按间隔重试。重写后断言读时限、轮次不重叠、隐藏即中止，以及**仅仍在途**的请求在卸载时被中止；该文件 6 项在恢复改动后的最终运行中全部通过。

其余 3 项失败经逐一复现后定性为**用例缺陷或负载敏感**，不是产品回归；两项已在后续轮次修复，修复方式都不放宽断言：

- `wall-controls.spec.ts:92`：用例点击的是**折叠 `<details>` 内的隐藏复选框**，浏览器会静默忽略该点击（受控复选框的 `checked` 从未改变），因此逐路统计行根本没有渲染；同时 `fieldsets` 期望值（1）也是按这个失效状态校准的。实测产品行为正确：展开面板后同一操作会显示“音频未知 + 重试”。用例已改为先展开面板、重试切换直到生效，并把期望修正为 2（偏好面板 + 该来源行）；连续两次运行 2/2 通过。
- `usability.spec.ts:133`：用例用三次 `fill()` 之间**真实经过的时间**来假定它们落在组件 250ms 防抖窗口内；机器较慢时每个值都会被查询——而这是正确行为（三次独立按键本来就该各自触发）。用例改为在页面内同一个任务里连续更新输入值，从而与机器速度无关；连续三次运行 1/1 通过。
- `usability.spec.ts` 其余间歇失败（曾命中 `:337`、`:166`）在空闲机器上复跑 22/22 通过，判定为并发负载下的时序抖动：完整套件运行时不应同时跑 Gradle/容器构建等重负载任务。

这些结论都来自复现与实测，不能仅凭 CI 在 Linux 上为绿就假定本机为绿。

Chromium fixtures used the locally installed Chrome via `WEBOBS_PLAYWRIGHT_CHROMIUM_EXECUTABLE`; the bundled Playwright Chromium is not installed here. `tests/test_v2_client_control.py` could not run in this environment because the pinned libsodium runtime is unavailable (environment limitation, not a source result) and `android/tests/test_release_version.py` skips on this host.

## 2026-10-06 环境门禁轮次 / Environment-enabled gates round

本轮把 WSL、MuMu 模拟器与 Docker 引擎接入日常验证，用于执行此前在 Windows 上被跳过的门禁。按仓库文档补齐了工具链：PowerShell 7.6.6（`build-android.ps1` 等脚本要求 7.2+，此前缺失导致 Android 版本码检查被跳过）、锁定 Android SDK（platform 35 / build-tools 35.0.0 / platform-tools，command-line tools 校验 SHA-256）。

### WSL Ubuntu-24.04：此前跳过的 Linux 门禁

**15 个套件通过 / 2 个失败**（`tmp/wsl-linux-gates.sh`，日志 `/tmp/webobs-wsl-gates.log`）：

| 套件 | 结果 |
| --- | --- |
| test_v2_client_control（libsodium 依赖，Windows 上无法运行） | 30 项通过 |
| test_container_entrypoint（POSIX 生命周期，Windows 上全部跳过） | 13 项通过 |
| test_camera_registry / test_cluster_service | 51 / 42 项通过 |
| test_nvr_storage / test_nvr_evidence / test_nvr_media | 6 / 13 / 8 项通过 |
| test_online_source / test_release_identity / test_preupgrade_guard | 11 / 2 / 3 项通过 |
| test_s3_archive / test_encrypted_backup / test_node_agent | 4 / 3 / 7 项通过 |
| test_detector_worker / test_m7_gate_receipts | 3 / 4 项通过 |
| test_go2rtc_integration | 失败：需要已构建的产品镜像（Docker），本机当前无法产出，见下 |
| test_event_service | 失败：事件索引 p95 预算，环境特性，见下 |

### 事件索引延迟预算：环境特性，不是代码回归

`test_event_service.test_index_latency_and_outbox_ceiling_are_bounded` 要求 40 次 `ingest_event` 的 p95 < 50 ms。在**未修改**的 `events/` 与测试文件上（`git status` 干净）实测：

| 环境 | p95 |
| --- | --- |
| Windows 原生 Python | 通过（8/8 套件 OK） |
| WSL Ubuntu-24.04，仓库位于 `/mnt/c` | 83.8 ms |
| WSL Ubuntu-24.04，仓库位于 Linux 原生文件系统 | 84.9 ms |
| 股票 `python:3.12-slim` 容器（对照，无本项目镜像参与） | 65.2 ms |
| 本项目镜像构建内（三次） | 52.4 / 55.4 / 72.5 ms |

股票容器对照说明这来自宿主存储栈，而不是我们的改动或镜像内容。决定性对照：同一镜像、同一代码，把事件数据库放到 **tmpfs（内存）** 后 p95 降到 **1.58 / 2.25 ms**（中位数 1.2–1.5 ms），即慢的是 Docker Desktop → WSL2 → Windows 盘的 fsync 路径，不是索引实现，本机也无法通过改写 PRAGMA 拿到收益（`PRAGMA synchronous=NORMAL` 按连接补齐后 p95 仍为 45/76/84 ms，因此该改动已回退，不为无收益的改动削弱持久化语义）。

**按仓库规则不放宽预算**：因此本机无法完成当前 revision 的产品镜像构建（镜像构建会在该门禁失败），需要参考 Linux 主机（CI 使用原生块设备存储）或带测量证据的索引优化，二者都未在本轮完成。

### 容器门禁发现并修复的一处真实回归

上一轮新增的 `DeploymentDefaultsTests` 会读取仓库根目录的 `compose.yaml`/`.env.example`，而镜像构建会在容器内执行 `tests/test_container_entrypoint.py`（文件被复制到 `/tmp`），于是 `ROOT` 解析为 `/` 并抛出 `FileNotFoundError`，**直接导致镜像构建失败**。这正是只能在容器门禁暴露的问题。已将该类改为仅在仓库上下文运行（`skipUnless`，镜像内跳过），仓库内 2 项通过、WSL 内 13 项通过、镜像构建随后越过该步骤。

### MuMu（API 35 x86_64）：Android 构建与安装

`android/scripts/build-android.ps1` 在补齐 JDK/SDK/PowerShell 7 后完成真实构建：Gradle `testDebugUnitTest` + `lintDebug` + `assembleDebug` 成功（6 分 53 秒），脚本内置的 APK 身份（applicationId、versionName、versionCode）与 `apksigner` 签名校验通过，产物 `build/android/out/WebOBS-3.5.0-dev.android.1-android-DEVELOPMENT.apk`，随后安装并启动到 `emulator-5556`。设备侧核对：`versionCode=3050001`、`versionName=3.5.0-dev.android.1`、minSdk 29 / targetSdk 35，`ResumedActivity` 为该应用 `MainActivity`，crashes 缓冲区为空，界面正常渲染连接对话框。`android/tests/test_release_version.py` 在本机 2 项通过。

这不是候选包、不是正式签名、不是 ARM 真机或公开源更新验收。

Android 模拟器端到端（`android/tests/test_emulator.py`，会把**当前源码**的 `web/dist` 与 `cluster/cluster_service.py` 覆盖进隔离后端）本轮**未能完成**，原因已定位且属于 revision 不匹配，不是产品缺陷：本机可用的产品镜像都早于当前源码（8 天前的 `webobs:dev` 仍带有已被现行代码移除的启动限制——无管理员时拒绝 `CLUSTER_ENABLED=true` + `COMPAT_BASIC_AUTH=false`；7 天前的 `webobs:v3.3-smoke` 可启动，但把当前 `cluster_service.py` 覆盖进去后因缺少现行 `runtime_support` 模块而以退出码 3 失败）。因此该验收必须在能构建当前 revision 镜像的环境（本机被上面的存储栈延迟预算挡住）执行；模拟器上已确证的只有构建、签名、安装与启动。

This round changes source, automation and documentation only. Revision-matched three-target candidates, real upgrades/rollback, physical cameras/ARM/LAN, long-run performance budgets and the reference-device maximum archive size remain unqualified.
