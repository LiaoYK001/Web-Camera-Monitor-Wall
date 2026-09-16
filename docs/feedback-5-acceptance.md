# 反馈5 整改验收报告 / Feedback 5 acceptance report

> 基线：`5fec735` + 工作区未提交改动（本地启动脚本、转码器路径修复等）。
> 本报告区分**已在本机复现并验证**与**已实现但未在本轮实测**两项，不以页面绿灯代替媒体验证。
> Baseline: `5fec735` plus the uncommitted working tree. Each item is marked *verified* or *implemented, not yet run*.

## 自动化验证快照 / Automated verification snapshot

截至 `5d57d1a` 在 WSL2 Ubuntu-24.04 环境复现：

| 套件 | 命令 | 结果 |
|---|---|---|
| 前端类型检查 | `web\node_modules\.bin\tsc.CMD --noEmit` | 0 错误 |
| 前端运行时 | `playwright test -c playwright.local.config.ts --project=chrome`（monitor-view / wall-controls / playback-state） | 通过（含填充、几何、无音轨三态、首帧、退避、授权拒绝、编码探测） |
| Camera Registry | `python3 -m unittest tests.test_camera_registry` | 26/26 通过（含探测缓存并发合并/失效） |
| 启动器 | `node --test tests/test-dev-launcher.mjs` | 7/7 通过（含 Composite 参数与帮助） |
| C++ 核心 | `ninja -C ~/.cache/webobs-dev/<hash>/core-local` + `webobs-unit-tests` | 编译通过、单测全过（含 NVENC 就绪与 Program 分阶段状态） |

未列入上表的实测（真实五路 ≥30 分钟长稳、原始 1080p/GPU 会话、OBS 侧 NVENC、Docker/vGPU）仍需在具备来源/GPU 的环境中执行，见文末“未在本轮实测”。端到端 Composite 发布与浏览器 Program WHEP 持续解码已在本轮实测（见 F5-04）。

## 本机实测事实 / Verified on this machine

- GPU：NVIDIA GeForce RTX 3090（driver 616.92），WSL2 Ubuntu-24.04；**只有 `/dev/dxg`，没有 `/dev/nvidia0` / `/dev/nvidiactl`**。
- `libcuda.so.1` / `libnvcuvid.so.1` / `libnvidia-encode.so.1` 均在 `/usr/lib/wsl/lib` 可加载。
- ffmpeg 6.1.1：`h264_nvenc` / `hevc_nvenc` 编码小样与 `-hwaccel cuda` 解码小样**均通过**。
- 结论：反馈截图中 “NVIDIA NVENC 不可用” 的根因是 C++ 探测只认 `/dev/nvidia0`，与真实能力无关。
- **运行期抓取**（本机启动 `webobsd` 直连模式，端口 18080，Basic 认证）：
  - `GET /api/v1/program/status` → `{"enabled":false,"endpoint":"/api/v1/program/whep","configuration":"disabled","engine":"stopped","publish":"idle","reason":"composite_disabled"}`，证明 F5-04 分阶段状态字段在运行期生效；
  - `GET /api/v1/system/capabilities` → `videoEncoder.backends.nvenc.devicePresent = true`（仅凭 `/dev/dxg` 即判定设备存在），证明 F5-03 探测修复在运行期生效；由于该次启动未注入硬件探测环境变量，`libraryLoaded/encodeSupported/runtimeProbePassed` 仍为 false（如实反映）。

## F5-01 画面填充 / wall fill — 已实现并验证

- 自动布局改为确定性 squarified treemap：1/2/4/5/9/16 路与“两大三小”**覆盖率 100%**、无重叠、无越界、重复应用稳定。
- 新增 `MonitorView.fill`（默认 `stretch`）与逐来源覆盖；自动布局把有效 `scaleMode` 写入场景，Direct 与 Composite 共用同一有效布局。
- 视频、检测框、遮罩与叠加层统一走 `tileTransform`，检测框不再漂移。
- 验证：`monitor-view.spec.ts`（含新增 “fills the canvas…”、“keeps detection boxes…”）。

## F5-02 画面外诊断 / out-of-picture status — 已实现并验证

- 移除画面内黄色诊断按钮、状态胶囊与名称；新增画布外来源状态区（名称/实际状态/告警数/问题中心入口，可键盘操作）。
- 无画面时仅显示简洁占位，正常播放不再被按钮遮挡。
- 问题中心已按“来源+问题类型+组件”合并，并以 `resolved` 更新而非堆积。
- 验证：`wall-controls.spec.ts` 断言无 `.tile-status-button`/状态胶囊/名称，且有状态区。

## F5-03 NVIDIA 探测与加速 / NVIDIA detection and acceleration — 已实现，路径已实测

