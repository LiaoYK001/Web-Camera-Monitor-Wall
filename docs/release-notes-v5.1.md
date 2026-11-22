# v5.1 Windows 完整融合版 / Complete Windows fusion release

状态：完整候选已冻结待集中验收；未进入 Latest 或稳定更新源。/ Status: a complete candidate is frozen for centralized acceptance; outside Latest and the stable updater feed.

## 候选身份 / Candidate identity

下表在候选冻结时绑定实际字节；发布前每一项都必须来自同一次 Windows 运行，不沿用其它包的摘要。正式 Tag 映射为 **Tag `v5.1` · 应用与安装器版本 `5.1.0`**。
Every value below comes from one Windows run and is bound at freeze. The stable mapping is **Tag `v5.1` with application/installer version `5.1.0`**.

| 项目 / item | 值 / value |
| --- | --- |
| 候选版本 / candidate version | `5.1.0-rc.100` |
| 源码提交 / source revision | `066252efe10688137f1718d3af7054a09c7f1378` |
| Windows 运行 / Windows run | [45045849743](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/45045849743) |
| 安装器 / installer | `WebOBS-Wall-5.1.0-rc.100-windows-x64-SETUP.exe` |
| 安装器字节与 SHA-256 / installer bytes and SHA-256 | 212,169,982 B · `83cdc5c5f083d7bff62ce9de57936c863e521ca4b11fcc832bea9a84a703b9c8` |
| `latest.yml` SHA-512 与 size | 212,169,982 B · `0inHwokwc4o1LNC6E6bZogN4O1A6U3mKzVpe9VKGCocLvyqrEtU6nVD30flV0fcORslraUjPlBKRVM7Q8PUj6w==` |
| 组件体积拆分 / component size split | `docs/windows-component-size-split.md` |

## 安装后的实际入口 / Real entries after installation

| 开始菜单项 / Start Menu entry | 实际入口 / what it runs |
| --- | --- |
| **WebOBS Wall** | `bin/webobs-wall.exe`，唯一的原生宿主启动入口 / the only native host launcher |
| **WebOBS Wall - Import old data** | `MIGRATE-LEGACY.cmd`，导入受支持的旧 4.x 与 v4.5 档案 / import supported legacy 4.x and v4.5 profiles |
| **WebOBS Wall - Check for updates** | `CHECK-UPDATES.cmd`，读取固定更新源并须经用户确认才安装 / reads the pinned feed and installs only after user confirmation |
| **WebOBS Wall - Restore backup** | `RESTORE-BACKUP.cmd`，恢复双目录加密备份 / restore the dual-directory encrypted backup |

安装目录 / install directory: `%LOCALAPPDATA%\Programs\WebOBS Wall`。私有数据 / private data: `%LOCALAPPDATA%\WebOBS\Native`（账号配置、OBS profile、录像索引、密钥、备份、支持包）。卸载默认保留该数据目录、录像与未知文件，只删除已验证的包内文件。Uninstall keeps that private data directory, recordings and unknown files and removes only verified packaged files.

原生窗口控制板提供：开始原生监看、保存布局、刷新设备目录、退出账号、已保存 Studio 场景监看、固定场景投影、Program 投影、**录制 Program**、**推流 Program**、输出健康状态、**生成支持包**、**开启局域网共享**及其状态；关窗在有活动 Program 输出时进入托盘、托盘重显复用同一宿主（源码已接线；CI runner 没有系统托盘，这一条需要目标机验收）。
The single control panel provides watch, save layout, refresh catalog, logout, saved Studio scene watch, fixed projectors, Program projector, **Record Program**, **Stream Program**, output health, **Generate support bundle** and **Enable LAN sharing**; closing hides to the tray and re-showing reuses the same host.

## 相对 v5.0.0-rc.1 新增 / Added since v5.0.0-rc.1

