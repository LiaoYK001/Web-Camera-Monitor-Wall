# v2.2 operations workspace / v2.2 运维工作区

> Status / 状态：v2-M6 complete and published in `v2.2` / v2-M6 已完成并随 `v2.2` 发布。

v2.2 reorganizes the Local-first PWA around daily monitoring operations. The stable v2.1 media boundary does not change: approved HTTPS WHEP/HLS/MJPEG may remain `Camera → Browser`; ordinary RTSP is explicitly `Camera → Docker → Browser`; Profile preview never starts Composite Program.

v2.2 将 Local-first PWA 重组为日常监控运维工作区。v2.1 的媒体边界不变：获批的 HTTPS WHEP/HLS/MJPEG 可保持 `Camera → Browser`；普通 RTSP 必须明确显示为 `Camera → Docker → Browser`；Profile 独立预览不得启动 Composite Program。

## Workspaces / 工作区

The stable Hash routes are `#/monitor`, `#/studio`, `#/devices`, `#/audio`, `#/events`, `#/archive`, `#/storage`, and `#/settings`. Desktop uses a collapsible side-oriented information architecture; narrow PWA windows use bottom navigation and drawers. Monitor video contains only the source name, compact connection/problem status, and telemetry explicitly enabled by the operator. Full error text lives in Problem Center.

稳定 Hash 路由为 `#/monitor`、`#/studio`、`#/devices`、`#/audio`、`#/events`、`#/archive`、`#/storage` 与 `#/settings`。桌面使用侧边信息架构，窄屏 PWA 使用底部导航和抽屉。监看画面只保留来源名、小型连接/问题状态以及操作员主动启用的统计；完整错误文本统一进入问题中心。

## Registry v2 and preview / Registry v2 与预览

- One SQLite WAL migration advances `user_version` to 2 and adds device kind/enabled/group/tags/revision, Profile enabled/transport/live bitrate cap/audio expectation/probe state, bounded track descriptors, operational issues, and runtime policy.
- Existing Cameras and Profiles default to enabled, automatic transport, no group/tags/cap, and compatible legacy tracks. Re-running migration is idempotent.
- Lists paginate at 256, batches contain at most 256 atomic changes, tags contain at most 32 printable values, and each Profile caches at most 16 tracks.
- Display addresses remove URL userinfo, query and fragment. Catalog results are network-only and are not written to the offline PWA snapshot.
- The Profile preview constructs a one-source Scene v5 and reuses the normal browser media planner. Closing the dialog unmounts the player and releases its activation/WHEP session.
- Preview reports the actual TopologyPlan, execution owner, decoder and fallback reason, plus only the safe PTZ/snapshot/talk boolean capability summary. ONVIF service addresses never enter this response.
- Device-wide Probe checks all Profiles through the same one-camera/four-global bounded executor; Profile-specific Probe remains available for targeted diagnosis.
- A live bitrate cap affects only profile admission. It never edits camera firmware, NVR policy, or silently starts a transcoder.
- Plain HTTP media is fail-closed by default. `allowInsecureHttp=true` is a per-Profile operator exception for Docker Gateway/NVR ingestion only. It creates a visible warning issue and never qualifies an HTTPS PWA for Camera-to-Browser True Direct; the media plan reports `browser_https_required` and Docker remains the execution owner. Since media and any HTTP authentication may cross the network without TLS protection, use this exception only on a trusted LAN or a user-managed VPN.

## Problem Center / 问题中心

Server issues are deduplicated by `code + scopeKind + scopeId + component`; browser issues retain only stable IDs and an allowlist of technical fields. The UI supports severity/component/scope filters, acknowledge/resolved state, occurrence count, recommended actions and a redacted copy operation. Raw endpoints, credentials, response bodies, command lines, paths, PIDs and client addresses are forbidden.

服务端问题按 `code + scopeKind + scopeId + component` 去重；浏览器问题只保留稳定 ID 和技术字段白名单。界面支持级别/组件/范围筛选、确认/解决状态、发生次数、处理建议和脱敏复制。原始端点、凭据、响应正文、命令行、路径、PID 与客户端地址禁止进入问题记录。

## Audio workbench / 音频工作台

Direct playback creates one Web Audio analyser/gain/delay chain per source after an explicit user gesture. Composite uses one on-demand libobs volmeter per active source subscription. Both paths display RMS and Peak in dBFS and use Scene v5 `muted`, `volume`, `monitoring`, `syncOffsetMs`, and `audioTrack`; browser master monitoring volume is a local MonitorView v2 preference and never changes Program/NVR gain.

Direct 播放在明确用户手势后为每个来源创建独立 Web Audio analyser/gain/delay。Composite 为有订阅的活动来源按需创建 libobs volmeter。两条路径均以 dBFS 展示 RMS/Peak，并共享 Scene v5 的 `muted`、`volume`、`monitoring`、`syncOffsetMs` 与 `audioTrack`；浏览器监听主音量属于本地 MonitorView v2 偏好，不修改 Program/NVR 增益。

Unavailable audio is always rendered as `—`. MJPEG/Snapshot never triggers a server fallback merely to manufacture a meter. Polling is capped below 10 Hz and server volmeters detach after the subscription becomes idle.

## Release gate / 发布门禁

- Python migration/catalog/issue/settings tests, C++ CTest, TypeScript, production PWA build, public-repository audit and redaction tests must pass.
- Windows Chrome/Edge covers install, offline shell, responsive device catalog, Profile preview, Problem Center and Direct audio.
- WSL2 Chromium covers Docker integration, Registry migration, RTSP fallback, true-direct zero-server increment, Composite meters and all prior v1/v2 regressions.
- Long 16-stream/30-minute qualification remains optional and is not a v2.2 release claim unless revision-bound private evidence exists.
- v2.2 publishes only the GHCR image, immutable source Tag, checksums, SBOM, provenance and attestation. It does not publish EXE/APK/native or production IWA artifacts.
