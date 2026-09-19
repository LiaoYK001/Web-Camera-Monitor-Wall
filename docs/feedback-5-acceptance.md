# 反馈5 整改验收报告（当前状态）/ Feedback 5 acceptance report (current state)

日期 / Date：2026-09-19。
被测代码 / Code under test：Commit `93f790a`（渲染器探测与 OBS NVENC）+ `587e329`、`425d5df`、`f09dcaf`（批次 B/C/D）。其上 `367c2ab`、`37f12bb`、`4200576`、`ed70313` 只改验收驱动与文档，不改变被测服务端代码；长稳进程正是这一内容。
Baseline: commit `93f790a` (renderer probe + OBS NVENC) plus `587e329`, `425d5df`, `f09dcaf`. The later commits (`367c2ab`, `37f12bb`, `4200576`, `ed70313`) only touch acceptance drivers and docs, so the long-running services under test are exactly this content.

历史记录（旧结论、被否证的假设、逐步排查过程）见 `docs/feedback-5-acceptance-history.md`。本文件只描述当前状态。
Historical notes (previous conclusions, disproved hypotheses, the step-by-step investigation) moved to `docs/feedback-5-acceptance-history.md`. This file states the current state only.

## 1. 本轮自动化验证 / Automated verification this round

| 套件 | 命令 | 结果 |
|---|---|---|
| 前端类型检查 | `web\node_modules\.bin\tsc.CMD --noEmit`（工作目录 `web`） | 0 错误 / 0 errors |
| 前端运行时（真实 Chrome 153） | `playwright test -c <config> --project=chrome -g "monitor-view\|playback-state\|audio-tracks\|wall-controls"` | **22/22 通过** |
| 转码器与 audio-mix | `node --test tests/test-transcoder-mix.mjs tests/test-transcoder.mjs` | **7/7 通过**（含 ±10000ms 边界、越界拒绝、归一化延迟上报） |
| 启动器 | `node --test tests/test-dev-launcher.mjs` | **9/9 通过**（含 `-Soak`/`--soak`） |
| C++ 核心 | `cmake --build <core-local>` + `ctest` | 编译通过，`webobs-unit-tests` 全过（含新增 11 条混音路由等价断言） |
| OBS Composite 构建 | `python3 scripts/dev-native.py --composite --soak` | `obs-ffmpeg`/`obs-x264`/`obs-webrtc`/`obs-nvenc` 全部产出并通过模块校验 |

## 2. 环境结论（本轮重新探测）/ Environment, re-probed this round

旧报告的“本沙箱没有 WSLg 图形会话、只能用 Xvfb 软件渲染”**不再成立**。

- WSLg 可用：`DISPLAY=:0`、`WAYLAND_DISPLAY=wayland-0`、`XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir`、`/tmp/.X11-unix/X0`（Xwayland 已启动）。
- 硬件 OpenGL 可达：EGL/GL 真实探测在 `GALLIUM_DRIVER=d3d12` 下得到 `GL_RENDERER=D3D12 (NVIDIA GeForce RTX 3090)`；不设置时 Mesa 静默回退 llvmpipe。`scripts/dev-native.py` 现按容器入口的方式做真实探测，只在实际拿到非软件适配器时才上报 hardware。
- OBS 实际渲染器：`[info] Loading up OpenGL on adapter Microsoft Corporation D3D12 (NVIDIA GeForce RTX 3090)`。
- OBS NVENC：Ubuntu 无 `ffnvcodec`/`libmbedtls-dev` 且无 root，已把 `nv-codec-headers n12.1.14.0` 与 MbedTLS 3.6.2 装到用户缓存前缀；OBS 现输出 `NVENC version: 12.1 (compiled) / 13.1 (driver)`、`Loaded OBS module 'obs-nvenc'`，能力接口 `selected=nvenc, encoder=true`，`nvidia-smi` 显示 encoder 利用率约 8%。
- 已知限制（本轮已量化）：`obs-nvenc` 打印 `Failed to get a CUDA device for the current OpenGL context (CUDA_ERROR_OPERATING_SYSTEM)`——D3D12 后端 OpenGL 下无法共享纹理，退化为拷贝路径。实测 1920×1080 五路下 NVENC 24.5 fps、x264 29.7 fps，因此启动器在该条件下默认 x264（第 4.4.2 节）。`obs-nvenc` 偶发加载失败，此时同样回退 x264。
- 真实相机：`rtsp://192.168.31.199:8554/*` 可达。用户原始场景 1920×1080、5 路 camera（sha256 `87fcca32…c9b9`），运行时只读，未改写。