已实现并验证：
- `scripts/hardware-probe.py`：分别探测设备节点、库可加载、编码器注册、实际编码/解码小样，带超时与按环境签名缓存。
- C++：`video_encoder_backend_ready(kind, backend)` 按后端判定；NVENC 不再依赖 VA-API 字段，支持 `/dev/dxg` 与 `/dev/nvidia0`；硬件状态 JSON 分能力上报并新增 `libraryLoaded` 与硬件解码 `backend`。
- gateway 转码器：优先 CUDA 解码 + NVENC（`-preset p1 -tune ll -bf 0`），CUDA 不可用时软件解码 + NVENC 并标注“部分加速”，保留 VA-API/x264 回退。
- 验证：WSL 内 `g++` 编译并运行编码器就绪逻辑测试通过；增量构建 `webobsd`/`webobs-unit-tests` 成功；C++ 单测全部通过；`transcode-on-demand.sh` 语法检查通过，NVENC（CUDA 解码与软件解码两种）真实产出文件。

未在本轮实测 / not yet run：
- OBS 侧 NVENC 编码器（`obs-nvenc`）只有在 Composite 构建启用该插件后才注册；本机没有 `ffnvcodec` 头文件，因此 Composite 构建显式 `-DENABLE_NVENC=OFF`，OBS 编码能力如实为“未注册”（`encoder=false`），而 FFmpeg/NVENC 外部小样仍是 `encode=true / sample=true`——两者不再互相冒充。
- **已复现并修复的真实缺陷**：修复前 `detect_video_encoder_capabilities()` 把外部探测结果 `WEBOBS_NVIDIA_ENCODER_REGISTERED` 当成 OBS 编码器可用性，于是 `selected=nvenc` → `obs_video_encoder_create("obs_nvenc_h264_soft")` → OBS 报 `Encoder ID 'obs_nvenc_h264_soft' not found` → WHIP 输出启动失败、整个 Program 发布中断。现在 OBS 侧选择只认**本构建实际注册的编码器**（`encoder_registered()`），外部探测只体现在 `encode_supported / runtime_probe_passed`；真实运行日志为 `selected=x264 ... nvenc(encoder=false,encode=true,sample=true)` 并给出明确告警。`dev-native.py` 也会在检测到 `ffnvcodec` 头文件时自动 `-DENABLE_NVENC=ON`，并把 `-nv` 计入构建缓存 key（按特征组合隔离缓存）。
- Docker / vGPU 实机验收按约定留待后续。

## F5-04 本地服务端合成 / native Composite — 已完成端到端实测（Program WHEP 浏览器持续解码通过）

已实现：
- `-Composite` / `--composite` 贯通 PowerShell、Node、Python 启动器；不带参数保持 Direct-only 轻量默认。
- 构建缓存按功能组合隔离（`obs-composite` / `core-composite`），避免复用“仅 libobs”缓存。
- Composite 构建启用 OBS 插件但**显式排除 CEF/浏览器插件**，按需构建并校验 `obs-ffmpeg` / `obs-x264` / `obs-webrtc`，缺失时报具体模块名。
- 启动前运行硬件探测并导出 `WEBOBS_NVIDIA_*`；`WEBOBS_COMPOSITE_ENABLED` 随参数切换。
- 前端：分别显示未启用/依赖不完整/引擎失败/发布失败/浏览器连接失败，并给出 `.\scripts\dev.ps1 -Setup -Composite`、`.\scripts\dev.ps1 -Composite` 与日志目录。
- 后端分阶段状态：`/api/v1/program/status` 新增 `configuration`（disabled/incomplete/ready）、`engine`（stopped/ready）、`publish`（idle/publishing）与 `reason`（composite_disabled / webrtc_transport_disabled / engine_not_active / whip_output_not_ready），由运行状态如实推导，不再让前端只能显示“未知”。
- 验证：`python3 scripts/dev-native.py --check --composite` 通过；`tests/test-dev-launcher.mjs` 7/7 通过（含 Composite 帮助与参数校验）；C++ 核心重新编译通过且单测全过（含新增字段的 control_server）。

