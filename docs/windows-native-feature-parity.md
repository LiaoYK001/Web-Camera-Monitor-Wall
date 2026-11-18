# Windows WebOBS Wall 功能迁移矩阵 / Feature parity matrix

## 2026-11-17 v5.1修复进展 / v5.1 hardening

用户将下一正式交付目标指定为v5.1，主要Windows验证使用该版本。rc.1的安装/媒体回执保留，但不称完整功能已完成。源码修复v4.5工作区的真实插件路径和目标profile路径，账号配置/工作区以整目录提交，失败回退允许重试；原生更新器在执行前/备份后重新验证缓存文件大小/SHA-512，拒绝不可用/回退更新及必要备份缺失，并按数字比较预发布版本。现有及新增本机SQLite/文件/HTTP负向回归通过；新的Windows安装、完整迁移/更新链、声音/输出/远端等仍需后续证据，不关闭整个R4。

The v5.1 source fixes actual preview workspace paths and transactional profile publication, rehashes cached installers before execution, and compares prerelease numeric identifiers correctly. Local integration/regression passes do not qualify a new Windows installer, full migration or the remaining product features.

R2-004源码新增按账号workspace保存的固定/Program投影窗口位置、屏幕、大小及全屏偏好；重新打开时复用OBS窗口并按Qt逻辑坐标恢复，原屏幕缺失则夹到可见桌面并窗口回退；移动事件去抖写入，无新增常驻采样。Qt几何边界回归与完整product_window语法检查通过，Windows实际位置保存/关闭/重开门禁已加入但尚待新source运行。固定Scene媒体自动恢复和物理DPI/显示器故障仍开放，不关闭完整R2-004。

2026-11-18 最新 Windows 更新/迁移门禁：[run 44194328169](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44194328169) 在源码 `472f3fe5cddf90f304801aab4dccd4765b0076f2` 上 success，内部版本 `5.1.0-rc.16`。实际便携/安装态/升级后产品门禁各 **55/55**，认证前恢复隔离 **9/9**；已安装更新器实际完成同源码 `rc.16 → rc.17` loopback 下载、损坏缓存拒绝、独立维护解释器、加密备份、真实 NSIS 执行、版本切换和恢复验证。升级后 durable profile 指纹 **30/30** 一致；卸载保留 profile/录像/未知文件，快捷方式与注册项清理。安装器 **212,162,215 B**，SHA-256 `12039948205f915de180eb0a84f74d0b51ef3fd737a30234851305dbe4242dbd`；首启前安装树 **794,579,783 logical / 806,620,488 allocation B**、6,972 文件。

该 run 仍是内部候选，不是正式 v5.1 Release、稳定 feed 或目标机/OBS 性能资格。非空逐轨音频、由同一原生宿主产生的 Program 合成录像/推流、LAN/Caddy 的真实第二设备远端验收、完整旧档案迁移、物理多屏/DPI/音频/硬解和两小时长稳仍未关闭；`fullFeatureMigrationQualified=false`、`hardwareDecodeVerified=false`。详见[脱敏资格摘要](qualification/windows-v51-update-gates-2026-11-18.json)。

The latest Windows update/migration gate passed on source 472f3fe5: 55/55 portable, installed and upgraded checks plus 9/9 restore isolation, an actual rc.16-to-rc.17 installed updater/NSIS cycle with encrypted backup and restore, and a 30/30 durable-profile fingerprint match. The 212,162,215-byte installer is an internal qualification artifact, not a stable v5.1 release or target-device/OBS performance qualification. Nonempty multi-track audio, native Program composite recording/streaming, remote access, full legacy-profile migration and physical device qualification remain open.

2026-11-11。基线 `codex/windows-native-monitor@4678f3a`，PR #53 面向 `dev`。旧完整 Windows 产品与已发布原型分别核对，用户反馈 dev.53 原生画面正常，最终完整产品的性能和个人数据升级待集中验收。

执行依据为 [完整任务书](windows-webobs-wall-release-plan-2026-11-11.md)。状态按“旧实现可用、原生未接线”“接线开发中”“自动化通过”“最终设备待验收”记录，每项保留实际入口和证据。

Baseline is the native branch at 4678f3a, PR #53 targeting dev. The user reports working native pictures in dev.53. Full-product hardware performance and personal-data migration await the final integrated candidate. Existing protocol modules and prototype receipts qualify only their recorded scope.

## 2026-11-16 当前核对 / Current verified baseline

