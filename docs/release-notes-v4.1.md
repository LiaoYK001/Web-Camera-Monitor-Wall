# v4.1 发布说明（开发草案） / v4.1 release notes (development draft)

尚未发布 v4.1；v4.0 已发布安装包不包含本页的新调整。后续正式身份为 `v4.1` / `4.1.0`；当前仅准备开发候选。主交付端仍为 Windows x64、容器及独立 Android。

v4.1 has not been released. Existing v4.0 assets do not contain these changes. The intended stable identity is `v4.1` / `4.1.0`; only development candidates are being prepared.

## 本轮变更 / Changes

- Windows Direct 监看按需启停后台 Composite 发布，闲置 OBS 网络/媒体来源停止解码；录制保持连续。Windows uses on-demand Composite publishing and releases inactive OBS media decoding while recording remains continuous.
- NVIDIA Hybrid 增加 CUDA 解码及保留 NVENC 的分级回退，OBS 来源启用上游硬解探测策略。Hybrid adds CUDA decoding with staged NVENC/software fallback; OBS sources use upstream hardware probing.
- 系统状态统计本次应用进程树，区分 go2rtc、浏览器、FFmpeg 与后台服务，并提供整体 CPU 折算。Diagnostics show the owned desktop process tree and normalized CPU.
- go2rtc 命名流支持批量选择、逐项导入、部分失败重试、停止及不确定写入核对。Named streams support safe batch import, progress, partial retries, stopping and reconciliation.
- 网站回放自动检查 H.264 帧重排序兼容性，按需处理 B 帧；增加主页持续解码验收。Website VOD checks H.264 frame reordering and adds monitor-wall soak validation.
- 内部 go2rtc 冷启动使用固定 90 秒来源/启动探测预算与 95 秒 Hybrid 发布预算，修复下游 8/10 秒提前终止网站解析；实际媒体读取仍为 8 秒，单次信令与普通摄像机预算不变。Internal go2rtc startup aligns with the fixed extractor budget, preserving steady-state media reads, individual signaling and ordinary camera deadlines.
- 设备轨道探测复用同一次 FFprobe 记录 B 帧，已确认需要重排序的 H.264 自动进入 Hybrid；无 B 帧来源继续直通。旧设备需重新探测轨道；直接写入旧式 RTSP 场景的来源仍不具备此登记信息。Registry track probes persist B-frame metadata without an additional media read; known reordered H.264 uses Hybrid. Existing devices need a fresh track probe; legacy raw RTSP scene sources do not have this registry metadata.
- Direct 根据实际接收端 SDP 协商 H.265：设备已探测为无 B 帧且接收端声明支持时，视频不经过服务器解码/编码；不兼容音频可单独转换。旧接收端、有 B 帧、未知结果和显式 Hybrid 保留 H.264 兼容路径；不同接收端可同时观看。实际画面未出现时，前端可退回兼容编码。Direct negotiates native HEVC only for a receiver offering it and a registry probe confirming zero B frames; incompatible audio can convert independently. Older/unknown/reordered/explicit-Hybrid cases retain compatibility conversion, including concurrent viewers and frontend fallback.
- 轨道探测改为有界异步任务，解决网站冷启动超过 HTTP 代理等待上限；已添加流提供“重新探测轨道”，失败保留原设备。探测期间修改来源不会被旧结果覆盖，缓存完成结果返回当前状态。Bounded asynchronous probes survive website startup without holding the proxy request; imported streams can retry in place, and stale probes cannot overwrite edited sources.
- 同时包含此前 dev 中的配置 Save/reload、RTSP 自动识别和实际主页播放/重启验收修复。Includes prior dev configuration reload, RTSP detection and actual playback/restart fixes.

## 已有证据 / Available evidence

