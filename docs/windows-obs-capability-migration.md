# Windows 原生 OBS 能力迁移账本 / Native OBS capability migration ledger

日期 / Date: 2026-10-31。状态 / Status: **审计与迁移门槛，不是迁移完成声明 / audit and gates, not migration qualification**。

本账本落实 [P0–P5 计划](windows-obs-parity-dsh-plan.md)，与 [执行证据](windows-obs-parity-execution.md) 配套。完整兼容产品继续默认提供已有功能；`native-host/` 是隔离、非默认的 OBS frontend/Qt 原型。没有运行用户摄像头、停止后台任务或更换已发布安装器。

## 1. 不混淆媒体路径与控制面 / Separate media paths from the control plane

普通 `kind=rtsp` 且无显式非空 `audioInputs` 的来源，由 [OBS scene adapter](../core/src/obs_scene_runtime.cpp#L610-L645) 将原 URL 写入 `ffmpeg_source` 的 `input`，无需先经过 MediaMTX/go2rtc/Python 媒体中转。原生原型 [复用已有 OBS source UUID](../native-host/src/wall.cpp#L19-L64)，也不需要这些服务完成本地媒体解码/合成/投影。

这**不表示现有完整产品可以删除这些组件**。The local OBS media path and the existing account/control/background-service dependencies are different graphs.

- `kind=camera` 引用仍需 camera 服务解析设备和解码偏好：[source resolution](../core/src/obs_scene_runtime.cpp#L614-L621)。
- 显式音轨选择/混音，即使单条非默认轨，走 [gateway audio mix](../core/src/obs_scene_runtime.cpp#L582-L604)；失败显式拒绝，不能静默切回默认轨。未配置这一路由的普通 RTSP 才是直读。
- 浏览器名为 Direct 的路径仍由 [control server](../core/src/control_server.cpp#L1471-L1667) 建立 MediaMTX on-demand/兼容转码，不能把“浏览器 Direct”当作“OBS 原生直连”。

## 2. 实际启动与生命周期 / Actual startup and lifecycle

[Supervisor.start](../desktop/src/supervisor.mjs#L159-L175) 无条件启动 MediaMTX、go2rtc wrapper（再启动真实 binary）、camera、cluster、clients、events、NVR、backup schedule 与 core。archive 仅在配置存在时启动；Caddy 仅在 LAN 开启时启动。OBS Composite 编码可按读者启停，不等于整个网关进程已经按需。NVR 的外部 FFmpeg 是按实际配置 worker 启动，不应写成所有输入默认持续转码。

[Supervisor.stop](../desktop/src/supervisor.mjs#L177-L192) 逆序正常关闭；异常关闭阻断更新。[snapshot](../desktop/src/supervisor.mjs#L194-L198) 要求全部 writers 已停。原生宿主迁移要保留这些拥有关系，不能留下不受管的 sidecar。

## 3. 能力账本 / Capability ledger

以下测试是未来迁移可复用的验收入口，**不是本次重新运行或通过声明**。每项只有实际等价检查通过后才可退出旧路径。

| 能力 / Capability | 现有实现与原型差距 / Current implementation and gap | 退出门槛 / Exit gate |
| --- | --- | --- |
| 来源、稳定 ID、布局、Studio/Preview/Program/投影 | [scene source settings/reuse](../core/src/obs_scene_runtime.cpp#L555-L706)、[desktop projection IPC](../desktop/src/main.mjs#L104-L118)；原型只枚举已有 ffmpeg_source、非破坏建五格、Studio 送 Preview 并手动 TAKE：[wall](../native-host/src/wall.cpp#L19-L78) | 旧稳定 ID、持久化/撤销、全源类型、音轨/过滤器/转场、固定 Scene 多投影和 Preview/Program 分离有显式映射与回退。复用 [studio identity test](../desktop/tests/native-studio-identity.cjs)、[source identity test](../desktop/tests/native-source-identities.cjs)、[Program pixel test](../desktop/tests/native-program-preview.cjs)、[main smoke](../desktop/tests/native-main-smoke.cjs)。OBS 自带功能不等于产品数据已迁移。 |
| 账号、会话、Origin、RBAC、设置/管理 | [login/setup](../core/src/control_server.cpp#L4113-L4196)、[fresh authorization](../core/src/control_server.cpp#L4228-L4303)、[cluster accounts](../cluster/cluster_service.py#L715-L808)；原型没有产品登录/RBAC/账户存储 | 401/403、跨 Origin、过期/撤销/禁用用户、camera/group 作用域、服务不可用 fail-closed、改密和管理员隔离。复用 [account proxy](../tests/account_proxy_runtime.py#L78-L85) 与 [cluster service tests](../tests/test_cluster_service.py)。不得让 Qt 直连子 API 绕过产品 gate。 |
| 摄像头目录/凭据引用、ONVIF、PTZ、对讲/快照 | [camera API proxy](../core/src/control_server.cpp#L2174-L2195)、[PTZ stops](../camera/camera_registry.py#L3072-L3181)、[probe/event threads](../camera/camera_registry.py#L3943-L3946)；原型仅手动 OBS Media Source | 设备目录和凭据隔离、超时/迟到仍自动停 PTZ、对讲收尾、后台自动探测和事件订阅迁移。复用 [camera tests](../tests/test_camera_registry.py)、[camera runtime](../tests/camera_registry_runtime.cjs)、[device controls](../tests/device_controls_runtime.cjs)。不能按页面是否打开判断后台空闲。 |
| 浏览器 Direct/Composite、WebRTC/远程观看、go2rtc/网站 | [Direct/compatibility](../core/src/control_server.cpp#L1471-L1667)、[go2rtc gate](../core/src/control_server.cpp#L4327-L4343)、[demand encoding](../core/src/obs_engine.cpp#L1030-L1067)、[private website relay](../go2rtc/online_source.py#L245-L281)；原型未迁移这些消费者 | 保留 Direct-only、不强迫转码、单个 viewer 退出不影响他人、认证/WS/URL 私密性、固定提取器和 Job 清理。复用 [Composite demand](../desktop/tests/native-composite-demand.cjs)、[go2rtc runtime tests](../tests/test_go2rtc_runtime.py)、[online source runtime](../tests/online_source_runtime.cjs)。按真实订阅/任务启停，不因本地 OBS 直读而全局删除。 |
| 音频多轨选择/混音/监听 | [explicit tracks](../core/src/obs_scene_runtime.cpp#L582-L604) 目前依赖 MTX/transcoder；原型沿用 OBS source 设置，没有产品 bus/监听偏好迁移 | 输入 track 与输出 bus 的语义、同步、mute/volume/监听、失败不静默回退等价后才退出该适配。复用 [studio identity](../desktop/tests/native-studio-identity.cjs) 和 [main audio smoke](../desktop/tests/native-main-smoke.cjs#L145-L152)。 |
| 事件、规则、通知、分析 | [event/NVR/outbox](../events/event_service.py#L203-L227)、[event retry worker](../events/event_service.py#L485)、[analysis jobs](../cluster/cluster_service.py#L1217-L1437)；原型未迁移 | 去重、私密通知目标校验/有界重试、事件录像、分析授权/lease/撤销、持久触发器恢复。无规则/订阅/outbox/job 才能考虑休眠。复用 [event tests](../tests/test_event_service.py) 与 [cluster tests](../tests/test_cluster_service.py)。 |
| NVR、回放/证据链、导出、存储/归档 | [NVR maintenance/workers](../nvr/nvr_service.py#L580-L630)、[archive conditional startup](../desktop/src/supervisor.mjs#L168-L169)；OBS 录制不能代替 NVR 目录/时间线/证据/lease | 无录像、预录、事件规则、导出和播放 lease 才能休眠；锁定/删除/范围、hash、空间不足保全与故障恢复等价。复用 [NVR media](../tests/test_nvr_media.py)、[storage](../tests/test_nvr_storage.py)、[evidence](../tests/test_nvr_evidence_integration.py)、[archive](../tests/test_s3_archive.py)、[desktop evidence contract](../desktop/tests/native-evidence-contract.cjs)。 |
| 配对、媒体计划、账户布局同步/集群 | [pairing/grants](../v2/client_control_service.py#L435-L853)、[sync mutations](../v2/client_control_service.py#L1213)、[media plans](../v2/client_control_service.py#L1463)；原生 OBS scene 保存不是账户/client 同步 | 冲突版本、离线缓存、加密/签名与 scoped grants/撤销、同步队列恢复。复用 [sync](../desktop/tests/native-sync-contract.cjs)、[offline UI](../desktop/tests/native-offline-ui.cjs)、[main smoke](../desktop/tests/native-main-smoke.cjs#L126-L165)。cluster 另有账号/权限/存储/分析职责，不能随 clients 一并删除。 |
| 宿主 IPC、本地安全、单实例/托盘、正常退出/崩溃收束 | [main host boundaries](../desktop/src/main.mjs#L17-L90)、[IPC allowlist](../desktop/src/ipc-policy.mjs#L1-L13)、[Windows Job](../desktop/native/job_host.cpp#L38-L79)；原型 portable/禁 updater/清外来插件环境，不等于现有产品宿主语义 | 白名单命令/已知会话、精确 frame/payload、退出 dirty/export 门、托盘后台行为、二实例和 owner crash 无孤儿进程检查；原生启动烟测现已采样 obs64 后代、拒绝网关/转换/检测/网站辅助进程与服务端口、并在正常退出后确认安装根无残留（2026-11-01，dev.46），2026-11-01 dev.49 又增加故意强杀 obs64 的崩溃收束烟测（crashed=true、5 次采样、无残留/无监听端口），但仅覆盖进程级强杀且未观察到子进程，不覆盖二实例、插件/驱动崩溃、真实相机或长时间运行。复用 [main lifecycle smoke](../desktop/tests/native-main-smoke.cjs#L184-L203)、[packaged runtime smoke](../desktop/tests/packaged-runtime-smoke.mjs)。未等价前不移除 Electron。 |
| 私密数据、备份恢复、升级/安装/卸载 | [private root/DPAPI/mappings](../desktop/src/supervisor.mjs#L47-L108)、[private directory](../desktop/python/private_directory.py)、[consistent snapshot](../desktop/python/snapshot.py#L23-L65)、[backup scheduler](../backup/encrypted_backup.py#L330-L357)、[updater](../desktop/src/updates.mjs#L8-L114)；原型全新 portable 不导入、不覆盖；已有每用户 NSIS 安装/卸载保留 `config/` 与 `backups/`、新版本首次启动的逐文件哈希配置快照及 `restore_native_backup.py` 校验恢复，但仍无 Electron 数据迁移、加密备份、每 15 分钟调度或自动回滚 | 显式确认迁移、旧 schema/密钥/目录、hash/size 校验、用户确认/正常停写、失败回退、默认卸载留数据。复用 [encrypted backup](../tests/test_encrypted_backup.py)、[installed upgrade](../desktop/tests/installed-update-smoke.ps1)、[NSIS install](../desktop/tests/nsis-install-smoke.ps1)。自动备份每 15 分钟、每 2 秒 claim jobs，无 UI 不代表无任务。 |

## 4. 当前直接阻止粗暴裁剪的条件 / Immediate blockers to naive trimming

### 4.1 账号不是可直接懒启的 UI 附件

[Fresh authorization](../core/src/control_server.cpp#L4280-L4303) 对用户禁用/不存在、拒绝和授权服务不可用有撤销/401、403、503 的闭合行为。不能为了去掉 cluster/Python 改为“服务没开便默认允许”。新控制面要复用或等价实现会话存储、作用域和撤销；没有远程接口也不能冒称产品能力已经等价。

### 4.2 安全更新工作门当前要求 MTX/NVR 在线

[Supervisor.workload](../desktop/src/supervisor.mjs#L200-L205) 同时查询 NVR 与 MediaMTX，无法访问会阻止安装。未来能力状态须显式区分 `disabled / idle / active / unknown`，只有被完整验证的 disabled/idle 可不启动；`unknown` 仍阻断。先完成这一契约和持久任务引用图，才逐项 lazy-start；不能一停服务就破坏更新，亦不能把 HTTP 错误当作 idle。

### 4.3 CEF 不能直接从现有包删除

[OBS engine](../core/src/obs_engine.cpp#L694-L721) 的旧通用注释称按源类型加载，但 **Windows 分支实际无条件 require obs-browser/image-source/obs-text**，为了初始空 scene 后新增源可用。删除 CEF 会使现有 Windows engine 启动失败。[Runtime integrity](../desktop/src/runtime-integrity.mjs#L6-L14) 也列入 CEF、Python、MTX/go2rtc/Caddy/网站等完整组件，并 [逐文件 hash、真实路径与额外文件检查](../desktop/src/runtime-integrity.mjs#L37-L68)。将来新能力 profile 应生成独立完整性 manifest，不放宽现有验证以容忍缺失。

原型 `ENABLE_BROWSER=OFF / defaultProduct=false / servicesStarted=[]` 只证明隔离本地媒体原型可无 CEF，不是 Browser Source 迁移或删除授权。Qt 插件、FFmpeg/OBS/D3D11 ABI 继续按固定上游部署规则；不互换 avcodec 主版本 DLL。

### 4.4 不把现有 core 作为第二个 OBS renderer 搬入新宿主

[core entry](../core/src/main.cpp#L135) 直接调用 `run_obs_engine`。直接把完整旧 Supervisor 放进 Qt 宿主会启动第二套 OBS 媒体/渲染实例，违背消除冗余目标。先拆出 renderer-free 控制/认证适配契约，再接入同一 OBS source/scene/frontend 对象。

## 5. 下一最小安全实现 / Next minimal safe implementation

1. 固定旧包为回退，保持所有已有数据/账号/权限/备份/升级行为；原型仍是独立、明确标记的非默认入口。
2. 做 renderer-free 控制/认证适配契约：既有 session/Origin/RBAC、loopback 内部凭据、私密数据根与 Job 所有权；原生端仅调用白名单命令。先在全新 profile 验证首次登录、撤销、跨 Origin、fail-closed、正常退出及无孤儿进程。
3. 对旧 scene/schema 做只读 import dry-run，输出稳定 ID 映射、兼容性和不支持清单，不覆盖旧数据；用户明确确认后复制并保留回退。仅 URL 相同不表示来源连接、音轨、过滤器与解码设置兼容。
4. 建立持久任务/订阅引用图与上述更新工作门，再逐项按需启停网关、设备、NVR、网站、分析/归档。每项保留启动者、消费者、退出条件、异常清理者与 raw evidence。
5. P4 默认/扩展包分别固定版本、SHA-256、许可、SBOM/对应源码和显式下载确认；离线安装/卸载与数据保留实测。逻辑 unpacked bytes 不替代实际 post-install/allocated bytes，不以缺功能的原型与完整 OBS 做体积比较。
6. P2 首轮同机同源 OBS A/B、逐路实际硬解和 P5 三对交替/两小时稳定性仍须目标硬件。轮询 CPU/内存工具的 coverageIncomplete/strictTotal 边界不消失，未知 GPU/功耗/延迟/画面指标不得填零。

These are implementation gates, not permission to drop capabilities or weaken checks. Keep the complete fallback until evidence demonstrates equivalence, and retain the target-machine performance/size objectives as open.
