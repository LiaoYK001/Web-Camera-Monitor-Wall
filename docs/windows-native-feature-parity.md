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
| AUTH | `LoginGate.tsx`、`AccountWorkspace.tsx`、core auth、cluster accounts | 原生登录/建账/退出，管理浏览器账号页 | 同一账号、绑定 userId/authEpoch，会话撤销 | core Direct-only、cluster | 安装后真实账号登录、改密/禁用/过期关闭画面 | 接线开发中，现有原生身份基础可复用 | Qt 登录已接 core native API，Windows 安装态与执行一致性待验证 |
| RBAC | `UserAccessEditor.tsx`、cluster role/camera scope | 原生目录和每次执行/持续观看校验 | 角色、camera/group scope，未知来源拒绝 | cluster、Registry | 同名重建账号、换组、隐藏/嵌套来源、权限撤销 | 旧实现可用，原生未接线 | OBS 原生编辑和自动恢复入口 |
| DEV | `CameraRegistry.tsx`、`camera_registry.py` | 原生摄像机/Profile 选择，本机设备管理页 | 稳定 camera/profile ID、Secret 引用 | camera、core | 选已有设备进入媒体源，禁用/缺失 Profile 可见报错 | 原生未接线 | 已接授权目录与严格 Profile 解析，Windows UI/安装态待验证 |
| IMPORT | `bulkSourceImport.ts`、ONVIF API | 设备库批量导入/ONVIF 页面 | 去重、配置保留、device.manage | camera、WebUI | 实际导入、失败不覆盖、重启保留 | 旧实现可用，原生未接线 | 管理入口与安装组件 |
| LIVE | `DirectPreview.tsx`、`ProgramPreview.tsx`、core OBS | 原生 OBS Media Source 与 Preview/Program | 认证后建图，同源兼容设置共享 | OBS、obs-ffmpeg | 真实插件、真实服务、动态 H.264/H.265 最终像素 | 原型自动化通过，用户报告 dev.53 显示正常 | 完整账号/目录闭环 |
| STUDIO | `SceneCollection.tsx`、`sceneSchema.ts`、`StudioController` | 原生场景切换/编辑与现有管理 Studio | Scene/Source UUID、草稿、revision、嵌套 | OBS、core、WebUI | 保存/恢复、裁剪/层级/锁定、冲突、TAKE | 原生未接线 | 文档与 frontend 图映射 |
| LAYOUT | `monitorView.ts`、监控偏好、设备布局 | 原生网格/轮换/事件提升/主子码流 | 账号与设备偏好分离 | OBS、account、clients | 既有布局范围、人工选择、帧率/分辨率回读 | 原生未接线 | 不限五路的布局接线 |
| PROJECT | `ProjectorView.tsx`、desktop fixed projector IPC | 原生 Program 与固定 Scene 多投影 | 固定场景身份、同源引用 | OBS/Qt | 双固定场景、切 Program、重开/全屏/DPI | 原型 Program 像素覆盖，产品入口待接线 | 多投影授权和消费者寿命 |
| AUDIO | `AudioWorkspace.tsx`、`sourceAudio.ts`、schema-v6 | 原生混音/监听/电平，管理音轨页 | 账号监听偏好与项目轨道语义 | OBS、必要音轨适配组件 | 无重复扬声器输出、多轨保存、失效轨报错 | 原生未接线 | 音轨与运行时映射 |
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
| OPS | `ProblemCenter.tsx`、`DeveloperDiagnostics.tsx` | 原生问题/诊断入口与受认证管理页 | 有界脱敏导出、settings.manage | core、业务服务 | 解码/组件/连接故障定位、脱敏支持包 | 旧实现可用，原生未接线 | 产品内采样及统一诊断 |
| BACKUP | backup 服务、原型 restore helper | 管理页及安装升级一致性备份 | 活跃 SQLite 快照、Secret、录像路径 | backup、原生 updater | 损坏/中断/磁盘满、幂等迁移和真实恢复 | 原型文件备份覆盖，完整迁移待实现 | 旧数据全量映射与数据库一致性 |
| LIFE | `main.mjs`、`supervisor.mjs`、`job_host.cpp` | 原生单实例/托盘/supervisor | Job、任务消费者、正常退出和崩溃收束 | Qt、Win32、按需服务 | 安装态关闭/托盘/后台任务/故意崩溃零遗留 | 原型部分自动化通过 | 生命周期所有者迁移 |
| UPDATE | desktop updater/NSIS、稳定 feed | 原生更新设置/下载/确认/安装 | SHA-512/size、版本、备份、用户确认 | 原生 updater、NSIS | 旧稳定升级、新原生后续升级、截断/断网/失败恢复 | 原型 NSIS 部分通过，原生 updater 待实现 | electron-updater 替代与完整数据升级 |

## 进程和体积口径 / Process and size accounting

旧 `Supervisor.start` 默认启动 MediaMTX、go2rtc wrapper、camera、cluster、clients、events、NVR、backup 与 core，archive 和 Caddy 依据配置启动。原生核心拟默认启动 OBS host、control-only core、账号和设备目录服务，其他消费者由真实功能需求启停。Python 业务实现保留并计入实际组件成本，组件名称不能用于推断是否转码。

旧 dev.18 footprint 总逻辑字节 1,459,397,091，其中 Electron shell 388,050,826、独立 runtime/bin 432,284,496、OBS 树 352,434,045、Python 172,898,288。数据来自其已发布 footprint，最终完整安装重新计量。原型约 99 MB 的历史证据仅作为核心媒体基线。R5 分别记录下载、安装逻辑/分配、首次运行新增、离线完整组件与功能增量，包含所属树外进程。

The old full-runtime baseline is 1,459,397,091 logical bytes in published dev.18. Its Electron shell, separate tools, OBS tree and Python runtime dominate the payload. The native prototype's roughly 99 MB receipt applies to its measured component scope. R5 measures the integrated core and complete installation afresh, including optional/offline components and owned external processes.