1. **多轨音频 / multi-track audio**：逐轨混音、监听、电平与逐轨静音/增益/偏移；Program 产物解码实际音轨。AAC/Opus 编码器创建改用具名 `QByteArray` 保存的编码器名与所选总线标签，修复非默认总线下“电平有信号、录制/推流静音”，OBS mixer 索引仍从零开始。
2. **Program 合成输出 / Program composite output**：同一个宿主把实际 Program 画面与混音录成 MP4（MKV→MP4 流复制），并以回环 RTMP 发布到私有 MediaMTX，再由中继提供 RTSP/WHEP；无任务时不启动编码器或 MediaMTX，停止、断线、撤权、退出释放进程。私有中继的 API、RTSP、WHIP/WebRTC 与 ICE UDP 监听全部按空闲回环端口分配，不写死端口也不占用产品分发网关 MediaMTX 的 8889（Windows 还会预留动态端口段，固定端口可能在无人监听时也无法绑定）；任何一次推流拒绝都把具体原因写入 `streamError`，不静默。验收落到实际收到的产物：录制文件与回环发布接收端解码确认选中总线音调、未选总线不串音、视频帧持续推进。 已知行为：节目混音子进程只有在 ffmpeg 打开相机输入之后才绑定本地端点，切换 Program 场景后音频需要数秒才可用；媒体源首开失败后按 1 秒重连恢复，录制与推流都会先等待混音真正出音，实测建立时长以 `programMixLeadIn` 记录在回执中，不隐藏。
3. **备份一致性 / backup consistency**：双目录加密备份按成对交换收敛；中断的恢复在普通产品启动时、持有数据目录独占锁且创建配置与 OBS profile 之前处理并可重试；旧版仅含配置的备份保留现有原生档案。
4. **真实 LAN/Web 入口 / real LAN entry**：开启后由打包 Caddy 提供 HTTPS，账号与逐相机权限不变；缺组件、端口占用或 TLS 失败时失败关闭，不降级明文 HTTP。启用共享时 go2rtc 的 WebRTC 监听绑 `0.0.0.0` 以便同网设备连接（刻意行为，管理面与内部媒体监听仍回环）。
5. **支持包 / support bundle**：有界脱敏状态、计数与 OBS 标记统计，含 Program 输出与 LAN 的失败原因；不含摄像机地址、令牌、日志正文或媒体。
6. **发布身份与发布链 / release identity and chain**：Tag `v5.1` 与应用/安装器版本 `5.1.0` 的单一映射、验收文件契约、候选发布 `--verify-only` 与 `main` 可达校验。
7. **体积拆分与同机 OBS 对照 / size split with a same-OS OBS comparison**：本轮安装树有 6,973 个文件，占 794,763,016 逻辑字节、806,813,008 分配字节；体积回执列出 OBS 32.1.2 参考值 479,371,662 逻辑字节。 / The installed tree contains 6,973 files, 794,763,016 logical bytes and 806,813,008 allocated bytes. The receipt lists 479,371,662 logical bytes for the OBS 32.1.2 reference.
8. **安装态长稳门禁 / installed soak gate**：安装态连续 ≥2 小时逐路帧进度、CPU 秒、私有内存、句柄与子进程集合采样；停滞、进程增减、内存或句柄增长、进程树不工作都会让本次运行失败。

## 尚未包含或尚未验收 / Concrete gaps

以下是具体缺口，不是“还需测试”：OVERLAY 原生叠层未接线；DETECT 最终叠层像素未在门禁开启；OFFLINE 设备同步未接入原生宿主；PTZ/预置位/对讲缺真实 ONVIF 设备证据；MQTT/Home Assistant 实际投递未验证；公开网站解析与长直播未验收；真实五路 H.265、RTX 4090 Laptop 逐路硬解、物理多屏/DPI/睡眠唤醒、用户本人旧档案以及同画质同布局下完整进程树 CPU/GPU/内存是否 ≤ 原生 OBS，都需要用户目标机集中验收；未签名、不进入稳定 feed，旧稳定版本 → v5.1 实机升级未验收；Android、容器与 Linux/ARM 扩展端保持暂停。

Windows CI 在 GitHub-hosted Windows Server 2022 上用合成五路 H.265/H.264 夹具与合成音调检验便携、安装态、升级后与长稳门禁，回执只含脱敏合成数据；CI 通过不等于物理机器、真实相机、逐路硬解、多显示器或 OBS 同机性能达标。

## rc.100 自动验收与实机清单 / Automated and device validation

rc.100 的十类回执齐全，覆盖便携入口、NSIS 安装、升级后入口、旧数据导入、加密备份与中断恢复、更新器、体积拆分和 120 分钟安装态长稳。121 个样本中，进程树累计 CPU 时间增加 1,128.43 秒，私有内存增加 1,241,088 字节，句柄增加 28 个。局域网回执因运行器没有私有 IPv4 跳过 HTTPS 与第二设备操作。[Windows CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/45045849743)