## 3. 六项反馈当前状态 / Status of the six items

| 反馈 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | `monitor-view.spec.ts` / `wall-controls.spec.ts`（22/22） |
| F5-02 干净画面 | 已实现并自动化验证 | `wall-controls.spec.ts` |
| F5-03 硬件加速 | **OBS 渲染与编码均已在真实运行中启用并取证**；网关 NVENC/CUDA 转码沿用既有实现 | 本文件第 2 节 + `nvidia-smi` |
| F5-04 本地合成 | **真实五路 1920×1080 Composite 30 分钟持续发布**（30/30 采样 ready、track=[Opus,H264]、`inboundFramesInError=0`） | `tests/artifacts/soak/…-composite-1080p-4200576/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有自动化验证；路由复用/先备后切有单测；有符号偏移有转码器用例；端到端音频驱动部分通过 | 见第 5 节 |
| F5-06 播放稳定 | **两种模式各 30 分钟浏览器验收均已执行**。合成模式用 x264 复测后达标：服务端 29.7 fps、浏览器接收 30.07 fps、解码 30.03 fps、呈现 28.7 fps（≥90%）；此前用 NVENC 只有 21.95–24.35 fps，原因是 WSL 下 NVENC 无法共享 GL 纹理（见 4.4.2）。Direct/Hybrid 五路持续出图 1787.8s，但首帧 31.7–74.4s、最大帧间隔 3.07–6.70s 仍超门槛 | `tests/artifacts/browser-soak/2026-09-17…composite/`、`…/2026-09-19T12-44-34-450Z-composite/`、`…/2026-09-19T09-49-57-510Z-direct/` |

## 4. 长稳实测数据 / Measured soak data

### 4.1 服务端（sampler，`tests/soak-evidence.mjs`）

- 运行：`2026-09-18T18-02-32-770Z-composite-1080p-4200576`，30 次每分钟采样，覆盖 29.0 分钟。
- renderer=hardware、encoder=nvenc。
- **通过**：`program` 路由 30/30 ready、tracks `[H264,Opus]`、字节 387 MB → 1451 MB、`inboundFramesInError=0`；每个采样都是 `publish=publishing`。
- **未通过**：逐来源帧推进与“无重启”。5 路中 2 路全程稳定（`camera-mu2ux4qk`、`camera-mu2ux99i`：最大帧龄 501ms、重启 2 次），另外 3 路反复 stalled/recovering：

| 来源 | 最大帧龄 | 重启次数 |
|---|---|---|
| camera-mu2uub8u | 113 s | 69 |
| camera-mu2uuez4 | 582 s | 41 |
| camera-mu2ux73u | 29 s | 25 |

### 4.2 浏览器（`web/tests/local-runtime/browser-soak.spec.ts`，真实产品页面 + Chrome）

- 运行：30.1 分钟（1812s），播放的是页面内的 `video[aria-label="实时合成节目画面"]`（服务端 Program）。
- 首帧 4551 ms（≤20s 通过）、最大帧间隔 1772 ms（≤3s 通过）、媒体时间推进到 1807.5s（持续出图通过）。
- **39768 帧 / 1812s = 21.95 fps，为目标 30 fps 的 73.2%，未达 90% 门槛。**

### 4.3 Direct/Hybrid 浏览器验收（2026-09-19）/ Direct/Hybrid browser acceptance

真实产品页面、真实 Chrome，先按产品自身的配对流程完成浏览器授权（创建配对 → 管理会话批准 5 路相机授权 → 完成配对，无任何桩授权），再切换到“网关直通/浏览器媒体”。

- 运行：`2026-09-19T09-49-57-510Z-direct`，**1787.8 秒（29.8 分钟）**、119 次采样。该运行在轮次边界被中止，未能写下自身汇总，数据由增量写入的 `browser-soak-timeline.jsonl` 重新计算（见同目录 `derived-browser-summary.md`）。

| 来源 | 帧数 | 实测 fps | 名义目标 | 比值 | 首帧 | 媒体时间 | 最大帧间隔 |
|---|---|---|---|---|---|---|---|
| camera-mu2uub8u | 30149 | 16.86 | 20 | 0.843 | 74.4 s | 1713.2 s | 3067 ms |
| camera-mu2uuez4 | 33960 | 19.00 | 20 | 0.950 | 31.7 s | 1756.2 s | 4016 ms |
| camera-mu2ux4qk | 29995 | 16.78 | 25 | 0.671 | 39.3 s | 1285.7 s | 5236 ms |
| camera-mu2ux73u | 33110 | 18.52 | 25 | 0.741 | 47.9 s | 1740.0 s | 3663 ms |
| camera-mu2ux99i | 29317 | 16.40 | 15 | 1.093 | 56.6 s | 1264.8 s | 6697 ms |

- 通过：五路媒体时间全部推进（无冻结）、无崩溃、持续播放近 30 分钟。
- 未通过：首帧（31.7–74.4s，预算 20s；瓦片是逐路建立网关计划后连接，且来源本身出图慢）、最大帧间隔（3.07–6.70s，预算 3s）、3 路的解码帧率未达名义目标 90%。
- 服务端同时刻采样（30 次，29.1 分钟）显示 21 条路由中仅 6 条持续 ready 且字节增长，**11 条从未 ready**——与“来源侧不稳定”一致。

### 4.4 瓶颈归因 / Bottleneck attribution

渲染与编码不是瓶颈：OBS 日志的渲染滞后为 **1/8247（0.0%）**、编码滞后 **59/8247（0.7%）**，`nvidia-smi` GPU 15%、encoder 8%。

瓶颈在**真实相机来源**。12 秒直接读取各相机（`ffprobe -count_frames`）：

| 来源 | 名义帧率 | 实测帧数/12s | 说明 |
|---|---|---|---|
| back_3 | 20 | 94（≈7.8 fps） | `Could not find ref with POC`（丢包） |
| front_3 | 20 | 185（≈15.4 fps） | 同上 |
| overview_c4 | 15 | 216（≈18 fps） | 同上 |
| hik_ch1_main / hik_ch2_main | 25 | 大量 `PPS id out of range` | 解码告警持续 |

### 4.4.1 健康来源对照实验 / Healthy-source control

为区分“产品管线上限”与“本轮来源欠佳”，用 5 路本地 1920×1080@30 的 `media` 源（同一 H.264 文件循环、无网络丢包）临时替换场景来源（副本，测量后已按 `build/scratch/scene.original.json` 还原并校验 sha256 `87fcca32…` 一致），其余配置不变，同一环境各测量 60 秒 program 输出：

| 场景 | program 服务端帧数/60s | 折合 fps | 对 30 fps 目标 |
|---|---|---|---|
| 真实 5 路相机 | 1473 | 24.5 | 81.7% |
| 健康 5 路合成来源 | 1630 | 27.2 | **90.7%（达门槛）** |

浏览器侧同一对照（真实产品页面 WHEP 播放 program）：

| 场景 | 呈现帧 / 解码帧 | 时长 | 呈现 fps |
|---|---|---|---|
| 真实 5 路相机 | 2735 / 未记录 | 116.9 s | 23.4 |
| 健康 5 路合成来源 | 4401 / **4409** | 179.3 s | 24.6 |

结论（比上一轮更精确）：**健康来源下服务端达到 90.7%，即“≥目标 90%”在服务端是可以达成的**；真实相机把它压到 81.7%，来源贡献约 −2.7 fps。浏览器侧无论来源都停在 24–25 fps（约为服务端输出的 90%），且**呈现帧与解码帧几乎相等（4401 对 4409）**，说明瓶颈不在“呈现”，而在 WebRTC 接收/解码节奏。因此剩余差距由两部分构成：来源侧约 2.7 fps，浏览器接收侧约 2.6 fps（27.2 → 24.6）。

### 4.4.2 编码器 A/B：瓶颈是 WSL 下的 OBS NVENC / Encoder A/B: the bottleneck is OBS NVENC under WSL

同一场景、同一时刻、同一来源，只切换 `WEBOBS_VIDEO_ENCODER` 并用同一方法测量 program 输出 60 秒：

| 编码器 | program 帧数/60s | 折合 fps | 对 30 fps |
|---|---|---|---|
| NVENC（auto） | 1473 | 24.5 | 81.7% |
| x264 | 1779 / 1789（两次） | 29.6 / 29.8 | 98.8% / 99.4% |

浏览器侧 `getStats()` 的 inbound-rtp 计数（3 分钟、同一页面路径）：

| 编码器 | framesReceived | framesDecoded | framesDropped | packetsLost | nackCount | 元素解码 fps | 元素呈现 fps |
|---|---|---|---|---|---|---|---|
| NVENC | 24.41 fps | 24.35 fps | 2 | 0 | 0 | 24.3 | 23.4 |
| x264 | **30.07 fps** | **30.03 fps** | 0 | 0 | 0 | **30.0** | **28.7** |

两条链路都是 `packetsLost=0`、`nackCount=0`，说明 WebRTC 传输与浏览器接收/解码如实送达并解码了发送端给出的帧：NVENC 只送出约 24.4 fps，x264 送出约 30.1 fps。

结论修正（取代本章此前“主要归因于来源”的说法）：**合成模式帧率未达标的主要原因是 WSL 下 OBS 的 NVENC 无法与 D3D12 后端的 OpenGL 上下文共享纹理**（日志 `Failed to get a CUDA device for the current OpenGL context: CUDA_ERROR_OPERATING_SYSTEM`），退化为拷贝路径后只能维持约 24.5 fps；改用 x264 后，即使是本轮不稳定的真实相机，服务端 29.7 fps、浏览器接收 30.07 fps、解码 30.03 fps、呈现 28.7 fps，**“≥目标 90%”的门槛在服务端与浏览器两侧都达成**。来源侧的影响仍然存在（NVENC 下真实相机 24.5 对健康来源 27.2），但量级约 2.7 fps，不是主因。

据此启动器默认值也做了修正：D3D12 后端 OpenGL 下若未显式指定 `WEBOBS_VIDEO_ENCODER`，默认使用 x264 并打印实测理由；显式设置 nvenc 仍可强制硬件编码。

## 5. F5-05 音频现状与证据 / Audio state and evidence

已提交：

- `587e329` 批次 B：等效音频路由复用（共享 `mix-*` 守卫）、先备后切 + 回读校验、准备失败返回来源级错误并保留旧节目；`audio_routing_matches` 有 11 条单测。
- `425d5df` 批次 C：`B=max(0,-min(d_i))`，逐轨 `adelay=B+d_i`，视频用 `setts` 后移 B；校验接受 ±10000ms；`setts` 在 1/1000 与 1/90000 时间基下实测均精确平移 100ms。
- `f09dcaf` 批次 D：`-Soak`/`--soak` 贯通 PowerShell/Node/Python。

`tests/audio-regression.mjs`（自建 MediaMTX + 440/880Hz 双音轨来源 + 真实 `transcode-on-demand.sh` audio-mix）本轮实测：

- **单次增益**：`0:0.25:0,1:1.0:0` 实测 440/880 比值 **12.06 dB**，与理论 −12.04 dB 相符 → 增益只应用一次（通过）。
- **首轨静音**：对真实抓取做直接 DFT，440Hz 幅度 **0.0000**、880Hz **0.0623** → 静音首轨不会静音整个来源（通过；驱动自身的窗口统计此次抓到了启动空档，报告为 FAIL 属驱动缺陷，见下）。
- **负偏移**：转码器 stderr 实测输出 `新增端到端延迟: 2000ms (video and every track)`，流内视频/音频轨道均存在（通过）；“视频后移 2 秒”的 PTS 断言因录制未加 `-copyts`、复用器把两条流各自归零而**不可信**，需要在后续修正测量方法。

驱动当前缺陷（已在脚本头部注明）：录制进程与转码器首帧存在竞争，个别用例会抓到启动空档而得到全零窗口；本次已因此产生一次误报。该驱动**尚不能单独作为验收判据**。

## 6. 本轮发现并修复的两个产品缺陷 / Two product defects found and fixed this round

1. **Direct-only 网关启动即崩溃（`185197b`）**：`detect_video_encoder_capabilities(config, false)` 无条件调用 `encoder_registered()`，后者遍历 `obs_enum_encoder_types`；Direct-only 路径刻意跳过 `obs_startup`，于是在控制面监听之前 SIGSEGV（栈顶 `libobs.so.30(obs_enum_encoder_types+0xd)`，两个构建同样崩溃）。由 `361cada` 引入。修复后 Direct-only 可正常启动并返回如实的 `configuration=disabled`。**这是 Direct/Hybrid 验收长期缺失的直接原因。**
2. **未配对被误报为控制面不可达（`0a1026b`）**：`requestBrowserPlan()` 把 `browserDeviceHeaders()` 与 fetch 放在同一个 try 中，未配对时抛出的「此浏览器尚未完成配对」被改写成「控制面当前不可达」，把排查方向引向网关/网络。现在未配对会走 `DirectPreview` 的 needsPairing 分支并给出配对操作。

## 7. 仍未完成 / Still open

1. **Direct/Hybrid 的首帧与帧间隔**：合成模式在 x264 下已同时满足帧率、首帧与帧间隔门槛；Direct/Hybrid 五路的首帧（31.7–74.4s）与最大帧间隔（3.07–6.70s）仍超门槛，尚未用健康来源复测，也未用 x264 之外的变量做过 A/B（Direct/Hybrid 不经 OBS 编码，其缺口另有成因）。
2. **单路断开/恢复的受控故障注入**：本轮只有真实来源的自发 stall/recover 观测，没有受控注入，因此“其余四路不被一起重建、15 秒内出图”尚无证据。
3. **音频回归驱动**的启动空档缺陷与负偏移 PTS 测量方法（产品侧语义已用真实抓取 DFT 验证）。
4. **Docker / vGPU** 与跨设备音视频组合（按用户已确认范围留待后续）。

## 7. 命令 / Commands

```powershell
# 标准 Windows 入口（本轮已实测可启动到 WEBOBS_DEV_READY，并转发 --soak）
.\scripts\dev.ps1 -Composite -Soak