- 前端 typecheck/build；相关浏览器回归 24 项通过。Frontend typecheck/build and 24 focused browser checks passed.
- Desktop 单元 48 项通过；原生 Python 17 项中 9 项通过、8 项因本机对应运行时位置未构建而跳过；POSIX 转码回归 10 项通过。Desktop unit checks passed; local Python checks distinguish nine passes from eight runtime-dependent skips; ten POSIX transcoder checks passed.
- Windows `4.1.0-dev.6`（`ca68ff5`）[完整 CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/38366721760) 与[公开源码 CI](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/38366720283) 通过，包括原生运行时、Composite 浏览器按需/故障恢复、打包启动和 NSIS。它包含独立冷启动预算，尚不包含本轮异步轨道探测与接收端 H.265 调整。2026-10-13 最新源码设备服务 Windows 全量 56 项、聚焦浏览器 14 项及 Linux CTest 2 项通过。Dev.6 passed complete Windows/public CI; the latest asynchronous probes and receiver-specific HEVC still require a new Windows candidate. Current source passed 56 Windows registry, 14 focused browser and two Linux CTest checks.
- Linux/WSL 编译、CTest 2 项通过；实际 OBS→WHIP→MediaMTX→RTSP 解码验证待机、观看超过保温期、关闭后停止、强制踢出发布连接后恢复与健康状态。网站助手另通过 MP4/HLS 实际解码、重复连接及首次 HTTP 请求中断恢复。Linux/WSL compilation and two CTest cases passed; real transport exercised demand lifecycle and publisher fault recovery. The website helper passed MP4/HLS decoding, reconnect and initial HTTP disconnect recovery. These are separate from complete Windows candidate qualification.
- 2560×1440/25fps 合成 HEVC → NVENC 的单路 20 秒试验：软件解码 3.375 CPU 秒、CUDA 解码 3.312 CPU 秒（本机 9950X3D/RTX3090）。样本差异很小，不能据此宣称显著优化，更不是暗夜精灵或 OBS 对照。A short synthetic decode sample showed little CPU difference and establishes neither significant savings nor stock OBS parity.
- 同五路合成源、实际 Electron 隐藏窗口短测：优化前开发候选整体 CPU 中位 10.30%、p95 12.86%；`4.1.0-dev.4` 为 7.14% / 8.39%，中位约下降 30.7%，webobsd 分项中位由 3.39% 降至 0.19%。五路总帧计数增长、视频尺寸一致；总数包含丢弃帧，不能证明可见画面持续呈现。仅一次短测，不代表可见窗口、准确 FPS 或 OBS 达标。[方法与边界](windows-performance-v4.1.md)。A short hidden-window synthetic comparison reduced normalized median CPU by about 30.7%; total frame counters do not prove visible presentation.
- 用户指定的 YouTube 已转为回放：旧候选自动直通复现无画面，显式 H.264 转换通过主页十分钟及整应用重启恢复；`4.1.0-dev.2` 自动策略首次 MSE 启动失败，复跑通过主页 600 秒、117 次帧增长采样，但整应用重启后播放失败。日志确认下游 8/10 秒早于提取冷启动完成；不能将十分钟播放成功计为完整通过。The reported replay passed a ten-minute automatic monitor soak on dev.2 after an initial MSE failure, but failed playback after full restart. Logs exposed the shorter downstream startup deadlines; full qualification remains failed.
- 冷启动修复经 Linux 实际 go2rtc→Hybrid→浏览器验证：人为延迟 18 秒的 H.264/AAC 源在 25 秒出画面并持续解码，正常关闭后生产者与转码停止。此合成故障验证不替代 Windows YouTube 的完整复验。With the startup fix, an actual synthetic go2rtc source delayed by 18 seconds decoded through Hybrid in a browser within 25 seconds and stopped after viewer shutdown; Windows external-site requalification remains required.
- `dev.6` 使用自身捆绑前端，重新完成指定 YouTube 回放的冷导入、实际轨道探测、MSE、Studio/TAKE、主页可见呈现 600 秒和整应用重启恢复。117 次采样，总帧 17,134、丢弃 573、非丢弃帧 16,561，平均约 27.6fps；不宣称无掉帧或稳定满 30fps。门禁额外要求 `requestVideoFrameCallback`，测试确保画面位于视口中。The exact reported replay passed dev.6's own frontend through cold import, visible 600-second presentation and full restart, with 16,561 non-dropped frames (27.6fps average), not a zero-drop/full-30fps claim.
- 2026-10-13，最新 Linux 核心/真实 go2rtc、MediaMTX 与 Windows Electron 实际协商验证：无 B 帧 HEVC 接收端得到 `video/H265`，兼容接收端得到 `video/H264`；AAC、有 B 帧、未知重排序四种合成场景通过。关闭兼容端不打断另一端，全部关闭后媒体停止。首次网关配置应用期间出现过 502，探针按有界信令重试后通过；不是 Windows 捆绑核心或物理摄像机验收。Real Windows Electron with the latest Linux core/gateway exercised HEVC/H264 coexistence, AAC, reordered/unknown metadata and shutdown. A transient initial configuration 502 required bounded retry; these fixtures do not qualify the packaged Windows core or physical cameras.
- 2026-10-14 核对：`4.1.0-dev.7` / `e8b2368` 的[完整 Windows 构建](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/38383713329)成功，已包含接收端 HEVC 与异步任务；仍需加入最新表单外层等待修复。`dea715f` 的[完整容器预检](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/38384713598)成功，包含完整镜像、认证 go2rtc HTTP/WebSocket 媒体及 Direct/Composite 重启持久化。先前[失败运行](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/38384160818)暴露 Docker web-builder 漏复制配置编辑器资源，已修复，未绕过镜像门禁。Dev.7 passed complete Windows qualification; the latest editor-owner deadline fix still needs a new candidate. The complete container preflight passed after repairing a missing UI build input, retaining the failed run and all image gates.
- 表单外层普通编辑的 20 秒取消会早于异步探测完成，现仅对轨道探测使用 150 秒操作预算；新增浏览器回归跨过 20 秒并正常完成、未重复创建设备。本轮接入/批量/重试套件 10 项通过。Probe operations now outlive the ordinary editor deadline without extending normal writes. All ten focused import/batch/retry checks passed, including the clock-driven deadline regression.

## 发布前仍需完成 / Remaining qualification

1. 将表单外层探测等待修复纳入新 Windows 完整候选，重跑原生/打包/NSIS 门禁，五路混合编码可见呈现与占用复验。A complete new Windows candidate must include the editor-owner probe deadline fix, followed by visible mixed-codec qualification.
2. 同一暗夜精灵 13900HX/4090 Laptop、同五路来源、画质/FPS/音频设置，对照 stock OBS。分别测 H.264、H.265 与混合，比较直连与 go2rtc；每轮预热 3 分钟、采样至少 15 分钟，记录整体 CPU 中位/p95、内存、GPU 解码/编码、真实帧进度、断流恢复及摄像机连接数。全程不以降低画质代替性能达标。Same-machine/source/quality OBS comparison remains required; source fixtures cannot qualify this target.
3. 用户指定回放与至少一条正在直播的来源，进行至少一小时持续监看、网络中断及 go2rtc/应用正常重启恢复。One-hour replay/live soak, network fault and normal restart checks remain required.
4. 容器完整镜像、Android 新 APK 及适用回归；随后补齐发布说明和三端候选证据，再按版本化 dev→main 发布 PR 流程发布。Complete container/Android qualification and release evidence before the versioned release PR and publication.

不宣称达到 OBS 性能水平，不把短时、合成或 Linux 证据替代用户 Windows 实机验收。No OBS performance parity claim is made.