完整版本开发从 **v5.0** 开始，v4.5 保持历史预览。当前已发布源码 `24fd012`，最终 Windows run `43783406841` success：便携与真实 NSIS 安装各 40 项、认证前恢复 I/O 对照 9 项及卸载保留数据通过。安装 200,614,374 logical / 204,053,288 allocation bytes；这些是预览范围，不是完整功能、旧数据迁移、逐路硬解或 OBS 同机性能资格。以下 24 行逐项核对当前产品入口，旧 dev 记录仍保留为历史，不批量升级为完整通过。

The next complete release is v5.0. Final v4.5 evidence is scoped to its real native preview/installation paths. The 24 capability rows retain gaps for complete integration and physical qualification. Public source/receipts: [v4.5 Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.5).

## 媒体与控制架构 / Media and control architecture

Windows 采用一个固定 OBS frontend/Qt 媒体宿主。现有 core 的 Direct-only 路径已跳过 `obs_startup`，R1 复用它承载账号、Registry 代理和产品文档。原生 Qt 通过同一个有界、会话认证的 loopback HTTP 控制面访问服务，OBS 对象变更在 frontend 线程执行。管理功能继续使用本机受认证 WebUI，默认打开管理区，避免额外播放本地墙。

产品模式采用固定上游源码的构建副本及外置集成补丁，在恢复媒体之前阻止 OBS collection 恢复，同时由产品界面接管编辑入口。原生宿主拥有服务进程、会话和媒体消费者。退出、撤销与会话过期都必须释放受保护来源。产品存储仍保留 Registry、Secret 引用及 Scene/Studio 文档，OBS collection 作为临时运行时映射。

One pinned OBS frontend owns local media. Reuse the existing Direct-only core for authenticated control and documents, with a single bounded loopback HTTP adapter. Product-mode hooks apply to a pinned build copy before scene restoration. Product data remains authoritative, while runtime OBS state is rebuilt after authorization. A native supervisor owns service lifetimes and media consumers.

## 功能清单 / Feature inventory

