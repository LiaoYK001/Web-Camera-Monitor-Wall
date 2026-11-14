# Windows WebOBS Wall 功能迁移矩阵 / Feature parity matrix

2026-11-11。基线 `codex/windows-native-monitor@4678f3a`，PR #53 面向 `dev`。旧完整 Windows 产品与已发布原型分别核对，用户反馈 dev.53 原生画面正常，最终完整产品的性能和个人数据升级待集中验收。

执行依据为 [完整任务书](windows-webobs-wall-release-plan-2026-11-11.md)。状态按“旧实现可用、原生未接线”“接线开发中”“自动化通过”“最终设备待验收”记录，每项保留实际入口和证据。

Baseline is the native branch at 4678f3a, PR #53 targeting dev. The user reports working native pictures in dev.53. Full-product hardware performance and personal-data migration await the final integrated candidate. Existing protocol modules and prototype receipts qualify only their recorded scope.

## 媒体与控制架构 / Media and control architecture

Windows 采用一个固定 OBS frontend/Qt 媒体宿主。现有 core 的 Direct-only 路径已跳过 `obs_startup`，R1 复用它承载账号、Registry 代理和产品文档。原生 Qt 通过同一个有界、会话认证的 loopback HTTP 控制面访问服务，OBS 对象变更在 frontend 线程执行。管理功能继续使用本机受认证 WebUI，默认打开管理区，避免额外播放本地墙。

产品模式采用固定上游源码的构建副本及外置集成补丁，在恢复媒体之前阻止 OBS collection 恢复，同时由产品界面接管编辑入口。原生宿主拥有服务进程、会话和媒体消费者。退出、撤销与会话过期都必须释放受保护来源。产品存储仍保留 Registry、Secret 引用及 Scene/Studio 文档，OBS collection 作为临时运行时映射。

One pinned OBS frontend owns local media. Reuse the existing Direct-only core for authenticated control and documents, with a single bounded loopback HTTP adapter. Product-mode hooks apply to a pinned build copy before scene restoration. Product data remains authoritative, while runtime OBS state is rebuilt after authorization. A native supervisor owns service lifetimes and media consumers.

## 功能清单 / Feature inventory

