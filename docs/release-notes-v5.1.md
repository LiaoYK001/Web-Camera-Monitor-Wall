# v5.1 Windows 完整修复版 / Windows integration hardening

状态：开发中，未构建完整候选、未发布。用户2026-11-17要求以v5.1正式交付为目标，并在其Windows上主要验证v5.1。

2026-11-18 最新内部 Windows 门禁：[run 44194328169](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44194328169) 在源码 `472f3fe5cddf90f304801aab4dccd4765b0076f2` 上 success，内部版本 `5.1.0-rc.16`。便携/安装态/升级后各 55 项、恢复隔离 9/9；真实已安装更新器完成同源码 `rc.16 → rc.17` 的下载、改写缓存拒绝、加密备份、NSIS 升级、版本切换和恢复。升级前后 durable profile 指纹 30/30 一致，卸载保留用户数据。安装器 212,162,215 B，SHA-256 `12039948205f915de180eb0a84f74d0b51ef3fd737a30234851305dbe4242dbd`；安装树首启前 794,579,783 logical / 806,620,488 allocation B、6,972 文件。完整摘要见[资格记录](qualification/windows-v51-update-gates-2026-11-18.json)。

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