| ID | 旧入口与实际代码 | 新入口与迁移位置 | 数据与权限 | 组件 | 真实接线验证 | 状态与证据 | 当前阻塞 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AUTH | `LoginGate.tsx`、`AccountWorkspace.tsx`、core auth、cluster accounts | 原生登录/建账/退出，管理浏览器账号页 | 同一账号、绑定 userId/authEpoch，会话撤销 | core Direct-only、cluster | 安装后真实账号登录、改密/禁用/过期关闭画面 | v4.5 最终便携/安装：真实建账、登录/重登、改密/禁用/重启撤销通过；本机双模式 HTTP 回归含 epoch/撤权/队列复检与设备管理面 viewer-403 | R1-001 全入口审计(2026-11-16)已核对 core/native/cluster 实际入口，补 v2 设备管理面、排队会话复检与 legacy WS 撤权轮询；旧账号数据迁移、旧数据 ACL、已建立媒体通道服务端关闭与同源码 Windows 产品覆盖仍开放 |
| RBAC | `UserAccessEditor.tsx`、cluster role/camera scope | 原生目录和每次执行/持续观看校验 | 角色、camera/group scope，未知来源拒绝 | cluster、Registry | 同名重建账号、换组、隐藏/嵌套来源、权限撤销 | v4.5：逐相机/Profile目录与执行、持续撤权、投影退休、认证前恢复 I/O 隔离通过 | R1-001 审计确认 native mutation 执行时双重 validate/epoch 回声、v2 设备管理面 node.manage 与 sources 直接路由相机作用域栅栏（越权 WHEP/音频创建 403）；Studio/输出完整执行栅栏、角色/组跨快照一致性、旧数据 ACL 与 Windows 同源码覆盖仍开放 |
| DEV | `CameraRegistry.tsx`、`camera_registry.py` | 原生摄像机/Profile 选择，本机设备管理页 | 稳定 camera/profile ID、Secret 引用 | camera、core | 选已有设备进入媒体源，禁用/缺失 Profile 可见报错 | v4.5：设备 API 到原生五路/Profile选择、禁用/变更/保存恢复通过 | 旧个人设备导入、完整 ONVIF/PTZ/对讲与设备实测未完成 |
| IMPORT | `bulkSourceImport.ts`、ONVIF API、`migrate_legacy.py` | 设备库批量导入/ONVIF 页面；旧 WebOBS 4.x / v4.5 NativePreview 显式导入 | 去重、配置保留、device.manage；SQLite 一致性、账号绑定工作区、拒绝覆盖 | camera、WebUI、product migration | 实际导入、失败不覆盖、重启保留、旧档案迁移 | 管理页接入手动/批量设备；Linux实际服务+Chromium首用新增1+4路并读取5路；v5.0-rc.1 单元验证覆盖旧配置/v4.5 工作区、损坏/覆盖拒绝 | 浏览器首用和合成迁移不替代完整 Windows ONVIF/大批量、用户本人旧档案和目标机迁移验收 |
| LIVE | `DirectPreview.tsx`、`ProgramPreview.tsx`、core OBS | 原生 OBS Media Source 与 Preview/Program | 认证后建图，同源兼容设置共享 | OBS、obs-ffmpeg | 真实插件、真实服务、动态 H.264/H.265 最终像素 | v4.5：五路动态 HEVC、实际最终像素、同源复用、输入推进、断流恢复、重启和撤权通过 | 真实相机、逐路硬解、目标机同条件OBS对照与长稳仍待；v5.0快捷墙1/4/7路Windows动态像素通过；64为有界接口/网格，不是64解码器实测 |
| STUDIO | `SceneCollection.tsx`、`sceneSchema.ts`、`StudioController`、`product_window.cpp` | 原生场景切换/编辑与现有管理 Studio | Scene/Source UUID、草稿、revision、嵌套 | OBS、core、WebUI | 保存/恢复、裁剪/层级/锁定、冲突、TAKE | v5.0-rc.1：真实原生 cut/fade TAKE、Program source 回读/回执、旧 Program 图释放、Program/固定投影最终像素和空 Program 清屏通过；保存/恢复及无关 revision 保持 | 完整嵌套编辑、复杂冲突/撤销业务来源及目标机兼容仍开放 |
| LAYOUT | `monitorView.ts`、监控偏好、设备布局 | 原生网格/轮换/事件提升/主子码流 | 账号与设备偏好分离 | OBS、account、clients | 既有布局范围、人工选择、帧率/分辨率回读 | 受支持的已保存相机场景可映射布局/裁剪/层级；不同固定Scene最终画面通过 | v5.0快捷墙1–64路源码与本机几何/真实libobs复用通过，Windows便携及安装1/4/7路通过；完整编辑/复杂嵌套仍未完成 |
| PROJECT | `ProjectorView.tsx`、desktop fixed projector IPC、`product_window.cpp` | 原生 Program 与固定 Scene 多投影 | 固定场景身份、同源引用 | OBS/Qt | 双固定场景、切 Program、重开/全屏/DPI | v4.5 两固定Scene共用来源/全屏/关闭/撤权清屏；v5.0-rc.1 双固定投影、Program 投影、TAKE 前后最终像素和关闭/重开通过 | 物理多屏/DPI、睡眠唤醒和更完整投影持久恢复待目标机；not full device qualification |
| AUDIO | `AudioWorkspace.tsx`、`sourceAudio.ts`、schema-v6 | 原生混音/监听/电平，管理音轨页 | 账号监听偏好与项目轨道语义 | OBS、音频专用 FFmpeg 混音源 | 无重复扬声器输出、多轨保存、失效轨报错 | 非空 audioInputs 已接逐轨 gain/mute/syncOffset，经本机 TCP MPEG-TS 送入单一 OBS 音频源；OBS 输出总线/监听/主音量、volmeter dBFS 和 audioSources 诊断已实际接线。Windows rc.23 完整门禁结果待回执 | 目标机真实摄像头多音轨、物理扬声器/监听设备与长期漂移仍待主要验证 |
| OVERLAY | `MonitorProcessStatus.tsx`、analytics、隐私遮罩 | 原生叠层及管理配置 | 本地/录像/远端范围分开 | OBS、可选 analytics | 边框/检测框/音量表与最终像素、隐私遮罩 | 原生未接线 | overlay 来源和数据连接 |
| PTZ | `CameraDeviceControls.tsx`、`useShortTalk.ts` | 受认证管理页设备详情入口；原生窗口提供设备管理入口 | camera scope、移动脉冲、超时停止 | camera | 松键/断开停止、预置位、对讲收尾、快照 | 管理页入口与真实 camera 服务已在完整安装中启动；未做本次硬件交互 | 真实 ONVIF 相机、松键/断开收尾、对讲设备和实际最终画面待目标机 |
| OUTPUT | core OBS 录像/推流、`SystemStatus.tsx` | 原生宿主按需录制真实 Program/回环发布推流 | 输出状态、退出保护、音轨 | OBS x264/AAC、ffmpeg_muxer、rtmp_output、按需私有 MediaMTX（RTSP+WHEP 对外） | 本地关闭后持续任务、无需求编码器为零 | 同一 OBS 宿主已按需创建编码器，MP4 先写临时 MKV 再由锁定 FFmpeg 流复制；Program 以回环 RTMP 发布到按需私有中继，中继再提供 RTSP/WHEP，停止后释放。固定 Windows OBS 树禁用 obs-webrtc，`whip_custom`/`whip_output` 不存在（rc.57 回执 `stream-service-unavailable`）。Windows 门禁待 rc.58 回执 | 目标机真实编码性能、OBS 侧 WHIP 直推（需可在 Windows 构建的 LibDataChannel）、长时间推流和断电恢复待验证 |
| NVR | `NvrTimeline.tsx`、`NvrSettings.tsx`、`nvr_service.py` | 原生 supervisor 内的录像管理入口、时间线和配置页 | 原码流、配额、多卷、索引 | NVR、必要 FFmpeg | 计划、磁盘满、掉盘恢复、保留历史录像 | v5.0-rc.1：真实注册表相机录制、鉴权 MP4、时间线、policy off 收束和安装态通过；配置页支持连续/事件/分段/容量 | 多卷/掉盘/配额故障、目标机真实录像编码和长时间回放仍待 |
| EVIDENCE | `NvrExportPanel.tsx`、archive、timeline | 回放/归档/证据页面和原生回放入口 | Range、审计、hash、lease | NVR、archive | 真实媒体 seek/大文件导出、路径与权限 | v5.0-rc.1 鉴权 MP4/Range 和回放页入口已验证；导出服务已安装 | 大文件 seek/导出、磁盘/权限/审计和目标机数量仍待 |
| EVENTS | `EventsPanel.tsx`、`event_service.py` | 事件/规则/通知入口 | 权限、持久 outbox、重试预算 | events、可选通知集成 | MQTT/HA、重复抑制、重启恢复、事件录制 | v5.0-rc.1：真实事件创建/去重、规则和持久 outbox 通过；events 服务随完整安装启动 | MQTT/HA 实际目标、重启去重、事件录像和通知投递仍待 |
| DETECT | `AnalyticsWorkspace.tsx`、analytics providers | 检测配置/叠层及完整安装内模型/ORT 组件 | provider、任务授权、作用域 | analytics、模型/推理运行时 | 开关任务、lease/撤销、事件关联、成本增量 | 完整包已验证内置 ONNX/ORT 资产和管理页；检测最终像素未在本次门禁开启 | 目标机检测任务、provider、叠层最终像素与资源增量待 |
| G2R | `Go2rtcWorkspace.tsx`、固定代理、`go2rtc/runtime.py` | 完整安装内受认证管理页与来源适配 | `/api/v1/go2rtc/`、settings.manage | go2rtc | 配置保存、重载、HTTP/WS、凭据隔离 | v5.0-rc.1 go2rtc 服务随产品启动，管理入口和在线解析器自检通过 | 真实网站/长直播、外部站点 Cookie/重连及按需进程预算仍需目标验证 |
| ONLINE | `Go2rtcOnlineSources.tsx`、`online_source.py` | 网站来源目录/Profile，原生观看 | 锁定提取器、Cookie 私密目录 | go2rtc、yt-dlp/Streamlink/EJS/Node | 真实解析/relay/认证实播，预算与退出清理 | v5.0-rc.1 完整包已暂存锁定 yt-dlp/Streamlink/Node/EJS 并通过 `webobs-online-source --self-test` | 公开网站解析/实播、Cookie 认证、重连和退出清理仍待目标机；组件来源清单为候选未复审 |
| REMOTE | WebUI/PWA、Android 既有客户端 | 同一 Windows 服务的远程入口 | HTTPS、Origin、Direct/Composite scope | core、按需 gateway/Caddy | 既有客户端登录/播放，一个观看端退出不误停其他端 | 旧实现可用；原生 Complete 已启用 Composite WHEP 代理供本机 Program 发布后消费。原生产品窗口新增“开启/关闭局域网共享”开关，设置原子保存在 `config/native-lan.json`（默认关闭，变更在下次产品启动生效并显示 `pendingRestart`），由监督器启动 Caddy HTTPS 反向代理（仅私有 IPv4、本地 CA、只回环反代、产品登录与 Origin 策略不变）；HTTPS 端口被占用或无私有 IPv4 时入口保持关闭并在状态/支持包给出有界原因，本机回环监看不受影响；已安装门禁验证首账号创建、第二进程经 LAN HTTPS 登录/播放且与本机会话互不影响、禁用重启后无监听、无残留进程 | 真实第二台设备/交换机与跨设备媒体验收 |
| OFFLINE | `DeviceSyncPanel.tsx`、`useDeviceSync.ts`、v2 | 受认证管理页与原生布局状态同步 | 签名/加密缓存、冲突、有限离线权限 | clients、core、WebUI | 离线编辑、重连冲突选择、Program 不被覆盖 | 旧实现可用，原生未接线 | 设备状态与原生 scene 映射 |
| OPS | `ProblemCenter.tsx`、`DeveloperDiagnostics.tsx` | 原生问题/诊断入口与受认证管理页 | 有界脱敏导出、settings.manage | core、业务服务 | 解码/组件/连接故障定位、脱敏支持包 | 原生支持包已导出固定 schema、版本/启动身份、渲染器、媒体/音频/Program计数、窗口角色和 OBS 标记统计；不写 URL、令牌、日志正文、媒体或输出路径，256 KiB 上限。Windows rc.24 门禁待回执 | 尚非全进程CPU/内存或分引擎GPU/显存；Problem Center 已由管理页头部提供 |
| BACKUP | backup 服务、`migrate_legacy.py`、restore helper | 管理页、迁移快捷方式和更新前备份 | 活跃 SQLite 快照、Secret、录像路径、native-profile | backup、原生 updater | 损坏/中断/磁盘满、幂等迁移和真实恢复 | v5.0-rc.1 搬迁使用 SQLite backup API，更新前备份使用打包 libsodium，恢复隔离对照 9/9；加密备份现同时包含 config 与 native-profile，旧 config-only 包兼容且不删除现有 native-profile；恢复日志在持锁后、创建目录与读取 profile 之前由普通启动收敛（成对完成或回滚，旧对保留可重试），回滚分支现在同时收回已换出的旧 OBS 档案，崩溃时出现在活动路径上的新档案改为挪开保存而非删除；安装态门禁 `backup_restore_windows.py` 覆盖两个交换窗口（配置落盘前与 OBS 档案换出后）各终止一次真实恢复进程后从安装入口启动验证，另有 12 项本机备份回归覆盖两种半状态 | 用户本人档案实际搬迁、旧 DPAPI 密钥、磁盘满与恢复演练仍待目标机；两个窗口的 Windows 门禁结果待回执 |
| LIFE | `main.mjs`、`supervisor.mjs`、`job_host.cpp`、`product_supervisor.py` | 原生单实例/托盘/supervisor | Job、任务消费者、正常退出和崩溃收束 | Qt、Win32、按需服务 | 安装态关闭/托盘/后台任务/故意崩溃零遗留 | v5.0-rc.1 便携/安装各52项通过正常关闭、重启、origin 冲突、撤权和 launcher 崩溃清理；完整 NSIS 覆盖升级/卸载保留通过；活动 Program 输出关闭主窗口时保留托盘宿主 | 托盘菜单自动化和睡眠唤醒/目标机长任务仍待验证 |
| UPDATE | desktop updater/NSIS、native updater | 安装后“检查更新”入口、原生下载/确认/安装 | SHA-512/size、版本、备份、用户确认 | 原生 updater、NSIS | 旧稳定升级、新原生后续升级、截断/断网/失败恢复 | v5.0-rc.1 `latest.yml` 与安装字节绑定，同机 rc.1→rc.2 覆盖升级和更新前备份通过；候选为固定 prerelease feed | 稳定 feed、旧稳定→v5 实机、截断/断网/签名和目标机恢复仍待 |

