# MonitorView v1 and analytics handoff / MonitorView v1 与分析交接

> Status / 状态：v2-M5 functional slice on `dev`; complete release qualification is still required / `dev` 已落地 v2-M5 功能切片，仍需完整发布资格验证。

## View contract / 视图契约

`MonitorView v1` stores only view-generation rules: auto/manual mode, M source identities, telemetry appearance, rotation, promotion and low-power preferences. Auto layout accepts 1–16 visible items and emits ordinary Scene v5 `x/y/width/height` values. It does not create a second canvas format. Moving a tile in Studio remains a Scene edit; the operator may switch MonitorView to manual mode or regenerate the automatic layout.

`MonitorView v1` 只保存视图生成规则：自动/手工模式、M 来源身份、统计外观、轮换、事件提升和低功耗偏好。自动布局接受 1–16 个可见项并输出普通 Scene v5 `x/y/width/height`；它不创建第二种画布格式。在 Studio 移动画面仍属于 Scene 编辑；值守员可切到手工模式或重新生成自动布局。

Telemetry defaults to off. When enabled it defaults to bottom-left, 90% text opacity, a black 45% background and a one-second refresh. WHEP/Gateway uses WebRTC inbound stats; HLS combines rendered frames and hls.js fragment bytes; MJPEG reports unavailable FPS/rate when the browser cannot observe them. Decoder classification is only `HW`, `SW`, or `Unknown`, with a bounded implementation string when the browser exposes one. Measurements remain in component memory and are never written to Scene, IndexedDB, synchronization, logs or Program recordings.

统计默认关闭；启用后默认位于左下角，文字透明度 90%，黑色背景透明度 45%，每秒刷新。WHEP/Gateway 使用 WebRTC inbound stats；HLS 组合视频渲染帧与 hls.js 分片字节；浏览器无法观测 MJPEG 时，FPS/速率明确显示不可用。解码分类只有 `HW`、`SW`、`Unknown`，浏览器提供实现名称时仅展示有长度上限的文本。测量值只驻留组件内存，不写入 Scene、IndexedDB、同步、日志或 Program 录像。

Rotation pauses while the document is hidden, offline or in manual/edit mode. Random rotation is a shuffle bag, so an item does not repeat during one bag. A `webobs:detection-signal` browser event accepts a validated `DetectionSignal`; promotion additionally requires the MonitorView switch and the matching Camera/Profile policy, then applies threshold, hold and cooldown. Native camera events may continue in low-power mode. Browser/server software signals are ignored in low-power mode unless the profile explicitly sets `forceAnalyticsAlwaysOn`.

页面隐藏、离线或进入手工/编辑模式时轮换暂停。随机轮换使用 shuffle bag，因此同一轮内不重复。浏览器事件 `webobs:detection-signal` 接受已验证的 `DetectionSignal`；提升还要求 MonitorView 总开关与对应 Camera/Profile 策略同时允许，并执行阈值、保持及冷却。摄像机原生事件在低功耗模式下仍可工作；浏览器/服务端软件信号会被忽略，除非该 Profile 显式设置 `forceAnalyticsAlwaysOn`。

## Low-power boundary / 低功耗边界

The default target is 2 FPS, with 0.5/1/2/5 shortcuts and a validated 0.5–30 range. The selector first chooses an available profile at or below the target, minimizing decoded pixel-rate; otherwise it keeps the lowest-FPS/lowest-cost profile and displays `Target unmet: no low-frame-rate profile`. It never starts a Docker transcoder just to meet the target. Hidden-tile pipeline suspension and measured zero-new-server-session acceptance remain release-gate work.

默认目标为 2 FPS，快捷值为 0.5/1/2/5，验证范围为 0.5–30。选择器优先在不高于目标的 Profile 中最小化解码像素率；若不存在，则保留最低 FPS/最低成本 Profile，并显示 `Target unmet: no low-frame-rate profile`。它不会仅为达到目标而启动 Docker 转码。隐藏画面管线暂停及“服务端零新增会话”的实测仍属于发布门禁工作。

## Analytics versions / 分析版本

- `v3-M1 / v3.0`: per Camera/Profile motion and scene-change switches, native ONVIF events first, then a downsampled browser Worker where same-origin/CORS pixel access permits. Cross-origin MJPEG that cannot be safely sampled remains unsupported and must not trigger a hidden server media path.
- `v3-M2 / v3.1`: opt-in browser WebGPU/WASM person boxes and optional administrator-enabled server providers. Only the `person` class and normalized boxes are in scope; face identity, emotion inference and biometric databases are excluded.

- `v3-M1 / v3.0`：逐 Camera/Profile 运动与大范围画面变化开关，优先使用 ONVIF 原生事件；同源/CORS 像素访问允许时再使用浏览器降采样 Worker。不能安全采样的跨源 MJPEG 明确标记不支持，不能偷偷启动服务器媒体链。
- `v3-M2 / v3.1`：选择加入的浏览器 WebGPU/WASM 人物框，以及管理员显式启用的可选服务端 Provider。范围只包含 `person` 类别和归一化框；不包含人脸身份、情绪推断或生物特征数据库。

Camera Registry stores all three switches independently and defaults them off. Batch updates are one SQLite transaction, validate every Camera/Profile before writing, and are bounded to 256 records. `scene-change` is an additive event type; the existing v1 event schema remains compatible. Raw frames, model inputs, snapshots, endpoints and live telemetry remain outside logs and public evidence.

Camera Registry 独立保存三类开关且默认全部关闭。批量更新在一个 SQLite 事务中完成，写入前验证所有 Camera/Profile，单批上限 256。`scene-change` 是新增事件类型，现有 v1 事件 schema 保持兼容。原始帧、模型输入、截图、端点及实时统计不得进入日志或公开证据。
