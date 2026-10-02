# MonitorView and analytics runtime / MonitorView 与分析运行时

## Studio layers and projector / Studio 层级与投影

Scenes 支持最多 64 个独立预设。点击“新建场景”选择已建档设备或已有来源，可创建四路、六路等不同集合；新建时自动生成网格，后续位置、裁剪、缩放、声音及画布尺寸属于各场景自己的 Scene 文档。右键场景、点击省略号、按 Shift+F10 或 F2 可打开管理操作：复制、重命名、选择来源、画布属性、排列、锁定/解锁、排序和删除。删除只移除场景，不删除设备；Program 场景和被嵌套引用的场景须先解除使用。修改后点击“保存 Studio”。

右键已保存场景 → “打开场景投影 · 新窗口”使用 `#projector?scene=<id>`。每个场景使用独立窗口名，因此可同时投影多个场景，重复打开同一场景会复用窗口。窗口固定到场景 ID，保持保存的画布、来源位置与缩放，不跟随 Program/Preview 切换或全局自动布局；保存后的更新通过场景事件与每 5 秒读取刷新，场景被删除时显示明确状态。普通 `#projector` 仍跟随 Program。独立投影默认静音，双击全屏，Esc 关闭。浏览器需允许本站弹出窗口。

### Automatic playback optimization / 自动播放优化

“系统设置 → 弱网与慢速流自动优化”默认开启，账号中缺少新字段时也采用开启值。总开关、慢速流容错、低带宽 Profile 选择、缓冲与实时追赶均可独立选择，立即按账号保存。关闭总开关会恢复所选 Profile 和原有连接恢复行为。该策略调整浏览器播放，不更改摄像机或 Studio 配置，也不为优化自动创建转码服务。

WHEP/WebRTC 根据最近 16 个实际帧间隔调整卡顿判定，等待上限 90 秒，并延长首次帧等待；固定低帧率本身不触发低带宽 Profile 切换。每 3 秒观察视频丢包、抖动和冻结，连续三次恶化才请求更低成本且已启用的 Profile，切换后至少等待 60 秒，持续稳定后恢复原 Profile。保留音频能力，排除 Snapshot、停用和无有效媒体尺寸的候选；显式低功耗 Profile 优先。没有子码流时保留当前来源，不能凭空增加网络带宽。支持 `jitterBufferTarget` 的浏览器可在 120–800 ms 范围调整缓冲；不支持的浏览器继续使用自身控制。

HLS 提供有界缓冲、已有多码率的 ABR、自适应实时追赶以及致命网络错误的退避恢复；401/403 不自动反复重试。实际设备的网络、编码和码率仍需现场验证，自动化测试使用模拟流与协议状态。

Studio 的来源列表按从上到下的画面层级排列；拖动来源或按 `Alt+↑/↓` 可改层级，属性栏的“上移一层 / 下移一层”执行同一操作。修改属于草稿，点击保存 Studio 后生效。OBS 面板菜单中的来源和属性侧栏可以显示、隐藏、调整左右位置及宽度；画布固定在二者之间。

监看设置里的“统计叠层（全部来源）”及位置、文字框和透明度控件会更新已配置电平表的来源；逐路设置仍可随后单独修改。投影默认采用“完整画面”，包含统计、电平表、超阈值边框及检测框；“投影内容”可选“仅画面”。独立投影窗口读取同一账号的监控偏好。浏览器若阻止独立窗口的自动音频分析，可点击“启用电平检测（静音）”。服务端 Composite Program 是单路合成媒体，浏览器逐源叠层只在 Direct 投影中呈现。

The Studio source list is ordered from front to back. Drag a source or press `Alt+Up/Down` to change its layer; the property panel uses the same operation. Save Studio to commit the draft. The OBS panel menu controls the real source and property sidebars; the canvas stays between them. Global telemetry controls update existing source decorations, including sources with meters. Direct projectors default to the complete picture and can be switched to picture-only output. If browser autoplay blocks meter analysis in a detached window, use the silent meter-enable button. Browser per-source decorations are not part of the server Composite Program feed.

> Status / 状态：v2-M5 is complete and published in stable v2.1 / v2-M5 已完成并随稳定版 v2.1 发布。

## View contract / 视图契约

监看音频偏好自动保存到当前账号：总监听开关、扬声器/仅电平表输出、主音量、逐来源音量/静音/监听和调音台收起状态。刷新、重开浏览器或在另一浏览器登录同一账号后会恢复；已打开的页面在重新获得焦点或每 5 秒读取账号的最新偏好。保存失败会提示并保留加密的本地待同步副本，恢复连接后重试；关闭页面前使用 keepalive 请求提交最新设置。浏览器自动播放许可单独判定，被阻止时保留监听开启的设置，并提示点击恢复。独立投影默认静音，不会自动复制主窗口的扬声器输出。音频工作台的 Scene/音轨配置仍通过“保存音频配置”提交到 Studio。


