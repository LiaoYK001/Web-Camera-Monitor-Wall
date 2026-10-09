# v4.1 发布说明（开发草案） / v4.1 release notes (development draft)

尚未发布 v4.1；v4.0 已发布安装包不包含本页的新调整。后续正式身份为 `v4.1` / `4.1.0`；当前仅准备开发候选。主交付端仍为 Windows x64、容器及独立 Android。

v4.1 has not been released. Existing v4.0 assets do not contain these changes. The intended stable identity is `v4.1` / `4.1.0`; only development candidates are being prepared.

## 本轮变更 / Changes

- Windows Direct 监看按需启停后台 Composite 发布，闲置 OBS 网络/媒体来源停止解码；录制保持连续。Windows uses on-demand Composite publishing and releases inactive OBS media decoding while recording remains continuous.
- NVIDIA Hybrid 增加 CUDA 解码及保留 NVENC 的分级回退，OBS 来源启用上游硬解探测策略。Hybrid adds CUDA decoding with staged NVENC/software fallback; OBS sources use upstream hardware probing.
- 系统状态统计本次应用进程树，区分 go2rtc、浏览器、FFmpeg 与后台服务，并提供整体 CPU 折算。Diagnostics show the owned desktop process tree and normalized CPU.
- go2rtc 命名流支持批量选择、逐项导入、部分失败重试、停止及不确定写入核对。Named streams support safe batch import, progress, partial retries, stopping and reconciliation.
- 网站回放自动检查 H.264 帧重排序兼容性，按需处理 B 帧；增加主页持续解码验收。Website VOD checks H.264 frame reordering and adds monitor-wall soak validation.
- 同时包含此前 dev 中的配置 Save/reload、RTSP 自动识别和实际主页播放/重启验收修复。Includes prior dev configuration reload, RTSP detection and actual playback/restart fixes.

## 已有证据 / Available evidence

- 前端 typecheck/build；相关浏览器回归 24 项通过。Frontend typecheck/build and 24 focused browser checks passed.
- Desktop 单元 48 项通过；原生 Python 15 项中 7 项通过、8 项因本机未构建正式运行时跳过。Desktop unit checks passed; local Python runtime checks distinguish seven passes from eight runtime-dependent skips.
- Linux/WSL 编译、CTest 2 项通过；实际 OBS→WHIP→MediaMTX→RTSP 解码验证待机、观看超过保温期、关闭后停止、强制踢出发布连接后恢复与健康状态。网站助手另通过 MP4/HLS 实际解码、重复连接及首次 HTTP 请求中断恢复。Linux/WSL compilation and two CTest cases passed; real transport exercised demand lifecycle and publisher fault recovery. The website helper passed MP4/HLS decoding, reconnect and initial HTTP disconnect recovery. These are separate from complete Windows candidate qualification.
- 2560×1440/25fps 合成 HEVC → NVENC 的单路 20 秒试验：软件解码 3.375 CPU 秒、CUDA 解码 3.312 CPU 秒（本机 9950X3D/RTX3090）。样本差异很小，不能据此宣称显著优化，更不是暗夜精灵或 OBS 对照。A short synthetic decode sample showed little CPU difference and establishes neither significant savings nor stock OBS parity.
- 用户指定的 YouTube 回放：独立 RTSP 解码五分钟通过；旧候选自动直通的完整浏览器流程复现无画面；同候选显式 H.264 转换通过实际主页连续解码十分钟及完整重启恢复。实际输入含 B 帧；新版自动策略的独立 RTSP 解码已通过，完整新版候选仍待验收。The reported replay failed browser playback with old automatic passthrough; explicit H.264 conversion passed ten minutes of real monitor decoding and full restart recovery. The new automatic policy passed independent RTSP decoding; complete candidate qualification remains pending.

## 发布前仍需完成 / Remaining qualification

1. 新版 Windows 完整构建、按需 Composite 实际浏览器启停、五路实际混合编码、打包启动及 NSIS 门禁。Complete Windows candidate, actual browser demand lifecycle, five-stream mixed-codec, package and NSIS checks.
2. 同一暗夜精灵 13900HX/4090 Laptop、同五路来源、画质/FPS/音频设置，对照 stock OBS。分别测 H.264、H.265 与混合，比较直连与 go2rtc；每轮预热 3 分钟、采样至少 15 分钟，记录整体 CPU 中位/p95、内存、GPU 解码/编码、真实帧进度、断流恢复及摄像机连接数。全程不以降低画质代替性能达标。Same-machine/source/quality OBS comparison remains required; source fixtures cannot qualify this target.
3. 用户指定回放与至少一条正在直播的来源，进行至少一小时持续监看、网络中断及 go2rtc/应用正常重启恢复。One-hour replay/live soak, network fault and normal restart checks remain required.
4. 容器完整镜像、Android 新 APK 及适用回归；随后补齐发布说明和三端候选证据，再按版本化 dev→main 发布 PR 流程发布。Complete container/Android qualification and release evidence before the versioned release PR and publication.

不宣称达到 OBS 性能水平，不把短时、合成或 Linux 证据替代用户 Windows 实机验收。No OBS performance parity claim is made.