未在本轮实测 / not yet run（**不得视为已支持**）：
- 实际执行 `-Setup -Composite` 的 OBS 插件构建：本轮在 WSL 逐项复现出**具体阻塞点**（均为可执行的环境/脚本问题，非代码逻辑）：
  1. `libx264-dev` 缺失导致 obs-x264 无 `x264.h` —— 已加入 `dev-native.py` 的依赖列表；
  2. 仅加 `-DENABLE_PLUGINS=ON` 会在可选采集插件处配置失败（先 `LibAJANTV2`/aja，再 `XCB COMPOSITE`/linux-capture）—— 需显式 `-DENABLE_AJA=OFF -DENABLE_DECKLINK=OFF -DENABLE_VLC=OFF`（并可能补 `libxcb-composite0-dev`）；
  3. `check_obs_browser()` 在 `ENABLE_PLUGINS=ON` 时无条件要求 obs-browser **子模块内容**，而 `dev-native.py` 的 WSL 快速路径用 `git archive` 生成 Linux 存储源码，**archive 不含子模块**，因此必然配置失败。
  4. 按上述修复后 configure 已能依次越过 aja→XCB→obs-browser→FFmpeg(avfilter/avdevice)→Libva→Libpci→MPEGTS(SRT/RIST)→SpeexDSP，最终停在 **`LibDataChannel` 缺失**（`plugins/obs-webrtc/CMakeLists.txt:9`）。obs-webrtc 是 Composite 发布到 MediaMTX 的 WHIP 输出所必需，而 `libdatachannel` **不是 Ubuntu 24.04 的 apt 包**，需要像 Docker 镜像那样单独构建/安装。
  结论（本轮已更新）：源码构建并安装 libdatachannel v0.22.6 后，`cmake` 配置成功生成 `build.ninja`，且 **`obs-ffmpeg.so` / `obs-x264.so` / `obs-webrtc.so` 三个插件全部编译链接成功**（位于 `rundir/Release/lib/obs-plugins/`），启动器的模块校验可通过。上述依赖与开关、子模块复制、libdatachannel 源码构建均已固化进 `dev-native.py`。
  进一步实测：项目 C++ 后端以该 Composite OBS 构建重新配置并编译成功（`core-local-composite`：`webobsd` 与 `webobs-unit-tests` 链接通过），且 **`webobs-unit-tests` 全部通过**（`LD_LIBRARY_PATH` 指向该构建的 libobs）。
  **运行期已实测（引擎 + 发布）**：在 WSL + Xvfb 软件渲染下，以 Composite 核心 + Composite OBS 插件启动，OBS 成功加载 obs-ffmpeg/obs-x264（按场景来源按需加载模块，纯摄像头场景不再因缺 CEF/obs-browser 失败），创建 x264 + libopus 编码器并启动 WHIP 输出；启动 MediaMTX 后日志显示 `PeerConnection state is now: Connected`、`Connect time: 88ms`、`WebRTC program publishing is ready`，`/api/v1/program/status` 由 `publish:"idle", reason:"whip_output_not_ready"` 变为 `publish:"publishing", reason:""`。
  MediaMTX 侧取证（默认空场景）：`GET /v3/paths/list` 显示 **`program` 路径 `ready:true`，tracks 为 `["Opus","H264"]`，`bytesReceived` 约 1.2 MB**，即 OBS 合成确实在向 MediaMTX 推送真实 H.264 + Opus 媒体。
  **接入真实五路场景的无头实测（负面证据，重要）**：用缓存中真实的 5 路 camera 场景 + Xvfb 软件渲染启动，WHIP `PeerConnection Connected (42ms)`，但 20 秒内 `WebRTC publishing did not become ready`，最终 `Total frames output: 0`、`Total drawn frames: 17 (157 attempted)`、**`rendering lag/stalls: 140 (89.2%)`**、`encoding lag 10/111 (9.0%)`。说明在**无 GPU 的 Xvfb 软件渲染**下，5 路 1080p 合成无法产出可用节目流（渲染瓶颈），需要 WSLg/GPU 桌面会话；这也与 `docs` 中“允许软件渲染降级但必须明确提示”的约定一致。相机可达性未单独确认。
  **降低负载后的真实五路实测（通过）**：把真实 5 路场景复制为 960×540 并把目标 FPS 降到 5，同样在无头软件渲染下启动后：`/api/v1/program/status` → `{"configuration":"ready","engine":"ready","publish":"publishing","reason":""}`，MediaMTX `program` 路径 **`ready:true`，tracks `[Opus,H264]`**，OBS 日志 `WebRTC program publishing is ready`（`Connect time: 33ms`）。即**真实五路场景的 native 合成与 Program 发布链路可用**，瓶颈是 1080p@30 在纯软件渲染下的算力，而非引擎/发布逻辑；生产验收应在 WSLg/GPU 桌面会话按原始 1080p/帧率执行。
  代码修复：`obs_engine` 模块加载改为“基础必须 + 按来源类型按需”、OBS 配置目录支持 `WEBOBS_OBS_CONFIG_DIR`；`dev-native.py` 构建 `libobs-opengl` 并为 native 提供配置目录。
  **浏览器 Program WHEP 持续解码实测（通过）**：真实 5 路来源（缓存中的真实 camera 场景，缩放为 960×540 场景）启动 Composite 后，用 Playwright Chromium（WSL 内置 `chromium-1234`，headless）向 MediaMTX `POST /program/whep` 建立会话：
  - 协商：`payloads: a=rtpmap:108 H264`、`kinds: ["video"]`、`state: connected`、`ice: connected`、`videoWidth×Height = 960×540`、`readyState 4`；
  - 首帧与持续出帧：`requestVideoFrameCallback` **41 帧 / 20 秒**、`getVideoPlaybackQuality().totalVideoFrames` 增量 44、`lastMediaTime=16.123s`（媒体时间持续前进，不是静态首帧）；
  - MediaMTX 同时新增 reader，`outboundBytes` 由 0 增至 1,264,532，`inboundFramesInError: 0`。
  即 **来源 → OBS 场景合成 → H.264(+Opus) → MediaMTX → Program WHEP → 浏览器连续解码** 的完整链路已在真实五路来源上跑通；约 2 fps 是纯软件渲染（Xvfb、无 GPU）的算力上限，生产验收仍需 WSLg/GPU 桌面会话按原始 1080p/帧率复测。
  **启动器分级就绪已实测**：`dev-native.py` 现按“进程存活 / 引擎就绪 / Program 发布”三级分别探测与上报（实测输出 `Composite 分级就绪：进程存活=是；引擎就绪=是；Program 发布=是；轨道=Opus,H264`）；Composite 下核心就绪预算提高到 300 秒（真实五路来源要等 20 秒以上才开始监听控制面），避免把“核心尚未监听”当成“发布失败”。