`MonitorView v1` stores only view-generation rules: auto/manual mode, M source identities, telemetry appearance, rotation, promotion and low-power preferences. Auto layout accepts 1–16 visible items and emits ordinary Scene v5 `x/y/width/height` values. It does not create a second canvas format. Moving a tile in Studio remains a Scene edit; the operator may switch MonitorView to manual mode or regenerate the automatic layout.

`MonitorView v1` 只保存视图生成规则：自动/手工模式、M 来源身份、统计外观、轮换、事件提升和低功耗偏好。自动布局接受 1–16 个可见项并输出普通 Scene v5 `x/y/width/height`；它不创建第二种画布格式。在 Studio 移动画面仍属于 Scene 编辑；值守员可切到手工模式或重新生成自动布局。

Telemetry defaults to off. When enabled it defaults to bottom-left, 90% text opacity, a black 45% background and a one-second refresh. WHEP/Gateway uses WebRTC inbound stats; HLS combines rendered frames and hls.js fragment bytes; MJPEG reports unavailable FPS/rate when the browser cannot observe them. Decoder classification is only `HW`, `SW`, or `Unknown`, with a bounded implementation string when the browser exposes one. Measurements remain in component memory and are never written to Scene, IndexedDB, synchronization, logs or Program recordings.

统计默认关闭；启用后默认位于左下角，文字透明度 90%，黑色背景透明度 45%，每秒刷新。WHEP/Gateway 使用 WebRTC inbound stats；HLS 组合视频渲染帧与 hls.js 分片字节；浏览器无法观测 MJPEG 时，FPS/速率明确显示不可用。解码分类只有 `HW`、`SW`、`Unknown`，浏览器提供实现名称时仅展示有长度上限的文本。测量值只驻留组件内存，不写入 Scene、IndexedDB、同步、日志或 Program 录像。

Rotation pauses while the document is hidden, offline or in manual/edit mode. Random rotation is a shuffle bag, so an item does not repeat during one bag. A `webobs:detection-signal` browser event accepts a validated `DetectionSignal`; promotion additionally requires the MonitorView switch and the matching Camera/Profile policy, then applies threshold, hold and cooldown. Native camera events may continue in low-power mode. Browser/server software signals are ignored in low-power mode unless the profile explicitly sets `forceAnalyticsAlwaysOn`.

页面隐藏、离线或进入手工/编辑模式时轮换暂停。随机轮换使用 shuffle bag，因此同一轮内不重复。浏览器事件 `webobs:detection-signal` 接受已验证的 `DetectionSignal`；提升还要求 MonitorView 总开关与对应 Camera/Profile 策略同时允许，并执行阈值、保持及冷却。摄像机原生事件在低功耗模式下仍可工作；浏览器/服务端软件信号会被忽略，除非该 Profile 显式设置 `forceAnalyticsAlwaysOn`。

## Low-power boundary / 低功耗边界

The default target is 2 FPS, with 0.5/1/2/5 shortcuts and a validated 0.5–30 range. The selector first chooses an available profile at or below the target, minimizing decoded pixel-rate; otherwise it keeps the lowest-FPS/lowest-cost profile and displays `Target unmet: no low-frame-rate profile`. It never requests a Docker transcode merely to meet the target. While low-power mode is active, Page Visibility and Intersection Observer state release offscreen browser media connections and reconnect them only after they become visible. Measured zero-new-server-session acceptance remains release-gate work.

默认目标为 2 FPS，快捷值为 0.5/1/2/5，验证范围为 0.5–30。选择器优先在不高于目标的 Profile 中最小化解码像素率；若不存在，则保留最低 FPS/最低成本 Profile，并显示 `Target unmet: no low-frame-rate profile`。它不会仅为达到目标而请求 Docker 转码。低功耗开启时，页面可见性和 Intersection Observer 会释放离屏浏览器媒体连接，仅在恢复可见后重连。“服务端零新增会话”的实测仍属于发布门禁工作。

Deterministic browser tests cover every 1–16 landscape/portrait M/S combination, larger M area, stable re-layout, pinned sequential/random windows, unavailable MJPEG telemetry, WebRTC byte/frame/codec/decoder deltas, low-power visibility decisions and promotion threshold/cooldown behavior / 确定性浏览器测试覆盖 1–16 路横竖屏全部 M/S 组合、M 面积更大、稳定重排、固定顺序/随机窗口、MJPEG 不可测统计、WebRTC 字节/帧/编码/解码器差分、低功耗可见性决策及事件提升阈值/冷却行为。

## Wall quick controls / 监控墙快捷控制

### Account preference saving / 账号偏好保存

当前开发版按账号保存监控偏好。打开监控页只读取配置；调整后约 250 毫秒合并保存，连续写入按顺序执行。切换到其他页面或隐藏浏览器时，会提交尚未发送的调整；退出账号时取消待写入操作。保存当前场景的设置会保留其他场景的逐源电平表与统计外观配置。独立来源预览不写回监控偏好。网络故障时仍保留加密本机副本，以界面同步状态为准；浏览器被强制关闭时无法保证尚未完成的请求送达。

