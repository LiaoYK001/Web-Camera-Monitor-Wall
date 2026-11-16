# Windows WebOBS Wall 功能迁移矩阵 / Feature parity matrix

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
| AUTH | `LoginGate.tsx`、`AccountWorkspace.tsx`、core auth、cluster accounts | 原生登录/建账/退出，管理浏览器账号页 | 同一账号、绑定 userId/authEpoch，会话撤销 | core Direct-only、cluster | 安装后真实账号登录、改密/禁用/过期关闭画面 | v4.5 最终便携/安装：真实建账、登录/重登、改密/禁用/重启撤销通过；本机双模式 HTTP 回归含 epoch/撤权/队列复检与设备管理面 viewer-403 | R1-001 全入口审计(2026-11-16)已核对 core/native/cluster 实际入口并补 v2 设备管理面与排队读栅栏；旧账号数据迁移、旧数据 ACL 与同源码 Windows 产品覆盖仍开放 |
| RBAC | `UserAccessEditor.tsx`、cluster role/camera scope | 原生目录和每次执行/持续观看校验 | 角色、camera/group scope，未知来源拒绝 | cluster、Registry | 同名重建账号、换组、隐藏/嵌套来源、权限撤销 | v4.5：逐相机/Profile目录与执行、持续撤权、投影退休、认证前恢复 I/O 隔离通过 | R1-001 审计确认 native mutation 执行时双重 validate/epoch 回声与 v2 设备管理面 node.manage；Studio/输出/编辑完整执行栅栏、角色/组跨快照一致性、旧数据 ACL 与 Windows 同源码覆盖仍开放 |
| DEV | `CameraRegistry.tsx`、`camera_registry.py` | 原生摄像机/Profile 选择，本机设备管理页 | 稳定 camera/profile ID、Secret 引用 | camera、core | 选已有设备进入媒体源，禁用/缺失 Profile 可见报错 | v4.5：设备 API 到原生五路/Profile选择、禁用/变更/保存恢复通过 | 旧个人设备导入、完整 ONVIF/PTZ/对讲与设备实测未完成 |
| IMPORT | `bulkSourceImport.ts`、ONVIF API | 设备库批量导入/ONVIF 页面 | 去重、配置保留、device.manage | camera、WebUI | 实际导入、失败不覆盖、重启保留 | 管理页接入手动/批量设备；Linux实际服务+Chromium首用新增1+4路并读取5路，缺FFprobe仍可保存 | 浏览器首用证据不替代完整 Windows ONVIF/大批量/旧数据导入验收 |
| LIVE | `DirectPreview.tsx`、`ProgramPreview.tsx`、core OBS | 原生 OBS Media Source 与 Preview/Program | 认证后建图，同源兼容设置共享 | OBS、obs-ffmpeg | 真实插件、真实服务、动态 H.264/H.265 最终像素 | v4.5：五路动态 HEVC、实际最终像素、同源复用、输入推进、断流恢复、重启和撤权通过 | 真实相机、逐路硬解、目标机同条件OBS对照与长稳仍待；v5.0快捷墙1/4/7路Windows动态像素通过；64为有界接口/网格，不是64解码器实测 |
| STUDIO | `SceneCollection.tsx`、`sceneSchema.ts`、`StudioController` | 原生场景切换/编辑与现有管理 Studio | Scene/Source UUID、草稿、revision、嵌套 | OBS、core、WebUI | 保存/恢复、裁剪/层级/锁定、冲突、TAKE | v4.5：已保存相机场景/sceneId认证后恢复、内容前置条件及本地Preview与空Program分离通过 | 完整编辑、原子文档/运行时bridge、TAKE/过渡及业务来源未接线 |
| LAYOUT | `monitorView.ts`、监控偏好、设备布局 | 原生网格/轮换/事件提升/主子码流 | 账号与设备偏好分离 | OBS、account、clients | 既有布局范围、人工选择、帧率/分辨率回读 | 受支持的已保存相机场景可映射布局/裁剪/层级；不同固定Scene最终画面通过 | v5.0快捷墙1–64路源码与本机几何/真实libobs复用通过，Windows便携及安装1/4/7路通过；完整编辑/复杂嵌套仍未完成 |
| PROJECT | `ProjectorView.tsx`、desktop fixed projector IPC | 原生 Program 与固定 Scene 多投影 | 固定场景身份、同源引用 | OBS/Qt | 双固定场景、切 Program、重开/全屏/DPI | v4.5：两固定Scene共用来源、不同布局、全屏/回窗/关闭与仅投影相机撤权清屏通过 | 持续Program投影、物理多屏/DPI与投影持久恢复未完成 |
| AUDIO | `AudioWorkspace.tsx`、`sourceAudio.ts`、schema-v6 | 原生混音/监听/电平，管理音轨页 | 账号监听偏好与项目轨道语义 | OBS、必要音轨适配组件 | 无重复扬声器输出、多轨保存、失效轨报错 | 相机主音量/静音/监听/总线映射与显式空audioInputs无音频policy已接；v4.5空选择场景视频通过 | 非空逐轨、音频UI/电平、实际解码采样/扬声器与输出混音未完成 |
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
| OPS | `ProblemCenter.tsx`、`DeveloperDiagnostics.tsx` | 原生问题/诊断入口与受认证管理页 | 有界脱敏导出、settings.manage | core、业务服务 | 解码/组件/连接故障定位、脱敏支持包 | v4.5：输入推进/停滞、认证OBSBasicStats和实际渲染器标签进入便携/安装入口 | 尚非全进程CPU/内存或分引擎GPU/显存；支持包与完整故障入口未完成 |
| BACKUP | backup 服务、原型 restore helper | 管理页及安装升级一致性备份 | 活跃 SQLite 快照、Secret、录像路径 | backup、原生 updater | 损坏/中断/磁盘满、幂等迁移和真实恢复 | 仅历史原型文件备份；v4.5认证前恢复隔离不是旧数据迁移/全库备份验收 | 旧数据全量映射、活跃SQLite一致性、失败恢复与幂等迁移仍未完成 |
| LIFE | `main.mjs`、`supervisor.mjs`、`job_host.cpp` | 原生单实例/托盘/supervisor | Job、任务消费者、正常退出和崩溃收束 | Qt、Win32、按需服务 | 安装态关闭/托盘/后台任务/故意崩溃零遗留 | v4.5：独立安装/NativePreview数据、Unicode路径、快捷方式、origin、重启、退出/崩溃回收、卸载保留通过 | 托盘/后台任务、完整业务消费者、旧版升级/覆盖安装仍未完成 |
| UPDATE | desktop updater/NSIS、稳定 feed | 原生更新设置/下载/确认/安装 | SHA-512/size、版本、备份、用户确认 | 原生 updater、NSIS | 旧稳定升级、新原生后续升级、截断/断网/失败恢复 | v4.5明确手动卸载换包，无原生updater；旧electron-updater不进入新默认包 | 下载SHA-512/size、确认安装、正常停机、备份恢复及旧版升级仍待原生接线 |

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