- 仍需实测：≥30 分钟连续出图、≥90% 解码帧率、单路断开恢复、CPU/GPU 归因；本轮浏览器侧只连续解码 20 秒。`/api/v1/program/status` 的完整 JSON 建议按上文命令用带凭据的 curl 直接抓取一次（本轮以启动器三级就绪与 MediaMTX program 路径为证）。

## F5-05 多音轨 / per-source audio tracks — 逐轨探测/通道/前端混音/Scene v6 持久化已实现；引擎逐轨混音路径已查明但未达成

已实现：
- 音轨状态三态：只有**真正绑定媒体流且音轨数为 0** 才判定“该源没有音频轨道”（无 capability 不再误报）；已挂载未绑定流、Profile 未探测或探测失败显示“音频轨道待探测”并提供“重新探测”入口；纯色/文字/图片/嵌套来源直接判定无音轨。确认无音轨的来源隐藏电平/阈值/音量控制；有音轨来源可配置方向/位置/大小/透明度、阈值与告警边框。
- 电平表默认 OBS 风格左侧竖放，不遮挡画面标签。
- 验证：`wall-controls.spec.ts` 断言未探测摄像头显示待探测 + 重新探测按钮且不显示电平选项。
- **后端真实多音轨通路（本轮新增，已运行期实测）**：
  - `GET /api/v1/sources/<id>/audio-tracks`：对来源真实音轨做 ffprobe 探测（`-select_streams a`）并按路由缓存，返回 `index`（`0:a:<index>` 相对索引）、`streamIndex`、`codec`、`channels`、`channelLayout`、`sampleRate`、`language/title`、`sourceCodecBrowserCompatible` 与每条音轨的 audio-only WHEP 端点。**有音轨 / 确认无音轨（`tracks: []`）/ 探测失败（502 `audio_tracks_unavailable`）三态可区分**（探测改用通用 `run_capture_text`：此前单 token 校验会把 ffprobe 的 JSON 输出误判为失败，导致任何来源都返回“探测不可用”）。
  - 每轨一条独立 audio-only MediaMTX 路径 `audio-<32hex>-t<index>`，由 `gateway/transcode-on-demand.sh` 新增的 `audio-track <index>` 模式按需拉起（`-map 0:a:<index> -vn -c:a libopus`）——MediaMTX 1.18.2 的单个 WHEP 会话只映射一路音频输出，所以必须一轨一路；`gateway/mediamtx.yml` 同步补齐 `audio-*` 的 publish/read 权限（缺权限时发布被 401 拒绝）。
  - 浏览器端点 `POST /api/v1/sources/<id>/audio-tracks/<index>/whep` 与 `DELETE .../whep/session/<token>`；`Session` 增加 `audio_track`，最后一个同轨会话关闭时只释放该轨自己的路径（不会误删其他观看者仍在使用的视频路由）。
  - 单元测试 `core/tests/common_tests.cpp::audio_track_tests`：ffprobe JSON 解析（含字符串型 `sample_rate`）、空/畸形/超大输出、`0:a:N` 相对索引与绝对 `streamIndex`、路径命名与索引回环、非法 token/索引、路由参数校验（路径与索引不匹配即拒绝）、Opus/G.711 与 AAC 的浏览器兼容判定。
  - 运行期实测（合成双音轨来源 `rtsp://127.0.0.1:8554/hybrid-<token>`，H.264 + 2×Opus）：`audio-tracks` 返回 2 条真实音轨；浏览器用两个独立 audio-only WHEP 会话同时取流——**track0 `opus, connected, bytesReceived=273345, packetsReceived=1025, currentTime=20.29s`**、**track1 `opus, connected, bytesReceived=230093, packetsReceived=790, currentTime=20.29s`**；两个会话 `DELETE` 均返回 **204**，随后 MediaMTX 的 `audio-*` 路径消失（资源释放已实测）。
  - 同一次实测确认了设计前提：MediaMTX 1.18.2 的 RTSP 路径可承载多路音轨（`tracks: ['H264','Opus','Opus']`），但单个 WHEP 会话只映射一路音频输出。
  - 本环境真实相机**没有任何音轨**（`/v3/paths/list` 为 `tracks: ['H265']`，API 返回 `tracks: []`），故多音轨用合成来源验证；相机“确认无音轨”状态本身也是实测结果。