# 前端与启动器
web\node_modules\.bin\tsc.CMD --noEmit    # 工作目录 web
node --test tests/test-dev-launcher.mjs
node --test tests/test-transcoder-mix.mjs tests/test-transcoder.mjs

# 长稳采样（Windows 侧，读取 WSL 里的后端）
$env:WEBOBS_SCENE_FILE='build\scratch\scene.original.json'
node tests/soak-evidence.mjs --label composite-1080p --mode composite --target-fps 30 --minutes 30

# 浏览器长稳（真实产品页面）。Direct/Hybrid 必须加 WEBOBS_SOAK_PAIR=1：
# 普通 RTSP 需要浏览器配对后的授权令牌，未配对时瓦片会如实显示离线。
$env:WEBOBS_SOAK='1'; $env:WEBOBS_SOAK_MODE='direct'; $env:WEBOBS_SOAK_PAIR='1'; $env:WEBOBS_SOAK_MINUTES='30'
$env:WEBOBS_SOAK_TARGET_FPS_MAP='{"camera-mu2uub8u":20,"camera-mu2uuez4":20,"camera-mu2ux4qk":25,"camera-mu2ux73u":25,"camera-mu2ux99i":15}'
node node_modules/@playwright/test/cli.js test -c <config> --project=chrome -g "feedback-5 soak"

