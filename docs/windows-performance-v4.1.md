# v4.1 Windows 性能开发证据 / Windows performance development evidence

2026-10-09。本页记录开发试验，尚未完成用户暗夜精灵 13900HX/RTX4090 Laptop 的同机 OBS 对照，也不构成 v4.1 正式发布验收。

Development measurements only. These results establish neither stock OBS parity nor qualification of the user's laptop.

## 同源短测 / Same-source short comparison

测试机为 Ryzen 9950X3D / RTX3090，32 个逻辑处理器。来源由应用进程树外的独立测试服务器提供：三路无 B 帧 H.264 1920×1080、两路 HEVC 2560×1440，全部 25fps、相同生成文件循环播放。通过实际表单、批量导入、Studio 保存、TAKE 和主页五个视频完成操作；两轮都要求每段采样的五路解码帧增长，视频尺寸保持不变。

The test host used 32 logical processors. An independent fixture supplied three reorder-free H.264 1080p and two HEVC 1440p streams at 25fps from the same looping files. Both runs exercised actual device import, Studio, TAKE and five decoded monitor videos with matching dimensions and ongoing frame progress.

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
- 旧候选只在批量建档阶段借用当前前端；主页播放使用旧候选自己的前端，新候选全程使用自身前端。The older candidate used the current frontend for batch setup only; playback used its own bundled frontend. The new candidate used its own frontend throughout.
- 优化前基线为历史开发候选，不是已发布 v4.0 安装包。仅一次短测；持续帧增长不等于逐路精确 FPS、掉帧和画质验收。The baseline is an earlier development candidate, not the published v4.0 installer. One short run and advancing frames do not qualify exact FPS, dropped frames or visual quality.
- 私密回执及测试运行目录保留在 Git 外。本页仅保留汇总，不包含摄像机地址、日志、口令或媒体文件。Private receipts remain outside Git; no camera URLs, logs, credentials or media are published here.

正式性能目标仍按 [v4.1 发布草案](release-notes-v4.1.md) 的同机、同源、同质量长期对照完成。Further qualification must use the same user hardware, sources and quality settings for a sustained comparison.
