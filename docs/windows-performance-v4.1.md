# v4.1 Windows 性能开发证据 / Windows performance development evidence

更新于 2026-10-19。本页记录开发试验，尚未完成用户暗夜精灵 13900HX/RTX4090 Laptop 的同机 OBS 对照，也不构成 v4.1 正式发布验收。

Development measurements only. These results establish neither stock OBS parity nor qualification of the user's laptop.

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

正式性能目标仍按 [v4.1 发布草案](release-notes-v4.1.md) 的同机、同源、同质量长期对照完成。Further qualification must use the same user hardware, sources and quality settings for a sustained comparison.