The current development version stores monitor preferences per account. Opening the monitor only reads preferences; edits are combined after about 250 ms and written in order. Navigating to another page or hiding the browser submits pending edits; clearing the account cancels pending writes. Saving the current scene preserves per-source meter and telemetry decorations from other scenes. Independent source previews do not write monitor preferences. Network failures retain an encrypted local copy; check the sync indicator. Forced browser termination cannot guarantee delivery of unfinished requests.

The large-picture switch takes effect immediately: enabling it raises `largeCount` to at least one, checking an `M` row promotes that source, and the small/large ratio slider (10%–90%, default 50%) drives the auto layout so a small tile is the chosen share of a large tile while the canvas stays filled. The layout is a deterministic skyline packing over ordinary Scene v5 rectangles, so re-applying it is a stable fixed point.

大画面开关即时生效：勾选后 `largeCount` 至少为 1，勾选 `M` 行即提升该来源；小/大画面比例滑块（10%–90%，默认 50%）驱动自动布局，在尽量填满画布的前提下让小画面为大画面的指定比例。布局是对普通 Scene v5 矩形的确定性 skyline 装箱，因此重复应用是稳定不动点。

The per-source audio meter follows OBS: a vertical rail on the left edge by default, with direction (vertical/horizontal), corner or custom position, size and opacity, a dBFS threshold and an alert border. Sources whose profile or live stream carries no audio track show `该源没有音频轨道` instead of meter options. After enabling sound the operator picks `扬声器 + 电平表` or `仅电平表 / 阈值`; the latter mutes the speaker gain while keeping every analyser alive for meters and threshold promotion.

逐源电平表遵循 OBS 习惯：默认在左侧竖放，可切换横/竖、四角或自定义位置、大小与透明度，并可设置 dBFS 阈值与超阈值边框。Profile 或实时流没有音频轨道的来源显示“该源没有音频轨道”，不再展示电平表选项。开启声音后可选择“扬声器 + 电平表”或“仅电平表 / 阈值”，后者把扬声器增益静音，同时保留全部分析器用于电平和阈值提升。

True fullscreen and the resizable window preview keep only the picture, telemetry overlay, level meter, detection boxes and audio alerts; tile states, status buttons, names, sliders and the audio/control bars are hidden. The Studio add-source form accepts multiple Camera Registry profiles at once with checkboxes and appends every selection in one Scene update.

真全屏与可缩放的窗口预览只保留画面、统计叠层、电平表、检测框和声音告警；画面状态、状态按钮、名称、滑块及音频/控制条一律隐藏。Studio 添加来源表单可用复选框一次选择多个 Camera Registry Profile，并在同一次 Scene 更新中批量添加。

## Analytics versions / 分析版本

- `v3-M1 / v3.0`: per Camera/Profile motion and scene-change switches, native ONVIF events first, then a downsampled browser Worker where same-origin/CORS pixel access permits. Cross-origin MJPEG that cannot be safely sampled remains unsupported and must not trigger a hidden server media path. The implementation is tracked on `dev`; release requires revision-bound v3-M1 receipts.
- `v3-M2 / v3.1`: opt-in browser WebGPU/WASM person boxes and optional administrator-enabled server providers. Only the `person` class and normalized boxes are in scope; face identity, emotion inference and biometric databases are excluded. The pinned ONNX model is served as a same-origin, hash-verified asset; the first-party Worker fails closed when its optional runtime is unavailable.

- `v3-M1 / v3.0`：逐 Camera/Profile 运动与大范围画面变化开关，优先使用 ONVIF 原生事件；同源/CORS 像素访问允许时再使用浏览器降采样 Worker。不能安全采样的跨源 MJPEG 明确标记不支持，不能偷偷启动服务器媒体链。
- `v3-M2 / v3.1`：选择加入的浏览器 WebGPU/WASM 人物框，以及管理员显式启用的可选服务端 Provider。范围只包含 `person` 类别和归一化框；不包含人脸身份、情绪推断或生物特征数据库。固定 ONNX 模型以同源、哈希校验资源提供；第一方 Worker 缺少可选运行时则安全失败。

Camera Registry stores all three switches independently and defaults them off. Batch updates are one SQLite transaction, validate every Camera/Profile before writing, and are bounded to 256 records. `scene-change` is an additive event type; the existing v1 event schema remains compatible. Raw frames, model inputs, snapshots, endpoints and live telemetry remain outside logs and public evidence.

Camera Registry 独立保存三类开关且默认全部关闭。批量更新在一个 SQLite 事务中完成，写入前验证所有 Camera/Profile，单批上限 256。`scene-change` 是新增事件类型，现有 v1 事件 schema 保持兼容。原始帧、模型输入、截图、端点及实时统计不得进入日志或公开证据。