All ten rc.100 receipts are present, including NSIS install, post-upgrade checks, legacy import, encrypted backup and interrupted restore, updater, size accounting, and the 120-minute installed soak. Across 121 samples, total process-tree CPU time increased by 1,128.43 seconds, private memory by 1,241,088 bytes, and handles by 28. The runner had no private IPv4 address, so LAN HTTPS and the second-device test were skipped.

1. 安装前保留现有配置与原生档案的加密备份。安装、重启、卸载后核对数据保留，并在隔离数据上试一次恢复。 / Back up existing configuration and native profiles before installation. Verify data retention and rehearse restore on isolated data.
2. 用五路真实 H.265 检查逐路硬解、画面推进、TAKE、录制及推流重连。与同画质同布局的 OBS 比较 CPU、GPU、显存和内存。 / Check hardware decode and frame progress on five real H.265 feeds, TAKE, recording, and stream reconnect. Compare full-process CPU, GPU, VRAM and RAM with OBS at the same layout and quality.
3. 检查多屏/DPI、睡眠唤醒、音频及托盘行为。用第二台设备验证 HTTPS、权限、播放和相机控制。 / Check physical displays, DPI, sleep/wake, audio, and tray behavior. Verify HTTPS, permissions, playback, and camera controls from a second device.
4. 用本人旧档案副本核对导入和升级。记录首次失败点及脱敏支持包；历史前端崩溃和恢复暂存相关风险仍开放。 / Verify import and upgrade with a copy of your old profile. Record the first failure and sanitized support bundle. Historical frontend crashes and interrupted-restore staging remain open.

## 历史进展记录 · 首轮修复与更新链门禁 / Prior hardening log

（历史记录，写于本次候选构建之前）状态：当时开发中，未构建完整候选、未发布。用户2026-11-17要求以v5.1正式交付为目标，并在其Windows上主要验证v5.1。

2026-11-18 历史 Windows 门禁：[run 44194328169](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44194328169) 在源码 `472f3fe5cddf90f304801aab4dccd4765b0076f2` 上 success，内部版本 `5.1.0-rc.16`。便携/安装态/升级后各 55 项、恢复隔离 9/9；真实已安装更新器完成同源码 `rc.16 → rc.17` 的下载、改写缓存拒绝、加密备份、NSIS 升级、版本切换和恢复。升级前后 durable profile 指纹 30/30 一致，卸载保留用户数据。安装器 212,162,215 B，SHA-256 `12039948205f915de180eb0a84f74d0b51ef3fd737a30234851305dbe4242dbd`；安装树首启前 794,579,783 logical / 806,620,488 allocation B、6,972 文件。完整摘要见[资格记录](qualification/windows-v51-update-gates-2026-11-18.json)。

该结果只关闭更新/安装/升级链的首轮实际门禁，不是正式 v5.1 发布：非空逐轨音频、同一原生宿主的 Program 合成录像/推流、LAN/Caddy 远端/离线、完整旧档案迁移、物理多屏/DPI/音频/硬解和两小时长稳仍未关闭。`fullFeatureMigrationQualified=false`、`hardwareDecodeVerified=false`；内部 rc.16/rc.17 字节不创建公开 Release，也不打开稳定 feed。

### 完整功能接线增量 / integration increment

- 多轨声音：显式非空 `audioInputs` 由音频专用 FFmpeg 逐轨 `track/gain/mute/syncOffset` 混音，经本机 TCP MPEG-TS 送入同一 OBS 场景的单一音频源；视频仍直接 RTSP。OBS 输出总线、监听、主音量、volmeter dBFS、`audioSources` 诊断和失败清理已接线；空 `audioInputs` 和旧语义保持不变。
- Program 合成输出：同一原生宿主按需创建 x264 + AAC 编码器；录像先写私有临时 MKV，停止后由锁定 FFmpeg 流复制成 MP4；推流按需启动私有 MediaMTX，宿主以回环 RTMP 发布 Program 混音，中继再对外提供 RTSP 与 WebRTC/WHEP，停止后释放。无输出任务时不创建编码器、不启动 MediaMTX。活动输出期间关闭主窗口保留托盘宿主，可恢复或显式停止退出。
- 备份与诊断：加密备份同时包含 `config` 与 `native-profile`，旧 config-only 包兼容且不删除现有工作区；原生支持包导出固定 schema 的版本/启动/渲染器/媒体/音频/Program 计数和 OBS 标记统计，不含 URL、令牌、日志正文、媒体或输出路径。
- 合成双音轨、MP4 H.264/AAC、八帧合成像素、发布后 RTSP H.264/AAC、实际视频帧、支持包脱敏和 MediaMTX 退出已加入 Windows 门禁；目标机真实摄像头/扬声器、编码性能、LAN/Caddy、离线同步和两小时长稳仍需主要验证。固定 Windows OBS 树以 `-DENABLE_WEBRTC=OFF` 构建且锁定的 vcpkg 归档不含 LibDataChannel，因此不存在 `whip_custom`/`whip_output`；OBS 侧 WHIP 推流仍是已记录缺口，Program 现走同机 RTMP→MediaMTX→RTSP/WHEP。