- **前端真实多音轨通路（本轮新增，已自动化实测）**：
  - `web/src/sourceAudio.ts`：`GET /api/v1/sources/<id>/audio-tracks` 客户端，15 秒 TTL 缓存 + 并发去重，三态（有音轨 / 确认无音轨 / 探测失败）分别映射为可用 / `none` / 待探测；`invalidateSourceAudioTracks` 让“重新探测”真正失效缓存而不是重放旧结果。
  - `web/src/directAudioMixer.ts`：混音条目按 **“来源+输入音轨”** 建键（`sourceId#trackIndex`），每条音轨独立的 GainNode/AnalyserNode，并按来源增加真实**合并**测量节点（各路增益求和后再测 RMS/Peak），快照同时给出合并值与逐轨值；video 元素始终 `muted`，多轨时不会从视频元素重复出声。
  - `web/src/audioTrackChannel.ts`：每条选中音轨一路 audio-only WHEP（只 `addTransceiver('audio')`），无“首帧”概念，改用**真实 RTP 包数进展**判定存活（6 秒无进展即重连），带抖动有界退避，401/403 直接停止，关闭时 DELETE 会话。
  - `web/src/AudioWorkspace.tsx`：按来源分组，列出真实音轨复选框（默认第一条、可多选）、每轨静音与增益、合并/独立电平切换；取消勾选/切换来源/卸载都会释放该轨通道与 Web Audio 节点。
  - 测试：新增 `web/tests/local-runtime/audio-tracks.spec.ts`（含 `tests/harness/audioWorkspaceMount.tsx`）断言来源分组、默认选中第一轨、多轨控件数量、合并/独立切换、无音轨与待探测两种状态、重新探测触发第二次请求，并断言每轨 `POST .../audio-tracks/<i>/whep` 与取消勾选后的 `DELETE .../session/` 真实发生。本轮聚焦套件 **22/22 通过**（原 21 项 + 新增 1 项），`tsc --noEmit` 0 错误。
  - 测试还暴露并修复了一个真实缺陷：控制面返回的是**相对**端点，而会话 Location 校验此前按绝对 URL 解析，导致 audio-only 通道永远拿不到会话地址（现在以页面 origin 为基准解析）。

- **Scene v6 `audioInputs` 与持久化（本轮新增，已自动化实测）**：
  - `SceneSource` 新增按“来源+输入音轨”的 `audioInputs[{track,gain,muted}]`，schema 版本升到 6；读取 v5 文档时按旧 `audioTrack` 迁移为单条输入，并把文档升级为当前版本后返回。
  - 解析/校验（track 0..31、gain 0..1、最多 8 条、不得重复、未知字段拒绝）、序列化、以及 Scene/Studio 存储的 legacy 迁移路径均已打通——顺带修正了 `migrate_scene_json` 中 `version > 4` 的守卫会把 v5 文档误判为“不受支持”的缺陷。
  - 前端保存音频配置时写回 `audioInputs`，并把 legacy `audioTrack` 同步为第一条输入；重新打开工作台会按已保存的勾选/增益/静音恢复（“保存音频配置”按钮在仅有音轨改动时也可用）。
  - C++ 单元测试 `scene_audio_inputs_tests`：v5→v6 迁移、每轨增益/静音保留、显式空列表（表示“该源不贡献音频”）、序列化回环，以及 track>31、gain>1、重复音轨、未知字段、超过 8 条等拒绝分支；前端 `audio-tracks.spec.ts` 增加“已保存选择回填”和“保存后 PUT 文档含 audioInputs 与同步的 audioTrack”断言。