# 音频回归（需先停止开发会话，占用 8554/9997）
node tests/audio-regression.mjs
```

## 8. 结论 / Conclusion

渲染与编码侧已从“软件渲染 + x264”推进到**真实硬件路径**（OBS 渲染滞后 0.0%、编码滞后 0.7%、NVENC 已注册并被选用），并且**原始 1920×1080 五路 Composite 在真实产品页面上连续播放了 30 分钟**，首帧与帧间隔门槛通过。帧率门槛未达标，原因经逐项测量定位到**真实相机来源本身**（7.8–18 fps、HEVC 丢包），不是合成/编码/传输回归。

本轮把帧率门槛的归因彻底做实：**瓶颈不是来源，也不是浏览器，而是 WSL 下 OBS 的 NVENC**。同一场景、同一来源、同一时刻只切换编码器的 A/B 显示 NVENC 24.5 fps、x264 29.6/29.8 fps；浏览器 `getStats()` 显示两条链路都 `packetsLost=0`、`nackCount=0`，NVENC 链路只收到 24.41 fps、x264 链路收到 30.07 fps（解码 30.03、呈现 28.7）。因此**改用 x264 后，即使面对本轮不稳定的真实相机，合成模式的“≥目标 90%”在服务端与浏览器两侧都已达成**；此前 73.2% 的结果应归因于编码器选择。据此启动器在 D3D12 后端 OpenGL 且用户未显式指定时默认 x264，并打印实测理由（显式 nvenc 仍可强制）。

本轮同时定位并修复了两个此前一直阻塞 Direct/Hybrid 验收的产品缺陷：**Direct-only 网关启动即崩溃**（`obs_enum_encoder_types` 在未 `obs_startup` 时被调用）与**未配对被误报为控制面不可达**。修复后 Direct/Hybrid 五路在真实产品页面上连续播放 1787.8 秒（29.8 分钟）且媒体时间全程推进，验收首次真正执行。

F5-01/F5-02 保持既有自动化验证；F5-03 的 OBS 渲染与编码均已在真实运行中启用并取证；F5-04/F5-06 的两种播放模式各 30 分钟验收均已执行，**首帧、帧间隔与帧率三类门槛在真实来源上未全部达标**，逐项测量把瓶颈指向来源侧；F5-05 的批次 A/B/C 代码与单测已完成，端到端音频驱动部分通过。受控故障注入与音频驱动缺陷仍需继续。

This round finally pinned the frame-rate attribution: the limiter is neither the sources nor the browser but OBS NVENC under WSL. An A/B that changed only the encoder on the same scene, sources and moment gave NVENC 24.5 fps against x264 29.6/29.8 fps, while the browser getStats() showed packetsLost=0 and nackCount=0 on both legs: the NVENC leg received 24.41 fps and the x264 leg 30.07 fps (30.03 decoded, 28.7 presented). With x264 the composite acceptance therefore meets the at-least-90-percent threshold on both the server and the browser side even against this round's unstable real cameras, and the earlier 73.2% result is attributable to the encoder choice. The launcher now defaults to x264 when the OpenGL context is D3D12-backed and no encoder was chosen explicitly, printing the measured reason; an explicit nvenc still forces the hardware encoder.

The rendering and encoding side moved from software-only to a real hardware path (0.0% rendering lag, 0.7% encoding lag, NVENC registered and selected), and the original 1920x1080 five-source Composite played for a full 30 minutes inside the real product page with the first-frame and stall thresholds met. The frame-rate threshold is not met, and per-item measurement attributes that to the real camera feeds themselves (7.8-18 fps with HEVC packet loss) rather than to compositing, encoding or transport. This round also located and fixed the two product defects that had been blocking the Direct/Hybrid acceptance all along: the Direct-only gateway crashed on startup (obs_enum_encoder_types called before obs_startup) and an unpaired browser was misreported as an unreachable control plane. With both fixed, the Direct/Hybrid wall played for 1787.8 seconds (29.8 minutes) in the real product page with media time advancing throughout, so that acceptance finally ran. F5-01/F5-02 keep their existing automated verification, F5-03 has OBS rendering and encoding enabled and evidenced in a real run, F5-04/F5-06 have a 30-minute acceptance in each playback mode while the first-frame, stall and frame-rate thresholds are not all met against the real sources (attributed by measurement to the sources), and F5-05 has batches A/B/C implemented with unit tests and a partially passing end-to-end audio driver. Controlled fault injection and the audio-driver defect remain open.
