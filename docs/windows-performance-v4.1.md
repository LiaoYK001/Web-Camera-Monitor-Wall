# v4.1 Windows 性能开发证据 / Windows performance development evidence

更新于 2026-10-30。本页记录开发试验，尚未完成用户暗夜精灵 13900HX/RTX4090 Laptop 的同机 OBS 对照，也不构成 v4.1 正式发布验收。

Development measurements only. These results establish neither stock OBS parity nor qualification of the user's laptop.

## 2026-10-30 原生监看与体积排查 / Native monitor and size investigation

用户反馈 `4.1.0-dev.14` 播放相同 H.265 时，FFmpeg/MediaMTX CPU 较高、WebOBS GPU 较高，整体超过 stock OBS 三倍。源码证实：浏览器不满足 HEVC 直通条件（例如已确认 B 帧、重排序未知或接收端不支持）时保留 H.264 兼容转换；此时服务端先解码/编码，网关转发 WebRTC，浏览器再解码/渲染。没有本机进程参数/逐路数据，不能断言用户每一路都命中了该分支。

The reported dev.14 HEVC workload exceeds stock OBS substantially. Code confirms that ineligible browser HEVC paths use H.264 compatibility conversion, adding server decode/encode, WebRTC relay and browser decode/render. User-specific per-stream routing remains unverified.

另发现 Windows OBS 来源硬解的全局就绪条件依赖外置 FFmpeg 的 NVENC/QSV 探测结果，而不是单独接受已经初始化的硬件 D3D11 设备。新的策略让实际硬件渲染设备也可启用 OBS 内部逐编码解码探测，避免外置编码探测失败时不必要地关闭来源硬解；显式关闭、软件回退与逐路实测边界保留。该问题是否发生在用户 dev.14 设备上仍需私有运行数据确认。

The Windows source-decode gate also unnecessarily depended on external encoder probes. A real initialized hardware D3D11 device now independently permits OBS's internal per-codec decoder probing, retaining explicit off/software fallback. This identifies a code-level cause of avoidable software decoding, not proof it occurred on the user's machine.