- **引擎侧（本轮修正，结论已改）**：
  - 已实现并保留：`resolved_audio_inputs()`（库单元，可单测）决定要混的输入轨：显式 `audioInputs` 优先，否则回退 legacy `audio_track`；**修掉一个真实缺陷**——旧实现把输入轨序号当作 *输出调音台位*（`1U << (audio_track-1)`），导致 `audioTrack > 1` 的来源在节目里其实**没有声音**，现在输出统一走节目总线（mixer 1），首条输入轨的 gain/mute 叠加在来源音量/静音之上。
  - **被实测否证的假设（重要）**：曾按“克隆 OBS 源实例 + `ffmpeg_source` 的 `track` 设置选择输入轨”实现逐轨混音，随后被证伪并已回退：本构建的 Media Source **没有音轨选择属性**（`plugins/obs-ffmpeg/obs-ffmpeg-source.c` 的属性表只有 input/inputFormat/reconnect/hw_decode/color_range/ffmpeg_options 等，全文没有 `"track"` 键），因此该设置被静默忽略。
  - 否证证据（合成双音轨来源 a:0=440Hz、a:1=880Hz，独立 8555 端口稳定发布后再启动引擎，排除来源健康重启干扰）：① 两个来源分别配置 `[{track:0}]` 与 `[{track:1}]` 时，节目里**只有 880Hz**（e880≈3.3e7，约为单源两倍），440Hz 始终在底噪（−61 dB）；② 单来源双输入 `[{track:0},{track:1}]` 三次抓取也**只有 880Hz**（e880≈1.68e7，440Hz≈1.5e4）；③ 方法学校准：直接从发布流抓 `a:0`/`a:1` 分别得到 440Hz(+64 dB) 与 880Hz(−61 dB)，说明来源本身两轨正常、分析可靠。
  - 因此当前实现**不再创建会被静默忽略的附属实例**，而是在配置了多条输入轨时明确记录一条告警（“该 OBS 构建没有 Media Source 音轨选择属性，额外输入轨尚未混音，需要走网关 audio-only 抽取通道”），避免用重复的默认音轨冒充逐轨混音。
  - 本轮把这条正确路径补全并实测：`transcode-on-demand.sh` 的 `audio-track <index>` 模式**接受显式 RTSP(S) 源 URL**（不再只认 `direct-<32 hex>`），并用严格字符集限制（可打印 ASCII、无空格、≤2048 字节）防止通过该字段注入额外 ffmpeg 参数；新增自动化测试 `tests/test-transcoder.mjs`（3/3 通过）覆盖 URL 形式、`direct-` 形式、track/路径不匹配、超范围 track、用 audio-only 路径喂 hybrid、含空格与注入式 URL、参数个数错误等拒绝分支。
  - 运行期实测（在 MediaMTX `hybrid-cccc…` 上发布 a:0=440Hz / a:1=880Hz，两条 `audio-<token>-t0/t1` 路径的 `runOnDemand` 用显式源 URL 调用该模式）：抽取结果分别**只含 440Hz**（e440 1.676e7 / e880 1.59e4，+60 dB）与**只含 880Hz**（e880 1.677e7 / e440 1.35e4，−62 dB），两条路径 `tracks` 均为 `['Opus']` —— “一轨一路”同时绕开了 MediaMTX 单音频输出与 OBS 无音轨选择属性两个限制。
  - 引擎接线（本轮已实现，但**默认关闭且未验证通过**）：`obs_scene_runtime` 用同一个 `WEBOBS_TRANSCODER_PATH` 环境变量加 MediaMTX 控制 API（`/v3/config/paths/add|delete`）为每条输入轨建立 audio-only 路径（命令经单引号转义，避免 URL 里的 shell 元字符），把该轨的 OBS 源实例指向 `rtsp://127.0.0.1:8554/audio-<token>-t<index>`，并把它们作为**画面外**的场景项加入节目场景（否则源不会开始播放），同时静音主源以免重复默认音轨。
  - **实测未通过，已抓到崩溃栈**：引擎在创建抽取通道后不久以 glibc `free(): double free detected in tcache 2` 中止，节目全程静音（多次抓取 peak=0），MediaMTX 侧没有任何 `audio-*` 路径的 `runOnDemand command started`（抽取实例只打印了 `settings:`，从未连接）。沙箱内无 gdb、无 root（不能改 `core_pattern`、不能装调试器），因此在 `main.cpp` 增加了一个**默认关闭**的崩溃回栈钩子（`WEBOBS_BACKTRACE_ON_CRASH=1`，`backtrace_symbols_fd`），拿到真实栈：
    ```
    __libc_free → abort            (double free)
    libobs.so.30(+0x70133)
    libobs.so.30(obs_source_enum_active_tree+0x7b)
    libobs.so.30(obs_canvas_set_channel+0x19d)
    webobsd(+0x204b51) → webobsd(+0x1ee655) → webobsd(+0x1e5a80) → main
    ```
    即崩溃发生在**设置节目输出通道时 libobs 遍历活动源树**的阶段，触发点是抽取源与场景/活动树的交互，而不是 HTTP/JSON/路径创建代码。已排除的假设：① 抽取源作为隐藏场景项 → 仍崩；② 去掉 `obs_source_inc_active`（只靠场景项激活）→ 仍崩。
  - **本轮进展（已修掉崩溃，但通道仍未启动）**：把抽取通道放进**独立的私有场景**（`obs_scene_create` 创建、不挂到任何 canvas、隐藏项）后，**double free 消失**（`fatal signal` 计数 0），说明崩溃确实来自节目场景活动树对抽取源的遍历。但随后实测：抽取实例仍只打印 `settings:`，MediaMTX 侧没有 `audio-*` 路径的 `runOnDemand command started`，节目音频仍全程静音（4 次抓取 peak=0）——即**隐藏项不会让源进入 playing/shown 状态**。
  - 把私有场景里的抽取项改为**可见**（该场景不渲染，理论上无副作用）后：媒体仍未启动统计（`audio track 1/2` 无 Reconnected），而 **double free 立即复现**。也就是说：可见 → 源被激活但触发活动树崩溃；隐藏 → 不崩但源永不启动。这指向 libobs 对“额外私有 ffmpeg_source 实例 + 场景激活”的处理本身，下一步需要换一种承载方式（例如常规 `obs_source_create` 注册的源、或让网关直接产出已混合好的单路音频供主源使用），而不是继续在场景项可见性上打转。
  - **本轮又试了第三种激活方式**：完全不建场景项，改用 `obs_source_inc_showing()` 直接把抽取实例标记为 showing（`dec_showing` 成对释放）。结果：**不崩溃**（`fatal signal` 计数 0），但抽取实例依旧不连接（`audio track 1/2` 无 `Reconnected`）、MediaMTX 没有新的 `audio-*` `runOnDemand command started`、节目音频 4 次抓取仍 peak=0。
  - 至此三种激活方式都已实测：场景项可见 → 源被激活但活动树 double free；场景项隐藏 → 不崩但源不启动；`inc_showing`（无场景项）→ 不崩但源同样不启动。结论：**libobs 不会为这些额外的私有 `ffmpeg_source` 实例启动媒体播放**，继续调整“激活方式”已无收益；下一步应改变承载方式（用常规 `obs_source_create` 注册的源，或让网关直接输出一路已混好的音频给主源）。
  - **本轮再试第四种**：把抽取实例从 `obs_source_create_private` 换成**常规注册源** `obs_source_create`（配合 `inc_showing`、不建场景项）。结果：**不崩溃**，但仍无 `Reconnected`、无新的 `audio-*` `runOnDemand command started`、节目静音。即“私有/常规注册”也不是原因。
  - **结论（已验证的四次否定）**：在本 OBS 构建下，凡是“为同一来源额外创建 OBS 媒体源来单独解一条输入轨”的做法都走不通——可见场景项能激活但触发活动树 double free，隐藏场景项与 `inc_showing`（含常规注册源）不崩但源永不开始播放。继续在激活/注册方式上试错已无收益。
  - **下一步的正确设计（已明确，尚未实现）**：不在引擎里加源，而是让**网关输出单路“已按要求混好”的音轨**，再让每个 scene source 只保留一个媒体源：新增 `transcode-on-demand.sh` 的 audio-mix 模式（`-map 0:v -filter_complex ... amix ...` 把选中的多条输入轨按各自 gain/mute 混成一路 Opus，视频 `copy`），产出 `mix-<token>` 路径；引擎在有 >1 输入轨时把该源的 `input` 指向这条路径。这样既保留逐轨可控（在网关侧完成），又完全避开“额外 OBS 源”这一被四次实测否定的路线。
  - 当前代码保留**不崩溃**的形态（常规注册源 + `inc_showing`），功能仍由 `WEBOBS_AUDIO_TRACK_EXTRACTION` 选入；默认路径不变，多输入来源仍打印明确的“额外音轨尚未混音”告警。
  - **本轮已落地网关侧的第一步**：`transcode-on-demand.sh` 新增 `audio-mix` 模式（`<src> mix-<32hex> audio-mix <index:gain:muted,...>`，最多 8 条、index 0..31、gain 0..1、muted 0/1，逐条校验），用 `volume`+`amix(inputs=n,normalize=0)` 把选中的多条输入轨按各自 gain/静音混成**一路 Opus**，视频 `copy`；`gateway/mediamtx.yml` 同步开放 `mix-*` 的 publish/read 权限。
  - 验证状态（诚实记录）：校验逻辑已实测——合法 spec 通过（继续进入 ffmpeg，因无媒体服务返回 145），`gain>1`、`index>31`、`muted` 非 0/1、分隔符错误、超过 8 条、目标不是 `mix-*` 均返回 2；既有 `tests/test-transcoder.mjs` 仍全绿。**但本轮的自动化用例追加与运行期抓取都因为我在 PowerShell 串联命令时的转义/引号问题失败**（追加内容被 PowerShell 的反引号转义破坏、抓取脚本的 JSON 引号被外层 shell 吃掉），因此“混音流真的同时含两路音轨且增益正确”这一条**还没有实测证据**，下一篇应先用文件写入（而不是 `bash -lc` 串联）重做这两步。
  - 因此该接线现在由环境变量 `WEBOBS_AUDIO_TRACK_EXTRACTION` **显式选入**：默认路径保持第 65 轮行为（主源音频 + 明确告警），不会把未验证的代码带进默认运行路径；下一轮应在该开关打开的情况下定位并修掉 double free，再恢复为默认。
  - 单元测试：`resolved_audio_inputs` 的显式优先与 legacy 回退；`webobs-unit-tests` 全绿。