| ID | 旧入口与实际代码 | 新入口与迁移位置 | 数据与权限 | 组件 | 真实接线验证 | 状态与证据 | 当前阻塞 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AUTH | `LoginGate.tsx`、`AccountWorkspace.tsx`、core auth、cluster accounts | 原生登录/建账/退出，管理浏览器账号页 | 同一账号、绑定 userId/authEpoch，会话撤销 | core Direct-only、cluster | 安装后真实账号登录、改密/禁用/过期关闭画面 | 真实账号服务与原生登录接线；dev.91 便携 UI 建账/重登/重启/改密撤销通过 | 旧账号数据迁移、安装态、全部恢复/编辑旁路审计仍未完成 |
| RBAC | `UserAccessEditor.tsx`、cluster role/camera scope | 原生目录和每次执行/持续观看校验 | 角色、camera/group scope，未知来源拒绝 | cluster、Registry | 同名重建账号、换组、隐藏/嵌套来源、权限撤销 | dev.91 scoped viewer、普通 API 撤权/改密及仅投影 camera 撤权清屏通过；历史 dev.88/90 恢复 I/O 对照通过 | 本轮恢复探针前构建失败；全部原生编辑旁路和安装态安全审计未完成 |
| DEV | `CameraRegistry.tsx`、`camera_registry.py` | 原生摄像机/Profile 选择，本机设备管理页 | 稳定 camera/profile ID、Secret 引用 | camera、core | 选已有设备进入媒体源，禁用/缺失 Profile 可见报错 | dev.91 已有设备 API 到原生选择/五路最终像素、禁用与配置更新清屏、保存/登录恢复通过 | 旧个人设备数据迁移、完整 ONVIF/设备控制和安装态未完成 |
| IMPORT | `bulkSourceImport.ts`、ONVIF API | 设备库批量导入/ONVIF 页面 | 去重、配置保留、device.manage | camera、WebUI | 实际导入、失败不覆盖、重启保留 | 旧实现可用，原生未接线 | 管理入口与安装组件 |
| LIVE | `DirectPreview.tsx`、`ProgramPreview.tsx`、core OBS | 原生 OBS Media Source 与 Preview/Program | 认证后建图，同源兼容设置共享 | OBS、obs-ffmpeg | 真实插件、真实服务、动态 H.264/H.265 最终像素 | dev.91 五路合成 HEVC、重复源共享及主画面/固定投影最终像素通过；同画布切换保活新源码待 Windows | 真实相机/目标机硬解/性能/长稳及安装态仍待验证 |
| STUDIO | `SceneCollection.tsx`、`sceneSchema.ts`、`StudioController` | 原生场景切换/编辑与现有管理 Studio | Scene/Source UUID、草稿、revision、嵌套 | OBS、core、WebUI | 保存/恢复、裁剪/层级/锁定、冲突、TAKE | 已保存 Studio 场景选择、sceneId 登录恢复、revision 更新清屏在 dev.91 通过；Linux 引用/变换通过 | 完整编辑、嵌套/各布局 Windows 像素、TAKE/过渡、Preview/Program 与业务来源待接线 |
| LAYOUT | `monitorView.ts`、监控偏好、设备布局 | 原生网格/轮换/事件提升/主子码流 | 账号与设备偏好分离 | OBS、account、clients | 既有布局范围、人工选择、帧率/分辨率回读 | 原生未接线 | 不限五路的布局接线 |
| PROJECT | `ProjectorView.tsx`、desktop fixed projector IPC | 原生 Program 与固定 Scene 多投影 | 固定场景身份、同源引用 | OBS/Qt | 双固定场景、切 Program、重开/全屏/DPI | dev.91 双固定 Scene 共用来源、不同布局同时显示、F11/回窗、单个关闭和撤权退休通过 | 持续 Program 投影、DPI/多显示器与投影持久恢复未完成 |
| AUDIO | `AudioWorkspace.tsx`、`sourceAudio.ts`、schema-v6 | 原生混音/监听/电平，管理音轨页 | 账号监听偏好与项目轨道语义 | OBS、必要音轨适配组件 | 无重复扬声器输出、多轨保存、失效轨报错 | 相机源主音量/静音/监听/总线已映射；明确空 audioInputs 已接视频保留与强制无音频，Linux 实际 SDK policy 通过 | Windows 空选择场景待验证；非空逐轨适配、音轨 UI、电平及实际音频输出未完成 |
| OVERLAY | `MonitorProcessStatus.tsx`、analytics、隐私遮罩 | 原生叠层及管理配置 | 本地/录像/远端范围分开 | OBS、可选 analytics | 边框/检测框/音量表与最终像素、隐私遮罩 | 原生未接线 | overlay 来源和数据连接 |
| PTZ | `CameraDeviceControls.tsx`、`useShortTalk.ts` | 原生设备控制入口及管理页 | camera scope、移动脉冲、超时停止 | camera | 松键/断开停止、预置位、对讲收尾、快照 | 旧实现可用，原生未接线 | UI 与设备命令接线 |
| OUTPUT | core OBS 录像/推流、`SystemStatus.tsx` | 原生宿主按需求录制/推流 | 输出状态、退出保护、轨道 | OBS 编码/输出组件 | 本地关闭后持续任务、无需求编码器为零 | 原生未接线 | 单一输出所有者和 engine adapter |
| NVR | `NvrTimeline.tsx`、`nvr_service.py` | 本机录像管理入口与按需后台服务 | 原码流、配额、多卷、索引 | NVR、必要 FFmpeg | 计划、磁盘满、掉盘恢复、保留历史录像 | 旧实现可用，原生未接线 | 原生 supervisor 与安装 |
| EVIDENCE | `NvrExportPanel.tsx`、archive、timeline | 回放/归档/证据页面 | Range、审计、hash、lease | NVR、archive | 真实媒体 seek/大文件导出、路径与权限 | 旧实现可用，原生未接线 | 浏览器管理入口和媒体按需组件 |
| EVENTS | `EventsPanel.tsx`、`event_service.py` | 事件/规则/通知入口 | 权限、持久 outbox、重试预算 | events、可选通知集成 | MQTT/HA、重复抑制、重启恢复、事件录制 | 旧实现可用，原生未接线 | 后台消费者和组件安装 |
| DETECT | `AnalyticsWorkspace.tsx`、analytics providers | 检测配置/叠层及可选离线组件 | provider、任务授权、作用域 | analytics、模型/推理运行时 | 开关任务、lease/撤销、事件关联、成本增量 | 旧实现可用，原生未接线 | 按需进程与模型分发 |
| G2R | `Go2rtcWorkspace.tsx`、固定代理 | 本机管理页与来源适配 | `/api/v1/go2rtc/`、settings.manage | go2rtc | 配置保存、重载、HTTP/WS、凭据隔离 | 旧实现可用，原生未接线 | 按需需求和 supervisor |
| ONLINE | `Go2rtcOnlineSources.tsx`、`online_source.py` | 网站来源目录/Profile，原生观看 | 锁定提取器、Cookie 私密目录 | go2rtc、yt-dlp/Streamlink/EJS | 真实解析/relay/认证实播，预算与退出清理 | 旧实现可用，原生未接线 | 可选完整离线组件 |
| REMOTE | WebUI/PWA、Android 既有客户端 | 同一 Windows 服务的远程入口 | HTTPS、Origin、Direct/Composite scope | core、按需 gateway/Caddy | 既有客户端登录/播放，一个观看端退出不误停其他端 | 旧实现可用，原生未接线 | 原生引擎远端输出 adapter |
| OFFLINE | `DeviceSyncPanel.tsx`、`useDeviceSync.ts`、v2 | 受认证管理页与原生布局状态同步 | 签名/加密缓存、冲突、有限离线权限 | clients、core、WebUI | 离线编辑、重连冲突选择、Program 不被覆盖 | 旧实现可用，原生未接线 | 设备状态与原生 scene 映射 |
| OPS | `ProblemCenter.tsx`、`DeveloperDiagnostics.tsx` | 原生问题/诊断入口与受认证管理页 | 有界脱敏导出、settings.manage | core、业务服务 | 解码/组件/连接故障定位、脱敏支持包 | 帧输入进度与认证后的 OBS 原有统计窗口已接线，本机编译/协议通过，Windows UI 待执行 | 全进程实时总量、GPU 引擎、完整支持包和组件故障入口未完成 |
| BACKUP | backup 服务、原型 restore helper | 管理页及安装升级一致性备份 | 活跃 SQLite 快照、Secret、录像路径 | backup、原生 updater | 损坏/中断/磁盘满、幂等迁移和真实恢复 | 原型文件备份覆盖，完整迁移待实现 | 旧数据全量映射与数据库一致性 |
| LIFE | `main.mjs`、`supervisor.mjs`、`job_host.cpp` | 原生单实例/托盘/supervisor | Job、任务消费者、正常退出和崩溃收束 | Qt、Win32、按需服务 | 安装态关闭/托盘/后台任务/故意崩溃零遗留 | dev.91 便携入口固定 origin、正常退出、重启与 launcher 崩溃 Job 收束通过 | 托盘/后台任务、旧数据迁移及安装后生命周期未完成 |
| UPDATE | desktop updater/NSIS、稳定 feed | 原生更新设置/下载/确认/安装 | SHA-512/size、版本、备份、用户确认 | 原生 updater、NSIS | 旧稳定升级、新原生后续升级、截断/断网/失败恢复 | 原型 NSIS 部分通过，原生 updater 待实现 | electron-updater 替代与完整数据升级 |

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
