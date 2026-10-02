# v2.2 operations workspace / v2.2 运维工作区

> Status / 状态：v2-M6 complete and published in `v2.2` / v2-M6 已完成并随 `v2.2` 发布。

v2.2 reorganizes the Local-first PWA around daily monitoring operations. The stable v2.1 media boundary does not change: approved HTTPS WHEP/HLS/MJPEG may remain `Camera → Browser`; ordinary RTSP is explicitly `Camera → Docker → Browser`; Profile preview never starts Composite Program.

v2.2 将 Local-first PWA 重组为日常监控运维工作区。v2.1 的媒体边界不变：获批的 HTTPS WHEP/HLS/MJPEG 可保持 `Camera → Browser`；普通 RTSP 必须明确显示为 `Camera → Docker → Browser`；Profile 独立预览不得启动 Composite Program。

## Workspaces / 工作区

### Current interaction refinements / 当前交互优化

主导航按工作台、媒体与数据、系统分组，图标配合文字。桌面点击“快速切换”或按 Ctrl+K（macOS 为 Cmd+K），可以按页面名称或用途搜索；↑/↓ 选择，Enter 打开，Esc 关闭。移动端“更多”显示页面用途，滚动菜单后关闭按钮仍可触达。切换页面或账号配置前保留现有未保存修改检查；取消后继续编辑。

Navigation groups workspaces with icons and labels. Quick Switch supports Ctrl+K/Cmd+K, purpose-based search, arrow selection, Enter and Esc. Mobile More describes each destination and keeps Close reachable. Navigation and account-profile switching respect unsaved edits.

系统设置的分区入口可直达账号配置、客户端设置、播放优化、运行设置、关于与更新。播放优化标记为“按账号立即保存”；运行设置标记手动保存与待保存状态。普通页面使用文档滚动，桌面 Studio 保留画布工作区内滚动。弹窗阻止背景滚动，Esc 关闭并恢复焦点；从弹窗内拖到背景不会误关闭。系统选择减少动态效果时关闭进入动画及循环动效。

Settings section shortcuts distinguish immediate account preference saving from explicitly saved runtime settings. Ordinary pages scroll in the document, while desktop Studio keeps its canvas workspace scroll. Dialogs lock background scrolling, restore focus and ignore drags that end on the backdrop. Reduced-motion preferences disable entrance and looping animations.

场景卡区分 Program、Preview、待保存状态；选项按管理、布局与顺序、投影、删除分组，可用方向键浏览。F2 重命名。来源搜索保留已勾选项，也可清空选择。应用到草稿后仍需“保存并应用”。重叠来源的缩放手柄使用独立编辑覆盖层，不改变节目画面的来源层级。设备列表翻页回到顶部，保存时避免重复提交，批量导入完成或停止前提示等待；未改变或无效的码率上限不会写入。

Scene cards distinguish Program, Preview and pending saves. Grouped actions support keyboard navigation and F2 rename; source search retains selection. Drafts still require Save and Apply. Resize handles use an independent editing overlay without changing program layers. Catalog paging returns to the top, mutations prevent repeat submissions, bulk import guards navigation, and unchanged or invalid bitrate caps are not written.

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

当前开发版的问题中心使用可键盘操作的侧栏弹窗，默认显示未解决的问题。可筛选待确认、已确认、已解决或全部状态，并手动刷新。确认请求执行期间禁用重复提交；失败时显示原因并允许重试。复制诊断失败时可展开技术详情手动复制。按 Esc 或“关闭”退出后，焦点回到打开侧栏的按钮。

The current development version uses a keyboard-accessible drawer dialog, showing unresolved issues by default. Filter open, acknowledged, resolved, or all issues and refresh manually. Acknowledgment disables duplicate submissions and displays failures for retry. If copying fails, expand technical details and copy manually. Esc or Close returns focus to the opener.

## Current settings workflow / 当前设置操作

“系统设置 → 运行设置”支持集中编辑后点击“保存设置”。只提交发生变化的字段；探测超时限定 2–30 秒，问题保留上限限定 128–4096 条。保存失败保留输入；“撤销修改”恢复已载入的值。遇到版本冲突时使用“重新读取设置”，重新读取或离开页面前会提醒未保存的修改。

账号配置档案及当前档案选择供同一账号的其他设备使用；本机备份仍保留在当前浏览器。保存、切换、导入、删除和恢复操作执行期间禁用重复操作。删除当前档案同时清除服务端的档案选择。

Under **Settings → Runtime settings**, edit fields and choose **Save settings**. Only changed fields are sent. Probe timeout accepts 2–30 seconds; issue retention accepts 128–4096 entries. Failed saves retain edits; Undo restores the loaded values. On a revision conflict, reload settings. Reloading or leaving warns about unsaved changes.

Account profiles and the active selection are available on other devices using the same account; local backups remain in the current browser. Save, switch, import, delete, and restore operations prevent duplicate actions while in progress. Deleting the active profile also clears its server-side selection.

交互回归 / Interaction regression: 在 `web` 目录运行 / Run from `web`: `npx playwright test -c playwright.usability.config.ts`。内存模拟接口覆盖失败、慢请求与窄屏操作，不替代真实局域网媒体验证。 / In-memory fixtures cover failures, slow requests, and narrow screens; they do not replace real LAN media validation.

## Issue data contract / 问题数据契约

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