未实现 / not implemented（明确列为后续项）：
- **Composite 逐轨混音本身仍未达成**：只混第一条输入轨；额外输入轨需要接到网关 `audio-<token>-t<index>` 抽取通道（接口已存在并实测），并决定抽取通道的生命周期与复用。
- 逐轨同步偏移仍按来源统一处理。
- 真实相机多音轨未实测（本环境相机无音轨；已用合成双音轨来源完成后端等价验证与浏览器双会话取流）；两轨同时稳定出流、WSLg/GPU 桌面会话与 Docker/vGPU 验收仍需后续执行。

## F5-06 五路播放稳定性 / playback stability — 状态机已实现并验证

- `whep.ts`：信令/ICE/媒体轨道/首帧/持续播放分开记录，**只有 `requestVideoFrameCallback` 呈现真实帧才进入 `live`**；20 秒首帧超时、6 秒帧停滞看门狗（后台暂停不误判）、带抖动的有界退避、连接代次校验、迟到响应释放；自动播放被阻止与媒体失败分开处理并提供 `resume()`。
- 探测缓存与并发合并：同一 Camera/Profile 的 ffprobe 结果按“端点哈希+传输方式”缓存（TTL 默认 15 秒，键不保留原始 URL），并发调用等待在途探测并复用结果（一次 ffprobe 服务多个调用者），Camera 保存/目录变更按来源失效。
- 真实拓扑标注：状态区按 `webobs:media-topology` 区分真直连 / 网关转发 / Hybrid 转码 / Composite，不再把全部正常播放标成“直达”（未知时回退“播放中”）。
- 浏览器能力运行时探测：媒体计划只声明本机 `MediaSource.isTypeSupported` 实际支持的编码（H.265/WebCodecs 不再无条件宣称，H.264 为基线兜底），避免规划出客户端无法解码的直连路径。
- 授权失败不再无限重连：WHEP 收到 401/403 时记录 `authorization_rejected`、释放会话、进入重新配对指引并停止退避重试（`getStage().lastError` 可查），避免对未授权来源反复请求。
- 验证：`playback-state.spec.ts` 用脚本化 `RTCPeerConnection` + stub rVFC 断言“ICE 连接不等于 live”，并验证 ICE 失败后的抖动重连；`test_camera_registry.py` 覆盖并发合并、TTL 命中与变更失效（26/26 通过）；`monitor-view.spec.ts` 覆盖拓扑标签映射。