## 进程和体积口径 / Process and size accounting

旧 `Supervisor.start` 默认启动 MediaMTX、go2rtc wrapper、camera、cluster、clients、events、NVR、backup 与 core，archive 和 Caddy 依据配置启动。原生核心拟默认启动 OBS host、control-only core、账号和设备目录服务，其他消费者由真实功能需求启停。Python 业务实现保留并计入实际组件成本，组件名称不能用于推断是否转码。

旧 dev.18 footprint 总逻辑字节 1,459,397,091，其中 Electron shell 388,050,826、独立 runtime/bin 432,284,496、OBS 树 352,434,045、Python 172,898,288。数据来自其已发布 footprint，最终完整安装重新计量。原型约 99 MB 的历史证据仅作为核心媒体基线。R5 分别记录下载、安装逻辑/分配、首次运行新增、离线完整组件与功能增量，包含所属树外进程。

The old full-runtime baseline is 1,459,397,091 logical bytes in published dev.18. Its Electron shell, separate tools, OBS tree and Python runtime dominate the payload. The native prototype's roughly 99 MB receipt applies to its measured component scope. R5 measures the integrated core and complete installation afresh, including optional/offline components and owned external processes.

dev.79 R1 内部组件回执（source aa90f52、run 43164336627）记录 1863 文件、197,867,225 B（清单自身除外）。其中 bin 96,876,552 B、Python 23,785,687 B、Web 56,642,796 B、OBS data 12,372,562 B、插件 3,725,824 B、许可证 3,972,953 B、services 442,527 B，其余为固定说明/标记。Web 内 `ssd_mobilenet_v1_12.onnx` 29,461,455 B 与 ORT WASM 25,749,873 B 合计 55,211,328 B。它们尚未做按需安装接线，当前真实体积全部计入；不能先从分母扣掉再宣称核心/完整版本达标。这个 R1 范围尚缺完整业务组件、安装态 allocation 与首次运行数据成本。