Windows rc.23（音频）与 rc.24（Program 输出/备份/支持包）完整门禁：结果以实际 run 回执为准，未通过前不作为发布资格。

优先修复rc.1审查确认的v4.5工作区迁移路径、缓存安装包执行前完整性校验和预发布版本比较。继续现有R2–R7的完整声音、OBS合成输出、远端/离线、迁移/更新、后台任务、体积性能及稳定性工作；不能把未接线项归为仅待实机。

保留v4.5与v5.0.0-rc.1的公开字节。开发只面向dev，正式发布按指定版本审查流程，Windows x64之外的暂停交付范围不变。最终说明必须绑定实际源码、安装包、回执及剩余目标机未测项。

已接入首批修复：v4.5工作区读取真实OBS插件配置路径，并与账号配置一起提交到新profile；提交失败恢复原空目标，允许重试。更新执行前对缓存EXE重新核对实际大小/SHA-512，并在备份后再次核对；拒绝无更新/回退及缺少必要备份材料。预发布版本按数字标识比较，支持rc.9→rc.10与忽略build metadata。

本机SQLite/文件迁移与故障注入、HTTP更新下载和缓存损坏负向回归通过；安装执行器在这些本机测试中为隔离mock，不能当作新Windows安装/个人旧档案验证。完整声音、输出、远端/离线及性能资格仍未完成。

构建管线已支持精确的5.1.0-rc.N内部验收候选（不开放稳定发行）。Windows门禁新增真实Qt保存工作区的迁移/登录恢复、独立运行时版本及清单的升级测试包、经过已安装更新器的下载/改写缓存拒绝/备份/NSIS执行，以及升级后产品入口与媒体。测试包仍为同源码构造的下一版本夹具，不冒充已发布下一版本。候选发布脚本新增必填`-SourceRevision <40位SHA>`，避免Tag默认落到无关分支；Windows实际结果仍需新run回执。

投影窗口增加按账号持久保存的屏幕、位置、大小和全屏偏好，复用现有workspace与OBS窗口；原显示器缺失时，约束到当前桌面可见区域并回退窗口模式。位置写入在移动/缩放后去抖，不增加空闲轮询。保存的是窗口偏好，打开仍经现有授权；尚未自动恢复多个固定Scene媒体窗口。Qt几何回归及界面语法检查通过，新Windows最终窗口门禁待执行；物理多屏/DPI仍待主要验证。

维护流程继续修复：检查更新不再把带单引号的Windows路径拼进Python代码；已是最新时结束，不再要求安装；自定义安装位置与安装前实际版本重新核对，稳定通道拒绝预发布更新。支持GitHub正式Latest资产路径，但未提前启用稳定feed。恢复备份命令补齐停止检查、明确确认和打包libsodium路径。

更新改用安装树之外的独立维护解释器，避免更新自身Python文件时占用；仅复制嵌入解释器和维护依赖，不带可选site-packages，临时字节计入维护回执，完成后在后续产品启动清理。Windows门禁将从已安装Python创建维护工具，退出该解释器后再执行NSIS，并恢复真实加密备份核对数据库语义。新的实际Windows结果仍待后续源码回执，不用早先c689e1b运行冒充这些修改已验证。

In development, not a qualified candidate or a published release. The requested v5.1 delivery hardens migration and updates and completes outstanding product integration. Published v4.5/rc.1 bytes remain immutable; no unmeasured target-device or OBS-parity claim is implied.