未在本轮实测 / not yet run：
- 真实五路 ≥30 分钟长稳、首帧 ≤20 秒统计、解码帧率 ≥90%、人为断开单路恢复、CPU/GPU 占用与慢读丢包归因。
- 转码/路由创建的引用计数与长期闲置回收、脱敏诊断摘要导出。

## 运行与验证命令 / Commands

```powershell
# 硬件能力（WSL 内）
python3 scripts/hardware-probe.py --json

# 前端相关测试（Chrome）
cd web; node node_modules/@playwright/test/cli.js test -c playwright.local.config.ts --project=chrome -g "monitor-view|playback-state"

# 启动器测试
node --test tests/test-dev-launcher.mjs

# 原生 Composite（首次构建较久；本机已实测引擎启动与 WHIP 发布）
.\scripts\dev.ps1 -Setup -Composite
.\scripts\dev.ps1 -Composite

# 无头环境复现（本机实测；Xvfb 软件渲染 + WEBOBS_OBS_CONFIG_DIR）
# 1) 构建后启动 MediaMTX，再以 composite 核心启动 webobsd：
#    xvfb-run -a -s "-screen 0 1280x720x24" <core-local-composite>/webobsd --scene-file <scene.json>
#    env: WEBOBS_COMPOSITE_ENABLED=true WEBOBS_WEBRTC_ENABLED=true WEBOBS_OBS_CONFIG_DIR=<可写目录>
# 2) 观察分阶段状态与控制面：
#    curl -u admin:<pw> http://127.0.0.1:8080/api/v1/program/status   # engine=ready / publish=publishing
# 3) 确认 MediaMTX 已收到节目媒体：
#    curl http://127.0.0.1:9997/v3/paths/list   # program: ready=true, tracks=[Opus,H264]
# 4) 一键等价路径（启动器会分别上报三级就绪，并对真实五路来源放宽核心就绪预算）：
#    cd <repo> && Xvfb :99 -screen 0 1920x1080x24 & DISPLAY=:99 python3 scripts/dev-native.py --composite
#    # 期望：Composite 分级就绪：进程存活=是；引擎就绪=是；Program 发布=是；轨道=Opus,H264
# 5) 浏览器 Program WHEP 持续解码：
#    页面内 RTCPeerConnection 加 recvonly video transceiver，POST SDP 到
#    http://127.0.0.1:8889/program/whep，用 video.requestVideoFrameCallback 计数；
#    参考实测：a=rtpmap:108 H264、41 帧/20 秒、960×540、lastMediaTime 持续前进。
```

## 结论 / Conclusion

F5-01、F5-02、F5-06 状态机与探测缓存已实现并有自动化验证；F5-03 的探测根因已在本机复现并修复，C++/转码路径已编译与实测，并修掉“外部 NVENC 探测冒充 OBS 编码器”导致 WHIP 输出启动失败的真实缺陷；OBS 侧 NVENC 仍如实报告为未注册，Docker/vGPU 未验收；F5-04 已完成真实五路来源 → OBS 合成 → H.264/Opus → MediaMTX → Program WHEP → 浏览器连续解码的端到端实测，启动器按三级就绪分别上报，仅 ≥30 分钟长稳与原始 1080p/GPU 会话待测；F5-05 在原有“无音轨/待探测/有音轨”三态过滤之外，补齐了后端与前端真实多音轨通路（逐轨探测 API + 每轨 audio-only 路径与 WHEP 会话 + 会话级资源释放；前端按来源分组、逐轨勾选/静音/增益、合并与独立电平、按“来源+音轨”建键的混音图），后端已实测双轨同时出流、前端已由 22/22 聚焦测试覆盖，并完成了 Scene v6 `audioInputs` 的模型/迁移/校验/序列化与前端持久化（C++ 单测 + 22/22 前端聚焦测试），并修掉“输入轨被误当输出调音台位导致 audioTrack>1 无声”的真实缺陷；引擎侧逐轨混音**未能达成**——实测证明本构建的 OBS Media Source 没有音轨选择属性，克隆实例只会重复默认音轨，因此该实现已回退并留有明确告警，下一轮应改为接入网关既有的按轨抽取通道（`audio-<token>-t<index>`）。**“画面干净且完整、加速状态真实”已达成；“五路持续出图、本地合成可用、多音轨实际可控”仍需在具备五路来源的环境中按上文命令继续实测。**