The dev.79 internal R1 component receipt measures 197,867,225 bytes before the receipt itself, including 56,642,796 bytes of WebUI assets. Its ONNX model and ORT WASM alone total 55,211,328 bytes. They remain shipped and fully counted until real optional installation is wired. This incomplete R1 scope is neither a complete-feature installed footprint nor an OBS-size pass.

## 2026-11-12 R1 当前门槛 / Current R1 gate

dev.86（43219901436、source 52b877c）的实际统一入口 UI/media/lifecycle passed=true：九组最终捕获各八帧通过，包含五路动态 HEVC、注销/禁用/配置变更/失效清屏、保存 IDs、重登重启、固定 origin 冲突拒绝及 Job 崩溃收束。恢复对照失败，安装态未执行。dev.87（43226176793、source 198ed4b）22 项实际 UI 检查和 13 组八帧捕获通过，含普通 scope/账号隔离/改密撤销；恢复对照真实 RTSP I/O 通过但正常关窗超时，NSIS 实际落盘/哈希/体积通过后在快捷方式检查附近失败，installed UI/卸载未执行。均不代表完整功能、旧数据升级、硬解或目标机性能达标。

Dev.86 passes the existing portable product UI/media/lifecycle gate with nine eight-frame capture groups. The restore positive control fails and installation did not run. Dev.87 passes scoped-viewer/account-isolation/password-change regressions. Restore normal close fails after real RTSP I/O; fresh NSIS reaches measured installation but fails before installed UI. R2–R7 remain open and no intermediate user testing is requested.