新增的 Windows 原生 Program 监看直接使用 libobs 解码/渲染，绕过本机观看的兼容视频转换、WebRTC 和浏览器解码。主窗口切换时释放其原播放器；已有独立观看端不随之关闭。当前作为显式试验入口，保留可回退的浏览器模式，使用与 OBS 相同的 NVIDIA/AMD 高性能提示。验收仍要求同机、同源、同分辨率/帧率/音频的可见窗口对照；不能用窗口绘制次数替代每路真实视频帧进度或硬解证据。详见 [Windows 运行边界](windows-desktop.md#v41-开发中的监看性能调整--monitoring-performance-in-v41-development)。

The explicit experimental native Program path bypasses those local video stages and releases the main browser players. Other viewers retain their work. Matching laptop/source/resolution/FPS/audio qualification remains required; draw callbacks alone do not prove per-stream media progress or hardware decode.

对现有 [dev.14 CI 附件](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41034181094) ZIP 中央目录的只读检查（按未压缩文件字节）得到：runtime/bin 451,074,384、OBS/CEF 352,434,045、Python 172,898,288、go2rtc UI 144,513,455、WebUI/模型 56,640,014；Electron 主程序另有 245,726,208 字节，尚有其他 Shell 运行库。压缩 NSIS 安装器为 454,131,546 字节，不与安装体积混用。外置 FFmpeg `avcodec-62.dll` 为 118,923,264 字节，OBS 自身使用另一套 `avcodec-61.dll`；二者 ABI 不同，不能简单删除/替换。

The original CI archive records large, independently required Electron, CEF, FFmpeg and Python runtimes. OBS and external FFmpeg use different codec DLL ABIs and cannot safely share arbitrary binaries. Installer download size and installed bytes are distinct measurements.

本机新生成的 go2rtc UI 为 27,228,928 字节，相对 dev.14 减少 117,284,527 字节；Windows 旧包中的未使用 `ffplay.exe` 为 18,800,128 字节，后续不再打包。两项预期合计约 136 MB，实际新安装体积以新候选 `*-footprint.json` 为准。这是文件载荷缩减，不是 CPU/GPU 性能提升率。

Local generated UI assets shrink by 117,284,527 bytes relative to dev.14; omitting unused ffplay removes another 18,800,128 bytes from the locked Windows payload. The new candidate footprint must confirm final installed size. These are payload savings, not a CPU/GPU improvement percentage.

首轮 [Windows dev.15 完整门禁](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41059000815)（`614a89b`）通过。真实 Win32/libobs 窗口读取五路 320×180/10fps、带 B 帧的合成 HEVC，来源健康与窗口绘制增长通过；未启动 Composite 发布或额外视频兼容路径，关闭/重开与 15 秒失去心跳回收通过。其 `*-footprint.json` 记录安装文件 1,458,546,999 字节、NSIS 427,196,203 字节；dev.14 ZIP 中央目录记录对应 1,594,695,173 / 454,131,546 字节，安装载荷减少 136,148,174 字节（约 8.54%）。它仍是完整的大型运行包，不能描述为接近 159 MB。

The first complete Windows dev.15 gate passed actual native-window/reordered-HEVC functional tests, normal packaging and isolated NSIS installation. Installed payload fell by approximately 8.54%; this does not measure CPU/GPU performance. The tiny synthetic streams do not qualify the user's 13900HX/RTX4090 Laptop sources.

dev.15 仅证明早期原生路径，未包含后续 OBS 硬解门控和安全依赖更新。早期 PR 审计因新通告[失败](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41060132083)，修复后的[公开 CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41062155214)已通过；最终运行候选使用新提交与独立身份，不能把早期附件追认为修复后的版本。

Dev.15 predates the later decode-gate and dependency fixes. The corrected public CI passes; its complete Windows candidate must retain its own identity and evidence rather than retroactively qualifying the earlier artifact.

最终 [Windows dev.17 完整构建](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/41062148722)（`4ca94a4`）已通过并保留开发附件，包含硬解门控修复和 Electron 44.9.1 / DOMPurify 3.4.17 等依赖更新。五路合成 HEVC 原生路径门禁再次通过；真实 desktop entry 额外调用 preload/IPC 原生入口，核对主进程 Cookie 认证和窗口状态/绘制后正常关闭。捆绑来源 UI 门禁、ASAR 的 clean-PATH/首登/Job 崩溃收束、隔离 Unicode 路径 NSIS 安装/卸载与数据保留也通过。没有发布稳定版本或更新生产 feed；13900HX/RTX4090 Laptop 的同机、同来源、同质量 OBS 对照仍未完成。

Final dev.17 (`4ca94a4`) passes the complete Windows build with the decode-gate/security fixes, repeated reordered-HEVC native-window checks and the actual desktop preload/IPC/cookie path. Source UI, packaged ASAR and isolated NSIS gates pass. The artifact is a development candidate, outside the stable feed. Actual same-source/quality OBS comparison on the user's laptop remains open.

## 播放中定位占用 / Inspect CPU during playback

监看页新增“实时占用”：保持播放器挂载，展开后每 5 秒读取本次桌面进程树，显示整体 CPU 及桌面/浏览器、FFmpeg、go2rtc、MediaMTX、核心等分项。整体及各项统一按逻辑处理器数量折算；首次读取或长时间中断后等待下一次采样，不把初始化零值计作真实负载。收起后停止读取，后台暂停、恢复后重新读取；单次读取最多 8 秒，旧响应不覆盖新状态。

The monitor's optional live CPU readout keeps the player mounted and samples the owned desktop process tree every five seconds. Total and per-role CPU use the same machine-normalized scale. The first reading or a long gap waits for the next sample. Collapsing stops reads, hidden pages pause, reads are bounded to eight seconds and stale results are discarded.

普通“系统状态”会离开当前监看页；只有独立投影等其他观看端仍在播放时，其读数才可能代表媒体负载。定位主窗口多路占用时使用监看页内的读数。容器/旧后端没有桌面进程树信息时，仅显示服务端单核百分比，不能代表 Windows/Android 观看端整体占用。即时读数用于定位大头，不能替代下文 15 分钟中位数/p95 对照。

The full settings/status page leaves the current Monitor view, so its numbers alone do not measure that wall's active load. Use the inline readout for the main monitor. Server-only diagnostics use an explicitly labeled per-core scale and cannot describe the watching Windows/Android device. Instantaneous readings help identify consumers; they do not replace the sustained median/p95 comparison below.

## 可见窗口长测（2026-10-14） / Visible-window sustained comparison

在同一 9950X3D/RTX3090 上，保持同一组持续运行的合成源：三路无 B 帧 H.264 1080p、两路有 B 帧 HEVC 1440p，25fps。实际 Electron 窗口可见，五路均完整处于视口；视频尺寸及每个画面的显示尺寸一致，画面整体纵向位置相差约 23px。两轮各预热 3 分钟，外部统计器每 5 秒采样、各保留 180 个样本（15 分钟）；观看端另在约 17 分钟内逐段验证非丢弃帧增长。

The same uninterrupted fixture supplied both runs. Actual Electron displayed all five videos inside the viewport at matching decoded and displayed sizes; vertical placement differed by about 23 pixels. Each run used three minutes of warm-up and 180 external CPU samples over fifteen minutes, with ongoing non-dropped-frame checks for approximately seventeen minutes.

| 项目 / Measurement | 旧开发候选 / Earlier candidate | 新开发候选 / New candidate |
| --- | --- | --- |
| 身份 / Identity | `4.0.1-dev.5` / `7001bae` | `4.1.0-dev.8` / `0468c02` |
| 整体 CPU 中位 / Median CPU | 13.02% | 8.62% |
| 整体 CPU p95 / p95 CPU | 15.58% | 10.31% |
| 每路平均呈现 / Presented FPS per stream | 24.95–24.96 | 24.82–24.87 |
| 每路丢弃帧 / Dropped frames per stream | 12–16 | 67–88 |
| Composite 发布 / Publisher | 持续发布 / publishing | 待机 / idle |
| 五路实际传输视频编码 / Negotiated video codecs | 5 × H.264 | 5 × H.264 |

CPU 中位下降约 33.8%，p95 同样下降约 33.8%；不是通过降低分辨率或关闭画面取得。新版呈现 FPS 略低、丢弃帧略多，不宣称无掉帧或满 25fps。两路 HEVC 在此组有 B 帧，仍走兼容 H.264 转换；这组数据不证明原生 HEVC 直通的性能。统计范围、PID 创建时间检查和排除上游生成器的规则沿用下文。单次顺序对照、合成无音频来源、当前主机/负载的限制仍然存在；旧基线是开发候选，不能改写成已发布 v4.0 或 stock OBS。

Median and p95 CPU decreased by approximately 33.8% at matching resolution and displayed size. The new run had slightly lower presented FPS and more dropped frames. Reordered HEVC still used H.264 conversion, so these measurements do not qualify native HEVC savings. This is one sequential synthetic, audio-free comparison on this host, against an earlier development candidate rather than published v4.0 or stock OBS.

## Windows 原生 HEVC 功能验证（2026-10-14） / Packaged Windows native HEVC check

另一次 dev.8 / `0468c02` 的可见 Electron 测试使用三路 H.264 1080p、两路 HEVC 1440p，全部无 B 帧、25fps、无音频。实际产品表单、批量建档、Studio/TAKE 和捆绑主页协商出 `3 × video/H264 + 2 × video/H265`，24 次进程采样中应用媒体 FFmpeg 均为零，Composite 保持待机。约 137 秒内各路平均呈现 24.66–24.76fps，存在丢帧。

A separate visible Electron run with the packaged dev.8 runtime negotiated three H.264 and two native H.265 streams. All sources were reorder-free, 25fps and audio-free. The actual import/Studio/TAKE workflow and bundled Monitor ran without application media FFmpeg in all 24 process samples, with Composite idle. Presented progress averaged 24.66–24.76fps per stream over approximately 137 seconds, with recorded drops.

这次仅验证直通功能，不是 CPU 对照；与上方长测相比 HEVC 的 B 帧条件不同，不能合并计算性能收益，也不替代用户摄像机或更长稳定性验收。

This establishes the passthrough path, not a CPU comparison. The HEVC reordering condition differs from the sustained comparison above; do not combine their results into a performance claim or physical-camera qualification.

## 同源短测 / Same-source short comparison

测试机为 Ryzen 9950X3D / RTX3090，32 个逻辑处理器。来源由应用进程树外的独立测试服务器提供：三路无 B 帧 H.264 1920×1080、两路 HEVC 2560×1440，全部 25fps、相同生成文件循环播放。通过实际表单、批量导入、Studio 保存、TAKE 和主页五个视频完成操作；两轮都要求每段采样的五路总帧计数增长，视频尺寸保持不变。总帧包含丢弃帧，不能据此证明可见画面持续呈现。

The test host used 32 logical processors. An independent fixture supplied three reorder-free H.264 1080p and two HEVC 1440p streams at 25fps from the same looping files. Both runs exercised actual device import, Studio and TAKE, with matching video dimensions and increasing total frame counters. Those counters include dropped frames and do not prove continuous visible presentation.

| 项目 / Measurement | 优化前开发候选 / Earlier candidate | v4.1 开发候选 / v4.1 candidate |
| --- | --- | --- |
| 身份 / Identity | `4.0.1-dev.5` / `7001bae` | `4.1.0-dev.4` / `5be2962` |
| 应用进程树 CPU 中位数 / Median CPU | 10.30% | 7.14% |
| 应用进程树 CPU p95 / p95 CPU | 12.86% | 8.39% |
| webobsd 分项中位数 / Backend median | 3.39% | 0.19% |
| Composite 发布 / Publisher | 持续发布 / publishing | 待机 / idle |
| 五路分辨率与帧增长 / Dimensions and frame progress | 通过 / passed | 通过 / passed |

整体 CPU 按 32 个逻辑处理器折算，中位数下降约 30.7%。统计器位于应用外部，以同一规则遍历实际 Electron 的子进程，并使用进程创建时间区分 PID 重用；排除生成源的服务器、FFmpeg 和统计器。每轮约 30 秒预热、24 个约 5 秒间隔的样本。逐项中位数不能相加代替整体中位数。

Normalized median CPU decreased by about 30.7%. The same external collector measured the owned Electron process tree in both runs, excluding fixture producers and itself. Each run had approximately 30 seconds of warm-up and 24 samples about five seconds apart. Medians of individual roles do not sum to the median of the total.

新版运行中仅有两路媒体 FFmpeg，实际参数确认 `-hwaccel cuda` / `-c:v h264_nvenc`，对应两路 HEVC 转换；三路兼容 H.264 直通。没有持续发布后台 Composite。这是本次试验观察，硬解能力状态本身不证明所有用户来源均已硬解。

The new run had two media FFmpeg processes, observed with CUDA decoding and NVENC encoding for the two HEVC streams; compatible H.264 stayed passthrough. Composite remained idle. This observation is specific to this run.

## 边界 / Limits

- 使用实际 Electron 的隐藏测试窗口，关闭后台节流；不是可见桌面窗口、物理摄像机或 stock OBS 对照。Actual Electron used a hidden window with background throttling disabled; this is not visible-window, physical-camera or OBS qualification.
- 2026-10-13 复核：该历史短测计数使用 `totalVideoFrames`，包含丢弃帧，原文“解码帧增长”不能作为实际呈现证明。后续来源门禁要求视频处于视口、`requestVideoFrameCallback` 与总帧减丢弃帧的增长；上方 2026-10-14 长测已采用这些更严格检查，历史短测的边界仍保留。Historical short-run total counters include dropped frames. The sustained comparison above uses viewport visibility, video frame callbacks and non-dropped frame progress; the earlier short run retains its original limitations.
- 旧候选只在批量建档阶段借用当前前端；主页播放使用旧候选自己的前端，新候选全程使用自身前端。The older candidate used the current frontend for batch setup only; playback used its own bundled frontend. The new candidate used its own frontend throughout.
- 优化前基线为历史开发候选，不是已发布 v4.0 安装包。仅一次短测；持续帧增长不等于逐路精确 FPS、掉帧和画质验收。The baseline is an earlier development candidate, not the published v4.0 installer. One short run and advancing frames do not qualify exact FPS, dropped frames or visual quality.
- 私密回执及测试运行目录保留在 Git 外。本页仅保留汇总，不包含摄像机地址、日志、口令或媒体文件。Private receipts remain outside Git; no camera URLs, logs, credentials or media are published here.
- 2026-10-30 低功耗暂停：启用低功耗后，隐藏窗口或完全移出视口的直接 RTSP 画面会关闭连接并在可见时重连，因此隐藏窗口读数不再等价于可见五路。与 OBS 对照时请保持主窗口可见、五路完整在视口内，并在两侧统一低功耗开关。Low-power suspension closes hidden/offscreen direct RTSP playback and reconnects on return, so hidden-window readings no longer represent five visible streams; keep the window visible with all five tiles in view and match the low-power switch on both sides for OBS comparisons.

正式性能目标仍按 [v4.1 发布草案](release-notes-v4.1.md) 的同机、同源、同质量长期对照完成。Further qualification must use the same user hardware, sources and quality settings for a sustained comparison.

## 可选占用栏加载隔离 / Optional readout loading isolation

新增受控模块延迟回归在修复前失败：占用栏尚未加载时，页面级 Suspense 会隐藏整个 Monitor。现在仅占用栏自身使用加载边界，保留同高禁用按钮；监看立即可用，模块完成后播放器 DOM 不变。typecheck/build 和完整相关 15 项回归通过；新完整候选仍需运行实际媒体门禁。A controlled module-delay regression failed before the fix. A local loading boundary now keeps Monitor and its player mounted while the optional module loads; fifteen related browser checks passed. Complete candidate qualification remains required.


## Windows 单端后续诊断（2026-10-20） / Windows-only follow-up diagnostics

按用户决定暂停 Android/Docker 同步交付，本轮继续使用已核验的原始 Windows `4.1.0-dev.13` / `1728381`，无前端替换。可见 Electron 1280×900 窗口同时播放三路 1920×1080 H264、两路 2560×1440 HEVC，均为 25fps、无 B 帧、无音频的合成源；编码目标每路 4Mbps，预先生成的 20 秒媒体由应用进程树外的 loopback RTSP 服务循环发送。实际文件 FFprobe 确认 codec/尺寸/25fps/BF0；H264 SHA-256 `f7b1648672abf3b9c582e0713d9b91ff3a7163b204941d3cb721e0293ba573a1`，HEVC `2090c44169654fed7f66bb095460eb18b6b70f2e49e2760666525a1eed5adb6f`。保留实际视口断言，完整五路尺寸不变。

这是短时诊断：画面就绪后预热 30 秒，外部进程树 CPU 收集 24 次、约 5 秒间隔；按本机 32 个逻辑处理器折算，中位 **6.06%**、p95 **7.28%**。同轮媒体窗口 138.145 秒，五路各 3453 个非丢弃帧，均约 **25.00fps**、本轮丢弃计数增量为零。实际接收 codec 为三路 H264、两路 H265；24 次应用状态中媒体 FFmpeg 实例均为零，Composite 均为 idle。解码实现/省电标记未在本轮 WebRTC 统计中出现，不能只凭全局 `video_decode: enabled` 宣称每路硬解。

The original bundled dev.13 passed this short visible five-source BF0/no-audio diagnostic: normalized median/p95 CPU 6.06%/7.28%, with 3,453 non-dropped frames per stream over 138.145 seconds (about 25fps), no observed dropped-frame increment, native 3×H264/2×H265, zero application media FFmpeg in 24 samples and idle Composite. Per-stream decoder implementation/power-efficiency fields were unavailable; global decode capability is not per-stream hardware proof.

**不把 6.06% 与此前 8.62% 直接计算版本降幅**：此前长测包含有 B 帧的 HEVC 兼容转换，本轮来源条件不同；本轮仅为 2 分钟级短测，不替代 15 分钟或暗夜精灵/实际摄像机/OBS 对照。独立的带采样器诊断进一步区分 Electron browser/renderer/GPU/utility 与 go2rtc/MediaMTX；该轮存在 profiler 开销，不作为第二份无干扰性能基准，也不把各角色中位数相加作为总占用。

Do not compare 6.06% directly with the earlier 8.62% as a version improvement: the earlier run converted reordered HEVC, and the source conditions differ. This short run does not replace sustained, Omen, real-camera or OBS qualification. A separate instrumented role/renderer profile has profiling overhead and is diagnostic only; role medians do not sum to the overall median.

本机已准备签名有效的 OBS Studio 32.1.0 便携副本及独立配置，WebSocket 与自动更新关闭、源仅连接自建 loopback RTSP，没有读取或修改用户现有 OBS 配置。首次启动使用隐藏窗口，测试可见性断言按预期拒绝，该失败保留并排除，未计作 OBS 性能通过；进程已结束。显示独立对照窗口的明确授权尚待用户回复；不以隐藏窗口代替可见预览对照。

A validly signed installed OBS 32.1.0 binary was copied into an isolated portable reference, with WebSocket/updates disabled and owned loopback sources. Its initial hidden launch was rejected by the visibility guard and retained/excluded, without changing existing OBS data. The owned process exited; visible-window permission remains pending, and no OBS parity is claimed.