2026-11-12 后续：dev.84（43176197394）五路 UI 选择/建图与八帧最终窗口捕获通过，五路像素因纯红编辑叠线仍失败；后续复用 OBS Locked Preview 的修改待新 Windows job。未执行后面的保存恢复/安装态门槛。 / Dev.84 passed choice, graph and guarded capture, but final five-stream pixels failed. The locked-preview repair is pending Windows validation.

2026-11-12 后续：dev.85（43178800584、source 6edb407）实际产品五路 HEVC 最终 Preview 八帧颜色/标记/时间推进通过，保存 camera/profile ID 通过；注销时源计数未退休归零，后续空白/重登/重启/安装态未通过。core 独占端口的实际 Windows 强制绑定负向检查通过。不是目标机硬解/性能或完整产品证明。 / Dev.85 passes the first actual five-stream final-pixel sequence and exclusive bind tests, then fails at logout retirement; later lifecycle and installation remain open.


dev.87 实际 NSIS 安装前首启测量：198,314,717 logical B、201,252,904 unnamed-stream allocation B、1865 files；setup 70,074,866 B。安装 gate 总体失败于 installed UI 前，因此仅作为本次不完整集成范围的实测体积，完整业务/升级/首次运行成本仍待补齐。 / Actual fresh installed footprint was measured in dev.87, but installed-entry and uninstall gates did not execute. It is not a full-product size qualification.


dev.88（43230943802、source 1dda0c5）：23 项实际 portable UI 检查和十五组八帧像素通过，含五格仅一个实际 HEVC 来源与切回独立五路；登录前恢复正/负 I/O 对照九项通过。NSIS 198,392,037 logical B / 201,326,632 allocation B，仍失败于快捷方式目标比较，installed UI/卸载待执行。已保存 Studio 场景的新入口未包含在该构建，完整 Studio/功能/迁移/更新/性能仍未完成。 / Dev.88 passes actual source sharing and pre-authentication restore isolation, but not installed-entry or full-product qualification.


dev.90（43611384570、source be7bd3d）实际保存场景 UI、五路最终像素、sceneId 登录后恢复及普通 API revision 变更清屏的八组捕获通过；整轮回切五路/保存阶段失败，NSIS 未执行。后续多投影、观看操作/保存同步及手动 session cookie 接线均待新 Windows source，不提前记为通过。 / Saved-scene subchecks pass in dev.90, while the full UI gate fails later; projector/session changes remain pending Windows.


R2 后续源码增加 OBS 原有媒体 callback 的轻量视频输入进度，主画面/两固定投影去重并在现有 heartbeat 中显示首帧/推进/六秒停滞/未知。Linux 实际 libobs proc-handler 分支（inert fixture）、补丁后完整 C 源与 Qt 编译检查通过；Windows 实际 HEVC 状态 UI 门禁待下一 source。它不等价于最终显示、硬解/独显或性能证明，dev.91 不含这项修改。 / Lightweight owned-source input progress is wired into the native UI; local protocol/compile checks pass, while actual Windows HEVC verification is pending and does not qualify final display or hardware performance.


R2 统计入口继续接线到 OBS 原有 OBSBasicStats，真实会话/scene.read 核验后才打开，注销关闭，标题注明仅宿主进程；本机 Qt/控件检查通过，Windows 实际窗口回归待下一构建。完整实时占用、多进程总量和分引擎 GPU 仍未完成。 / The authenticated native host-statistics entry now reuses OBS's existing surface; Windows UI validation and full product accounting remain pending.


Dev.91（43616770312、49cd463）实际 portable 31 项检查、25 组八帧像素通过，含两固定投影共用来源、全屏/关闭、仅投影 camera 撤权退休及手动保存回切；logoutRetirementMs=3。恢复正对照在编译前置失败（嵌套 MSBuild 同写 build_x86），未运行 I/O 探针。NSIS 实测 198,496,992 logical B / 201,433,128 allocation B，快捷方式报告目标不存在，installed UI 未执行。新帧进度/统计/同画布来源保活均待新构建。 / Dev.91 validates actual fixed-projector media and permission paths, while restore-build and installed-shortcut failures keep the full gate red.


实际 D3D11 渲染设备查询已进入原生 UI/私密状态，复用 prototype 同一实现，区分硬件 vendor、软件/未知并记录 LUID/显存容量；本机编译与回执检查通过，Windows 产品验证待 dev.92 之后。逐路硬解与显存占用尚未证明。 / The actual renderer adapter is wired into the product surface, with Windows product validation still pending and no decode/usage claim.


Dev.92（43620903246、c1bf843）整体 success，便携/实际 NSIS 安装后各 34 项检查、26 组/256 帧通过；恢复正负 I/O 对照九项通过。安装 footprint 198,521,443 logical B / 201,453,608 allocation B，原生快捷方式与卸载保留通过。全部仍为未完成业务融合的内部范围，旧版升级/完整功能 false，二进制未发布；目标机/完整功能性能未达标证明。 / Dev.92 validates the current isolated fresh-install scope, not complete legacy migration or the full R0–R7 objective.


R2 场景内容前置条件已接入真实服务与主图/固定投影：无关全局 revision 更新可继续，实际显示内容与 camera/身份变化仍 fresh 核验/拒绝。Linux 九项 CTest、真实并发 HTTP/权限与 Qt/契约通过；新多窗口最终像素待 dev.93 后 source，完整 TAKE/Preview-Program 仍未接线。 / Scene-content preconditions are wired with fresh authorization preserved; Windows continuity and full Studio integration remain pending.


Dev.93（43625385803、3ec6dfa）便携/实际安装各 35 项、27 组最终像素通过；一路合成 RTSP 断流恢复保持来源身份，空音轨选择保留视频。恢复与 NSIS/卸载保留通过；198529824 logical B、setup 70141373 B。仍无真实硬解/目标机/完整功能/旧版升级资格。后续管理网页登录与普通 API 已接不可变身份，本机真实账号/HTTP 回归通过，需新 Windows source；完整 Studio/TAKE bridge 继续。 / Dev.93 passes current installed/fault gates; complete features, upgrade and performance remain open. Bound management identity is locally integrated and awaiting Windows validation.


R2 本地监看已从普通输出选择改接 OBS 原生 Studio Preview，Program 在无受保护来源时独立初始化；禁用产品 profile 的 source/swap duplication，缺 Studio 时拒绝回退。实际 Windows gate 新增各阶段 Program root/媒体树保持检查，本机 Qt/补丁/契约通过，待 dev.94 后实际构建。完整 TAKE/原子 bridge 仍未完成。 / Local viewing now targets real Studio Preview with independent idle Program; actual Windows routing verification is pending and full TAKE remains open.


Dev.94（43629933739、6df8e5a）当前完整 gate success，便携/安装各 36 检查、28 组/280 帧、恢复九项与卸载保留通过；安装 198550830 logical B。Dev.95（43632728117、f1d393d）前 30 检查/248 帧含 Preview/Program 分离通过，但重启 entry -1/窗口访问失败，安装未验；旧日志的预期端口冲突不能当根因。产品独占 Studio 初始化、boot/退出诊断和提前保存偏好冷重启 gate 已接源码，本机通过，实际 Windows 待 dev.96。 / Dev.94 passes the current scope; dev.95 fails at restart after successful routing/media checks. Controlled initialization and scoped diagnostics await Windows validation; complete features/upgrade/performance remain open.

## v5.0 开发：可变路数快捷监看 / Variable quick wall

独立工作树 `codex/windows-v5-integration` 将原生快捷墙从固定5路接为1–64路，默认仍为5路，原五路3×2布局不变；旧schema 1的五路选择可读，非五路按当前账号保存/重新认证后恢复。选择器共享单个目录模型，改变路数只编辑选择草稿，点击监看后仍先resolve/重新授权并比较相机配置版本，再复用原来源建图；Preview不改Program。上限表示接口与布局边界，不是64台真实相机的硬件/性能承诺。

本机：网格测试覆盖1–64、奇数与uint32极值画布、无重叠/越界/零尺寸、整方格铺满及五路兼容；Qt 6.11.2头/GCC16语法检查通过（厂商头按system include处理）；API CTest 8/8；44构建契约、像素24项（2平台跳过）通过。实际固定libobs图测试1→7→64→1个同源item保持一个输入UUID，最后释放平衡；输入为inert fixture，不是64路解码证明。新增Windows门禁覆盖1/4/7路最终动态像素、改变路数不影响正在播放的图、交集UUID复用、7路保存/注销/认证恢复；source4291556的run43816563388已完整通过。完整Studio/TAKE/音轨/业务迁移继续开放。

The v5.0 quick wall now supports bounded 1–64 selectors with one shared catalog model, five-slot compatibility, fresh authorization, retained inputs and account-scoped persistence. Local geometry/API/Qt/real-libobs reference tests pass. Windows final-pixel and installed-entry gates pass for source4291556; inert inputs do not qualify decoding capacity, and this slice does not complete full R2 or OBS performance parity.

本轮最终 Windows [run43816563388](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43816563388) success，实际源码 `429155676834047d5be5b3fbc1b900abf660f831`、内部版本 `5.0.0-dev.1`。便携/实际NSIS安装各43项（四项新增quick-wall检查）、恢复9项与卸载保留通过；内部模式无v4.5预览专属目录项，不将数量写作44。预览/非预览实际HTTP及非原生目录兼容也通过。原始回执摘要、安装字节与边界见[脱敏资格摘要](qualification/windows-v5-quick-wall-2026-11-16.json)。安装器仍禁止发布，不更新v4.5或稳定源；后续仅回执文档提交不作为新二进制资格。

The internal Windows candidate passes43 portable/43 installed/9 restore checks, including variable layouts and authenticated persistence. All receipts bind4291556; the added documentation is not a rebuilt installer. Complete Studio, audio, business/data migration, native updating and physical-device performance remain open.

## v5.0.0-rc.1 完整融合候选（2026-11-17 已发布 prerelease）

完整 Windows 候选 [run 43956468003](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43956468003) 在源码 `8828532c60648f52fae9bee222fa41b80beee7ab` 上 **success**。便携产品门禁 52/52、实际 NSIS 安装后产品门禁 52/52、恢复隔离 9/9，共 35 组最终像素捕获；覆盖真实 Program cut/fade TAKE 与 Program 投影、NVR 实际录制与鉴权 MP4、事件去重/持久 outbox、go2rtc 服务与网站解析器自检、托管账号/相机范围撤权、普通关闭/重启/改密/launcher 崩溃收束。完整 NSIS 还通过同机 rc.1→rc.2 覆盖升级、profile 字节保留和卸载保留用户数据。

安装器 212,117,618 B，SHA-256 `3d16014dab7700e6bc4f73c5c0bfba5700382c78fb3f24041589b58a4e67016c`；候选 [Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1) 为 prerelease、非 Latest、固定候选 feed。安装树首启前 794,551,075 logical B / 806,587,720 allocation B、6,972 files；仍不是完整功能/目标机性能资格。

The complete Windows candidate run 43956468003 passed on source 8828532: 52/52 portable product checks, 52/52 installed checks, 9/9 restore isolation, and 35 final-pixel groups covering real Program TAKE/projector, NVR recording/authenticated MP4, events/outbox, go2rtc/online-extractor self-test, scoped revocation, normal close/restart/password change/launcher crash cleanup. Fresh NSIS, same-machine rc.1→rc.2 upgrade, profile byte retention and data-retaining uninstall also passed. The candidate Release is a prerelease, not Latest, with a pinned candidate feed.

未关闭边界：目标机真实五路/逐路硬解/物理多屏/DPI/音频/两小时长稳、个人旧档案实际迁移、非空逐轨音频、OBS 合成录像/推流、LAN/Caddy 远端和部分分析叠层。候选不得替代这些最终验收，也不得据此开放稳定 feed 或恢复暂停平台。

Open boundaries: target-machine real five-camera/per-stream hardware decode, physical multi-monitor/DPI/audio and two-hour stability; the user's own legacy profile migration; nonempty multi-track audio; OBS composite recording/streaming; LAN/Caddy remote access on a second physical device and part of analytics overlays. The candidate does not replace those final gates or authorize a stable feed or paused platforms.
