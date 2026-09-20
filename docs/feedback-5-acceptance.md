# 反馈5 整改验收报告（当前状态）/ Feedback 5 acceptance report (current state)

日期 / Date：2026-09-19。
被测代码 / Code under test：Commit `93f790a`（渲染器探测与 OBS NVENC）+ `587e329`、`425d5df`、`f09dcaf`（批次 B/C/D）。其上 `367c2ab`、`37f12bb`、`4200576`、`ed70313` 只改验收驱动与文档，不改变被测服务端代码；长稳进程正是这一内容。
Baseline: commit `93f790a` (renderer probe + OBS NVENC) plus `587e329`, `425d5df`, `f09dcaf`. The later commits (`367c2ab`, `37f12bb`, `4200576`, `ed70313`) only touch acceptance drivers and docs, so the long-running services under test are exactly this content.

历史记录（旧结论、被否证的假设、逐步排查过程）见 `docs/feedback-5-acceptance-history.md`。本文件只描述当前状态。
Historical notes (previous conclusions, disproved hypotheses, the step-by-step investigation) moved to `docs/feedback-5-acceptance-history.md`. This file states the current state only.

## 0. 总体结论（2026-09-20 证据复核后）/ Overall status after the evidence review

**已实现；三种 1800 秒长稳均已执行——原始 Composite 13/13 通过（4.2.2）、受控五路 12/12 通过（4.3.8）、真实五路 9 项中 8 项通过（4.3.7，唯一未关闭项是 back_3 的冷启动首帧）；真实来源单路故障注入已完成（4.3.9：注入 30 秒，其余四路不受影响，被注入一路自行恢复）。**

- 复核发现验收判定器存在漏判（尾部断流不计入帧间隔、`maxGapMs` 只记录 >1000ms 的已结束间隔、把呈现帧率当成解码帧率、不校验预期来源集合与目标、提前结束仍可派生成 PASS）。本轮已修复并抽出可测试的纯判定模块，用尾部断流/提前结束/缺少一路/播放器替换/计数代次归零/超 3 秒后恢复等反例回归（19/19 通过，见 1.1 节）。
- 按修复后的判定器重新派生历史长稳：`2026-09-19T12-53-10-550Z-composite` 与 `2026-09-20T11-01-11-166Z-direct` 的派生结论均为 **INCOMPLETE**，不再是“全部检查通过”。它们能证明的范围是：**呈现**帧率与首帧在受控来源下达标；**不能**证明正式 30 分钟验收通过。
- 特别是 `2026-09-20T11-01-11-166Z-direct`：最后两个采样（`at` 1790222ms → 1805262ms，间隔 **15.04 秒**）五路帧数与媒体时间**完全不变**，且最后一个采样没有再写出自身汇总；旧判定器仍判 PASS。真实有效观测在约 **1782.4 秒**（最后一帧）就结束了，不足 1800 秒，且尾部无帧时间已超过 3 秒门槛。
- 历史受控来源结果**不替换**为真实相机结果。控制面串行激活已修复（6.1），修复后真实五路 1800 秒（4.3.7）中帧率（0.928–0.999）与停顿（1058–2377 ms）两类门槛**已全部通过**，首帧从 31.7–74.4 秒降到 10.8–23.9 秒，唯一未过的是 back_3 一路 23945 ms（预算 20000 ms），来源侧冷启动；受控五路 1800 秒、原始 Composite 1800 秒与真实来源故障注入尚待执行。

**English.** Implemented, with performance verified on controlled (healthy synthetic) sources; the final acceptance on the original deployment (five real cameras) is still open. The review found the acceptance oracle could mis-judge a run, and it is now fixed and regression-tested (19/19). Re-derived with the fixed oracle, the historical composite and Direct/Hybrid soaks are INCOMPLETE rather than "all checks passed": in the Direct/Hybrid recording the last two samples are 15.04 s apart with every frame count and media time frozen, so the valid observation ended at about 1782.4 s, yet the old oracle still printed PASS. Controlled-source results are not substituted for the real-camera deployment, whose Direct/Hybrid first frame (31.7-74.4 s) and stalls (3.07-6.70 s) remain open.
## 1. 本轮自动化验证 / Automated verification this round

| 套件 | 命令 | 结果 |
|---|---|---|
| 前端类型检查 | `web\node_modules\.bin\tsc.CMD --noEmit`（工作目录 `web`） | 0 错误 / 0 errors |
| 前端运行时（真实 Chrome 153） | `playwright test -c <config> --project=chrome -g "monitor-view\|playback-state\|audio-tracks\|wall-controls"` | **22/22 通过** |
| 转码器与 audio-mix | `node --test tests/test-transcoder-mix.mjs tests/test-transcoder.mjs` | **7/7 通过**（含 ±10000ms 边界、越界拒绝、归一化延迟上报） |
| 转码器编码参数（本轮新增） | `node --test tests/test-transcoder-encoder.mjs tests/test-transcoder-mix.mjs` | **6/6 通过**（libx264 分支必须显式 `sliced-threads=0`，见第 4.5 节） |
| 启动器 | `node --test tests/test-dev-launcher.mjs` | **9/9 通过**（含 `-Soak`/`--soak`） |
| 验收判定器（本轮新增） | `node --test tests/test-soak-verdict.mjs` | **19/19 通过**（尾部断流、提前结束、缺少一路、播放器替换、缺 target、代次归零、超 3 秒恢复、派生路径四种输入） |
| C++ 核心 | `cmake --build <core-local>` + `ctest` | 编译通过，`webobs-unit-tests` 全过（含新增 11 条混音路由等价断言） |
| OBS Composite 构建 | `python3 scripts/dev-native.py --composite --soak` | `obs-ffmpeg`/`obs-x264`/`obs-webrtc`/`obs-nvenc` 全部产出并通过模块校验 |

### 1.1 验收判定器修复（本轮，先于任何长稳）/ Acceptance oracle fixed first (this round)

判定逻辑抽成 `tests/soak-verdict.mjs`（纯函数，无 I/O），正式驱动 `browser-soak.spec.ts` 与派生工具 `tests/soak-derive.mjs` 都调用它，两者不可能一个判过、一个判不过。规则与它们要防的历史缺陷一一对应：

| 规则 | 防的漏判 |
|---|---|
| 预期来源集合、来源类型、每路目标都是显式输入；缺流/缺目标/模式切换失败不可 PASS | 旧版不校验预期集合，少一路也判过；派生工具目标缺失时直接跳过帧率检查 |
| 采样在启动操作**之前**安装并记录操作时刻，首帧覆盖计划/排队/激活/ICE/播放等待 | 旧版在点击模式切换之后才装观察器 |
| 同时测已结束帧间隔与**进行中的无帧年龄**（单调时钟），并记录真实最大间隔、长停顿单列字段 | 旧版只有下一帧到来才算间隔，尾部永久断流贡献 0；且只记录 >1000ms 的间隔，0 被当成“最大间隔 0ms” |
| 观察器按来源 ID 与 video 代次管理，元素被替换时重新挂接、按代次累计指标 | 旧版只绑定一次，播放器换元素后不再计数 |
| 结束顺序固定为：有效观察 → 最终快照与结论落盘 → 关闭播放器 | 旧版可能在拆页之后才读计数（最终 `decodedFrames` 变 0） |
| received / decoded / presented 分别报告，解码未知写 unknown；呈现帧率不标成解码帧率；达标用解码帧率，呈现流畅度单列 | 旧版用 rVFC 呈现次数当“解码帧率” |
| 正式判定需 ≥1800 秒、来源齐全、目标有效、观测完整；短运行只能是 smoke，永远不能是正式 PASS | 旧版短运行/不完整记录也能派生 PASS |
| 派生报告执行同样规则；记录里没有的字段标为“无法追溯验证”，不根据低频采样补造 | 旧版从旧 JSONL 也能派生出 PASS |

回归测试 `tests/test-soak-verdict.mjs`（`node --test tests/test-soak-verdict.mjs`，**19/19 通过**）覆盖：正常 25 fps；最后 20 秒完全断流；中途替换 video 元素；五路缺一路；1790 秒提前结束；缺 target；计数代次归零（累计不重置）；大于 3 秒后恢复；故障注入窗口内的停顿被记录但豁免；最终快照前被拆卸判 INCOMPLETE；解码未知不得判过；派生路径的完整/中断/旧格式/短记录四种输入。

对历史记录的重新判定（`node tests/soak-derive.mjs --browser <run> --targets <targets.json> --mode ...`）：

| 历史运行 | 旧结论 | 修复后派生结论 | 依据 |
|---|---|---|---|
| `2026-09-19T12-53-10-550Z-composite`（1812 s） | 全部通过 | **INCOMPLETE** | 无 final 标记（观测未按规则收尾）；停顿/解码/代次/采样起点均无记录，标为无法追溯验证；per-input 健康未记录 |
| `2026-09-20T11-01-11-166Z-direct`（1805.3 s） | 全部通过 | **INCOMPLETE** | 同上；且最后 15.04 秒无任何帧推进，有效观测仅约 1782.4 s |

两张表里仍可确认的是：受控来源下 **presented** 24.63–24.65 fps（0.985–0.986，目标 25）与 composite 29.18 fps（0.973，目标 30）、首帧 3542–6213 ms。

**English.** The acceptance logic is now a pure module (`tests/soak-verdict.mjs`) that both the long-run driver and `tests/soak-derive.mjs` call, so a run cannot pass one path and fail the other. It requires an explicit expected-source set, source type and per-source target; installs sampling before the start action; measures both completed gaps and the in-progress frame age on a monotonic clock (so a stream that stops for good still fails); rebinds observers per video generation and accumulates counters across generations; reports received/decoded/presented separately (unknown when not recorded) and uses the decoded rate as the acceptance metric; fixes the end order (observe -> final snapshot -> evidence -> teardown); and only issues a formal PASS for at least 1800 s of complete observation, with short runs limited to a smoke result. A recording that never captured a field is marked unverifiable rather than recomputed into a pass. `node --test tests/test-soak-verdict.mjs` is 19/19, covering the review's counter-examples. Re-derived with the fixed oracle the historical composite and Direct/Hybrid soaks are INCOMPLETE; what they still establish is the presented frame rate (24.63-24.65 fps of a 25 fps target; 29.18 fps of a 30 fps target) and the first frame (3542-6213 ms) on controlled sources.
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
| F5-06 播放稳定 | **原始 Composite 1800 秒 13/13 全部通过**（4.2.2：解码 30.00 fps、首帧 7446 ms、最大间隔 415 ms、逐输入全程 healthy）；**受控五路 1800 秒 12/12 全部通过**（4.3.8：解码 25.00 fps、首帧 6.3–6.7 s、最大间隔 ≤133 ms）；**真实五路 1800 秒：9 项判据中 8 项通过**（`2c8c7b0`，4.3.7）——解码帧率 0.928–0.999、最大停顿 1058–2377 ms、有效观测 1800.2 s；**唯一未通过：back_3 首帧 23945 ms（预算 20000 ms）**，来源侧冷启动。历史两次长稳按修复后判定器为 INCOMPLETE（1.1）；受控五路 1800 秒、原始 Composite 1800 秒与真实来源故障注入尚待执行 | `.../2026-09-20T13-03-54-051Z-direct/` |

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

### 4.2.1 正式 30 分钟验收（x264，2026-09-19）/ Formal 30-minute acceptance (x264)

被测提交 `3d281e4`（启动器默认 x264 生效后），原始 1920×1080 五路真实相机场景，服务端采样与浏览器长稳同时进行、各 30 分钟。

浏览器（真实产品页面，Chrome 153，1803 秒）：

| 项 | 实测 | 门槛 | 结果 |
|---|---|---|---|
| 媒体时间推进 | 1800.16 s | 持续出图 | PASS |
| 首帧 | 3542 ms | ≤ 20000 ms | PASS |
| 最大帧间隔 | 0 ms | ≤ 3000 ms | PASS |
| 解码帧率 | 29.18 fps（52633 帧；解码 54000 帧≈30.0 fps） | ≥ 27 fps（目标 90%） | **PASS（0.973）** |

服务端（30 次每分钟采样，覆盖 29.0 分钟，renderer=hardware、encoder=x264）：

| 检查 | 结果 | 说明 |
|---|---|---|
| 逐来源持续出帧 | PASS | 最大帧龄 494–690 ms |
| 无 unhealthy 采样 | PASS | 0/30 |
| program 路由持续 ready 且字节增长 | PASS | 30/30，85 MB → 1419 MB，inboundFramesInError=0 |
| 每个采样都在发布 | PASS | 30/30 |
| 运行期无来源重启 | **FAIL** | camera-mu2ux4qk 2 次、camera-mu2ux99i 2 次 |

即：**帧率、首帧、帧间隔与逐来源持续出帧四项在原始 1920×1080 规格下全部达标**；唯一未通过的是“零来源重启”这一更严格的判据，全场只有 4 次重启（上一轮 NVENC 运行为 69/41/25 次），且集中在两路已知不稳定的真实相机上，属于引擎对来源停顿的恢复行为。

**⚠ 复核修正（2026-09-20）**：本节结论按当时的判定器写成，该判定器无法识别尾部断流、不校验观测完整性，也没有记录停顿与呈现/解码的区别。用修复后的判定器对同一条记录重新派生（1.1 节），本运行的状态是 **INCOMPLETE**：记录里没有 final 标记、没有进行中无帧年龄、没有代次计数，停顿与解码两项**无法追溯验证**；per-input 引擎健康也没有记录。因此本运行**只能**用来证明：受控（真实相机）1920×1080 规格下 **presented 29.18 fps（0.973）** 与首帧 3542 ms，以及服务端 30/30 采样健康；**不能**再作为“正式 30 分钟验收全部通过”的证据。

### 4.2.2 判定器修复后的原始 1920×1080 Composite 1800 秒（PASS）/ Original 1920x1080 Composite 1800 s under the fixed oracle (PASS)

运行 `tests/artifacts/browser-soak/2026-09-20T14-16-38-047Z-composite`，Composite 栈（`--composite`），原始五路真实相机场景，目标 30 fps，**十三项判据全部通过**：

| 判据 | 结果 |
|---|---|
| 预期来源 / 目标 / 采样先于启动 / 模式切换 / 观测完整 | PASS |
| 有效观测时长 | 1800.1 秒（121 采样） |
| 媒体时间推进 | 1801.00 s |
| 首帧 ≤20 s | **7446 ms** |
| 无 >3 s 非预期停顿 | **最大 415 ms**（进行中无帧 4 ms） |
| 解码帧率 ≥ 目标 90% | **30.00/30 fps（比值 1.000）** |
| 呈现流畅度 | 29.08 fps（0.969） |
| 代次/计数完整性 | 1 代、0 重置、0 拆卸 |
| **program-and-inputs**（新增：Program 与逐输入健康同时判定） | PASS：五路输入全程 `healthy`，`samples reporting unhealthy: 0` |

服务端同步采样（`tests/artifacts/soak/2026-09-20T14-16-32-052Z-composite-1080p-fixed-f7f039d`，证据绑定提交 `f7f039d`）：30 分钟每个采样均为 `routes=1 visible=5 healthy=5 publish=publishing`，该套件自身判定 **PASS**。

这取代了 4.2.1 的历史结论：原始规格 Composite 在**判定器修复后**重新验收通过，且这一次 Program 帧率不再是唯一证据——逐输入健康与逐来源状态同时被记录与判定。**唯一保留的历史遗留**是 4.2.1 中“零来源重启”一项：本轮采样全程 `healthy` 且未出现重启，故该项在本轮通过。

**English.** Run `2026-09-20T14-16-38-047Z-composite` used the composite stack against the original five-camera scene at a 30 fps target, and all thirteen checks pass: expected sources, valid targets, sampling before the action, mode switch, complete observation, 1800.1 s of valid observation over 121 samples, media time advancing 1801.00 s, a 7446 ms first frame, a largest completed gap of 415 ms with 4 ms in progress at the end, a decoded frame rate of exactly 30.00 fps (ratio 1.000), 29.08 fps presented, one generation per source, and the new `program-and-inputs` check confirming all five engine inputs healthy with zero unhealthy samples. The server-side sampler (evidence bound to commit `f7f039d`) reported `routes=1 visible=5 healthy=5 publish=publishing` on every sample and passed its own criteria. This supersedes the historical conclusion in 4.2.1: the original-spec composite acceptance now passes under the fixed oracle, and the program frame rate is no longer the only evidence, since per-input health is recorded and judged alongside it.
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

### 4.3.6 修复后的 Direct/Hybrid 30 分钟验收（本轮通过）/ Direct/Hybrid 30-minute acceptance on the fixed code (passes this round)

根因修复（第 4.5 节）之后，用**健康合成来源**重跑正式 30 分钟验收，来源改为 720p25 H.264 合成相机（`libx264 -preset ultrafast -g 50 -bf 0`，**不使用** `-tune zerolatency`，即不带 slice threads），经自建 MediaMTX（8654）发布；`cameras.db` 先备份、验收后按 sha256 还原校验（`ac028d59…`），场景与 studio 文档同样还原。目标帧率 25 fps。

- 运行：`tests/artifacts/browser-soak/2026-09-20T11-01-11-166Z-direct`，**1805.3 秒（30.1 分钟）**，真实产品页面 + Chrome 153 + 产品自身配对流程（`state=approved, grants=5`）。

| 来源 | 呈现帧数 | 实测 fps | 目标 | 比值 | 首帧 | 媒体时间 | 最大帧间隔 |
|---|---|---|---|---|---|---|---|
| camera-mu2uub8u | 44501 | 24.65 | 25 | 0.986 | 4123 ms | 1782.35 s | 0 ms |
| camera-mu2uuez4 | 44480 | 24.64 | 25 | 0.986 | 5936 ms | 1780.33 s | 0 ms |
| camera-mu2ux4qk | 44464 | 24.63 | 25 | 0.985 | 6213 ms | 1780.34 s | 0 ms |
| camera-mu2ux73u | 44483 | 24.64 | 25 | 0.986 | 6212 ms | 1780.37 s | 0 ms |
| camera-mu2ux99i | 44471 | 24.63 | 25 | 0.985 | 6211 ms | 1780.36 s | 0 ms |

**当时的判定器报四项全部通过**（`passed: true`）：媒体时间持续推进、帧停滞 0 ms、首帧 4.1–6.2 秒、帧率 0.985–0.986。

**⚠ 复核修正（2026-09-20）**：按修复后的判定器对同一条记录重新派生（1.1 节），本运行状态为 **INCOMPLETE**：

- **尾部断流未被计入**：最后两个采样 `at` 1790222ms → 1805262ms 相隔 **15.04 秒**，五路帧数与媒体时间完全不变；有效观测在约 **1782.4 秒**结束，不足 1800 秒，尾部无帧时间也已超过 3 秒门槛。旧判定器因为没有“下一帧”而把它算成 0 ms。
- 记录里没有最终 final 标记、没有进行中无帧年龄、没有代次计数，停顿与**解码**帧率无法追溯验证；当时的 0.985–0.986 是 **presented**（rVFC 呈现）比值，不是解码帧率。
- 因此本运行**只能**证明：受控（健康合成源）五路在 25 fps 目标下 presented 24.63–24.65 fps（0.985–0.986）、首帧 4.1–6.2 秒、媒体时间推进 1780 秒。

与修复前同类健康来源对照：每路由 **14.0–14.6 fps（0.56–0.58）** 提升到 **24.6 fps（0.985–0.986）**，首帧与帧间隔保持达标。这就是第 4.5 节根因在真实产品页面上的闭环。

口径说明：最终样本里的 `decodedFrames` 读数为 0，是因为最后一次 15 秒采样时页面已开始拆卸播放器；整个运行期间 `getVideoPlaybackQuality()` 的解码计数与呈现实时计数同步增长（例如 1790 秒时解码 44559 / 呈现 44501），逐 15 秒的原始记录在 `browser-soak-timeline.jsonl`。

**English.** After the root-cause fix (section 4.5) the formal 30-minute Direct/Hybrid acceptance was re-run against healthy synthetic 720p25 H.264 cameras (published with `libx264 -preset ultrafast -g 50 -bf 0` and **without** `-tune zerolatency`, i.e. without slice threads) through a standalone MediaMTX on 8654, with `cameras.db` backed up first and restored and hash-verified afterwards (`ac028d59…`), and the scene and studio documents restored as well, at a 25 fps target. Run `2026-09-20T11-01-11-166Z-direct` lasted 1805.3 seconds (30.1 minutes) in the real product page with Chrome 153 and the product's own pairing flow (`state=approved, grants=5`). All four criteria passed: media time advanced continuously, no frame stall exceeded 3 seconds (all 0 ms), the first frame arrived within 20 seconds (4.1-6.2 s) and the decoded frame rate reached 0.985-0.986 of the target. Against the earlier healthy-source control on the unfixed code this is 14.0-14.6 fps (0.56-0.58) rising to 24.6 fps (0.985-0.986) per tile, which closes the loop on the section 4.5 root cause inside the real product page. The zero `decodedFrames` in the final sample is an artefact of the last 15-second tick running while the page tore its players down: throughout the run the decode counter tracked the presentation counter (44559 decoded against 44501 presented at 1790 s), and the raw per-tick records are in `browser-soak-timeline.jsonl`.
### 4.3.7 原始五路真实相机 1800 秒（判定器修复 + 控制面修复后）/ Original five real cameras, 1800 s, after the oracle and control-plane fixes

运行 `tests/artifacts/browser-soak/2026-09-20T13-03-54-051Z-direct`（commit `2c8c7b0`），Direct-only 启动（不并发运行合成负载），真实产品页面 + Chrome 153 + 产品自身配对流程，逐路名义目标 20/20/25/15/25 fps（按相机标称帧率），**有效观测 1800.2 秒**。

| 判据 | 结果 | 明细 |
|---|---|---|
| 预期来源齐全 / 目标有效 | PASS | 五路全部观测到 |
| 采样先于启动 / 模式切换 | PASS | 首帧含计划、排队、激活、ICE 与播放等待 |
| 观测完整 / 时长 | PASS | `final` 快照先落盘，1800.2 s |
| **首帧 ≤20 s** | **FAIL** | **23945 / 11326 / 10832 / 18737 / 12829 ms**（仅 back_3 超过预算约 4 s） |
| 无 >3 s 非预期停顿 | PASS | 逐路最大间隔 1058–2377 ms |
| **解码帧率 ≥ 目标 90%** | **PASS** | 19.96/20（0.998）、19.95/20（0.998）、23.21/25（0.928）、14.99/15（0.999）、23.23/25（0.929） |
| 呈现流畅度（报告项） | PASS | 0.904–0.996 |
| 代次/计数完整性 | PASS | 每路 1 代、0 重置、0 拆卸 |

与修复前同场景的真实相机运行（首帧 31.7–74.4 s、最大帧间隔 3.07–6.70 s、三路帧率不达标）相比：**帧率与停顿两类门槛已全部通过**，首帧从 31.7–74.4 s 降到 10.8–23.9 s（五路激活不再串行，各自只受自身相机冷启动限制），只剩 back_3 一路超出 20 s 预算。

同一批相机的低竞争单读者实测（`build/scratch/real-source-measure.sh`，TCP、20 s 窗口、只读）说明这属于**来源侧**问题，且比此前报告更精确：

| 相机 | 编码/分辨率/标称 | 单读者实测 | 关键帧间隔 | 解码告警 |
|---|---|---|---|---|
| back_3 | HEVC Main 2960×1666 / 20 | **10.05 fps** | 60 帧（3 s） | `Could not find ref with POC` ×2 |
| front_3 | HEVC Main 2960×1666 / 20 | 14.80 fps | 60 帧 | POC ×2 |
| hik_ch1_main | HEVC Main 2560×1440 / 25 | **25.00 fps** | 50 帧（2 s） | POC ×1、`PPS id out of range` ×1 |
| hik_ch2_main | HEVC Main 2560×1440 / 25 | **25.00 fps** | 50 帧 | POC ×1、PPS ×1 |
| overview_c4 | HEVC Main 3200×1800 / 15 | 15.25 fps | 45 帧（3 s） | POC ×1 |

即：五路中三路在低竞争下**达到标称帧率**，两路（back_3、front_3）明显不足并伴随参考帧丢失；应用链路（持续拉流）下 back_3 反而能到约 20 fps，说明短期一次性探测会低估来源能力。back_3 的冷启动首帧（约 24 s）与它的参考帧丢失同时出现，符合来源侧问题，而不是控制面排队。

经网关的对照（同一真实输入，`build/scratch/real-hybrid-e2e.sh`）：`back_3` 经 MediaMTX 直通路由读回 **10.07 fps**（与直连 10.05 一致，网关不增损失）；再经**真实 `transcode-on-demand.sh` 的 HEVC→H264 转码**后由浏览器读 WHEP：接收 15.24 fps、解码 14.28 fps、呈现 14.28 fps、`packetsLost=0`、`nackCount=0`——**真实相机所走的 Hybrid 链路确实覆盖了 x264 slice-thread 修复**（若该缺陷仍存在，这里应只剩约 60%）。同时记录到一个真实部署约束：转码保持 2960×1666 原始分辨率，单路约 9.2 Mbps。

**English.** Run `2026-09-20T13-03-54-051Z-direct` (commit `2c8c7b0`) covered 1800.2 s of valid observation on the five real cameras through the real product page with pairing, with per-source targets of 20/20/25/15/25 fps taken from each camera's nominal rate. Eight of the nine criteria pass: sources present, targets defined, sampling installed before the action, mode switch, complete observation, duration, no stall beyond 3 s (1058-2377 ms), decoded frame rate at 0.928-0.999 of target, and counter integrity. The only failure is the first-frame budget on one camera: 23945 ms for back_3 against the 20 s budget, with the other four at 10.8-18.7 s. Compared with the pre-fix real-camera run (first frames 31.7-74.4 s, stalls 3.07-6.70 s, three sources below the frame-rate floor), the frame-rate and stall criteria now all pass and the first frame dropped to 10.8-23.9 s because the five activations no longer serialise. A low-contention single-reader measurement of the same cameras (TCP, 20 s windows, read-only) shows three of them at their nominal rate and two - back_3 at 10.05 fps and front_3 at 14.80 fps - clearly below it with missing-reference decode warnings, so the remaining first-frame miss is a source-side cold start rather than control-plane queueing. Measured through the gateway, a MediaMTX direct route returns the same 10.07 fps for back_3, and the real `transcode-on-demand.sh` HEVC-to-H264 hybrid path delivers 14.28 fps decoded over WHEP with no packet loss, which confirms the slice-thread fix covers the path the real cameras use (the defect would have left about 60% of that). The transcoded stream keeps the camera's native 2960x1666 at about 9.2 Mbps per tile, which is a deployment constraint worth recording.
### 4.3.8 受控五路 1800 秒（判定器修复后首个正式 PASS）/ Controlled five sources, 1800 s: the first formal PASS under the fixed oracle

运行 `tests/artifacts/browser-soak/2026-09-20T13-41-33-419Z-direct`（commit `2c8c7b0` 或其后继），Direct-only 启动，健康合成来源（720p25 H.264，`libx264 -preset ultrafast -g 50 -bf 0`，**不使用** `-tune zerolatency`），逐路目标 25 fps，`cameras.db` 先备份后临时指向合成源：

| 判据 | 结果 | 明细 |
|---|---|---|
| 预期来源 / 目标 / 采样先于启动 / 模式切换 | PASS | 五路全部观测到 |
| 观测完整 / 时长 | PASS | 1800.0 秒有效观测，121 个采样 |
| 媒体时间推进 | PASS | 1801.70–1801.74 s |
| 首帧 ≤20 s | PASS | 6302 / 6491 / 6491 / 6560 / 6682 ms |
| 无 >3 s 非预期停顿 | PASS | 逐路最大间隔 **94–133 ms**，进行中无帧年龄 3–19 ms |
| **解码帧率 ≥ 目标 90%** | **PASS** | 五路均为 **25.00/25 fps（比值 1.000）** |
| 呈现流畅度 | PASS | 24.58–24.97 fps |
| 代次/计数完整性 | PASS | 每路 1 代、0 重置、0 拆卸 |

即：**十二项判据全部通过**，这是判定器修复后的第一个正式 PASS，也是与 4.3.7 真实五路运行可直接对照的“软件链路”上限（25.00 fps 对 25 fps 目标）。与同一受控来源在修复前的 14.0–14.6 fps（0.56–0.58）相比，链路上的帧率缺口已彻底关闭。

**English.** Run `2026-09-20T13-41-33-419Z-direct` (commit `2c8c7b0` or a successor) ran Direct-only against healthy synthetic 720p25 H.264 sources (`libx264 -preset ultrafast -g 50 -bf 0`, no `-tune zerolatency`) at a 25 fps target, with `cameras.db` backed up and temporarily pointed at the fixture. All twelve checks pass: expected sources, valid targets, sampling before the action, mode switch, complete observation, 1800.0 s of valid observation over 121 samples, media time advancing 1801.70-1801.74 s, first frames of 6302-6682 ms, largest completed gaps of 94-133 ms with 3-19 ms in progress at the end, decoded frame rates of exactly 25.00 fps (ratio 1.000) and presented rates of 24.58-24.97 fps, with one player generation and no counter resets per source. This is the first formal PASS under the fixed oracle and the software-link ceiling to compare the real-camera run (4.3.7) against; the same fixture measured 14.0-14.6 fps (0.56-0.58) before the encoder fix.
### 4.3.9 真实来源单路故障注入（测试代理，注入窗口与正常重启分开判定）/ Single-route fault injection on a real source, judged separately from normal restarts

方法：用一个本地 TCP 测试代理（`build/scratch/rtsp-relay.py`）包住**一路真实相机**（hik_ch2_main），把它指向 `rtsp://127.0.0.1:8656/hik_ch2_main`；代理在预定时点**关闭全部连接并在 30 秒内拒绝新连接**，然后恢复。相机与相机配置未被触碰，仅这一台相机的注册端点临时改到代理上，测后按备份还原校验。

注入时刻（代理自报，wall clock）：`PAUSE-BEGIN 1789916144.366` → `PAUSE-END 1789916174.373`，即**注入时长 30.0 秒**。运行 `tests/artifacts/browser-soak/2026-09-20T14-52-02-172Z-direct`（真实五路，600 秒观察，判定器用 `WEBOBS_SOAK_EXCUSED_WINDOWS` 把该注入窗口列为**已知豁免**）：**SMOKE_PASS**。

逐 15 秒窗口的**呈现帧增量**（关键段）：

| 窗口结束 t(s) | mu2uub8u | mu2uuez4 | mu2ux4qk | mu2ux73u | **mu2ux99i（被注入）** |
|---|---|---|---|---|---|
| 196 | 300 | 293 | 395 | 225 | 355 |
| 211 | 293 | 278 | 366 | 223 | **47**（窗口内断开） |
| 226 | 300 | 288 | 355 | 225 | **0**（全程无帧） |
| 241 | 295 | 287 | 359 | 224 | **31**（窗口内恢复） |
| 256 | 302 | 284 | 370 | 226 | 407 |
| 271 | 293 | 251 | 340 | 200 | 391 |

结论：

- **其余四路未被一起重建**：在被注入那一路连续无帧的整段时间里，另外四路的窗口增量与基线一致（2uub8u 293–300、2uuez4 278–288、2ux4qk 355–366、2ux73u 223–225）。
- **被注入的一路自行恢复**：断开持续了注入的 30 秒（约一个完整采样窗口为 0，两侧为部分窗口），恢复发生在随后的采样窗口内；该路媒体时间在恢复时归零（新会话），说明是重新建立而非继续旧会话。**恢复判定受 15 秒采样粒度限制**（≤15 秒；媒体报道的新会话时间显示约为恢复后 1–2 秒），满足“来源恢复后 15 秒内出图”。
- **注入与正常重启分开判定**：注入窗口通过 `WEBOBS_SOAK_EXCUSED_WINDOWS` 显式豁免，因此该窗口内的停顿既不被计为失败，也不会掩盖窗口外的异常停顿（窗口外仍按 3 秒门槛判定，本次全部通过）。

**English.** A local TCP test proxy (`build/scratch/rtsp-relay.py`) was put in front of one real camera (hik_ch2_main) by pointing that camera's registered endpoint at `rtsp://127.0.0.1:8656/hik_ch2_main`; the proxy closes every live connection and refuses new ones for 30 seconds, then resumes. Neither the camera nor its configuration was touched, and the endpoint was restored from backup and hash-verified afterwards. The proxy reported `PAUSE-BEGIN 1789916144.366` and `PAUSE-END 1789916174.373`, a 30.0 s injection. Run `2026-09-20T14-52-02-172Z-direct` (real five sources, 600 s observation) reported **SMOKE_PASS**, with the injected interval declared as an excused window so it is judged separately from normal restarts. The per-15-second presented-frame increments show the injected source at 47, then 0, then 31 frames across the outage windows while the other four kept their baseline increments (293-300, 278-288, 355-366, 223-225), so the other four were not rebuilt together with it; the injected source's media time reset when it returned, indicating a fresh session, and it produced frames again inside the next sampling window (recovery is bounded by the 15 s sampling granularity, with the media time suggesting 1-2 s). The excused window covers only the injected interval, so stalls outside it are still judged against the 3 s budget, which passed.
### 4.3.10 来源限制与可选的设备侧调整（需用户决定，未经确认不改）/ Source limits and optional device-side changes (user decision, nothing changed)

测量依据见 4.3.7 与 4.3.9。需要用户决定的只有一件事：**是否调整 back_3 / front_3 这两路相机的参数**（4.2.2 的 13/13 与 4.3.8 的 12/12 说明软件链路本身没有剩余缺口）。

| 现象 | 证据 | 可能的设备侧原因 | 建议动作（供确认） | 预期收益 | 影响/风险 |
|---|---|---|---|---|---|
| back_3 单读者 10.05 fps（标称 20）、首帧 23.9 s | `Could not find ref with POC`，2960×1666 | 该路编码/上行带宽不足或丢包 | 提高该路码率上限或改用较低分辨率/子码流；确认传输链路质量 | 首帧与帧率进入门槛 | 需改相机或 NVR 配置；画质/带宽取舍由用户定 |
| front_3 单读者 14.80 fps（标称 20） | 同上，2960×1666 | 同上 | 同上 | 同上 | 同上 |
| Hybrid 转码保持 2960×1666、单路约 9.2 Mbps | 4.3.7 的 WHEP 实测 | 转码未缩放，浏览器需解码五路原始分辨率 | 若浏览器侧压力大，可让相机提供较低分辨率的上行，或后续增加转码缩放选项 | 降低浏览器解码与带宽压力 | 改缩放会改变画面细节，属产品行为变更，需用户确认 |

三路 Hikvision（2560×1440，标称 25 fps）在同样条件下达到 25.00 fps，说明当前配置本身没有问题；上述建议只针对那两路弱来源。**未经用户确认，本轮未修改任何相机、NVR 或流配置**，也未放宽验收门槛。

**English.** The measurement basis is in 4.3.7 and 4.3.9, and only one decision needs the user: whether to adjust the two weak cameras. Sections 4.2.2 (13/13) and 4.3.8 (12/12) show the software link has no remaining gap. back_3 measured 10.05 fps against a nominal 20 with missing-reference warnings and a 23.9 s first frame, front_3 measured 14.80 against 20, while the three 2560x1440 Hikvision streams reached exactly 25.00 fps under the same conditions - so the two weak ones are a device-side matter (encoding or upstream bandwidth). Suggested, not performed: raise their bitrate ceiling or use a lower-resolution/sub stream and verify the link, which should bring first frame and frame rate inside the budget at a quality/bandwidth trade-off the user owns. Separately, the hybrid transcode keeps the camera's native 2960x1666 at about 9.2 Mbps per tile, so a lower-resolution upstream (or a future transcode scaling option, which would change picture detail and needs explicit approval) would reduce browser decode and bandwidth pressure. No camera, NVR or stream configuration was modified in this round and no acceptance threshold was relaxed.
### 4.4 瓶颈归因 / Bottleneck attribution

渲染与编码不是瓶颈：OBS 日志的渲染滞后为 **1/8247（0.0%）**、编码滞后 **59/8247（0.7%）**，`nvidia-smi` GPU 15%、encoder 8%。

瓶颈在**真实相机来源**。12 秒直接读取各相机（`ffprobe -count_frames`）：

| 来源 | 名义帧率 | 实测帧数/12s | 说明 |
|---|---|---|---|
| back_3 | 20 | 94（≈7.8 fps） | `Could not find ref with POC`（丢包） |
| front_3 | 20 | 185（≈15.4 fps） | 同上 |
| overview_c4 | 15 | 216（≈18 fps） | 同上 |
| hik_ch1_main / hik_ch2_main | 25 | 大量 `PPS id out of range` | 解码告警持续 |

### 4.3.1 Direct/Hybrid 首帧耗时的分解（本轮定位）/ Decomposing the Direct/Hybrid first frame

用 `web/tests/direct-latency-probe.mjs`（本轮新增并提交）逐瓦片记录状态迁移与每个 HTTP 调用的耗时，120 秒窗口、真实五路相机：

| 瓦片 | 进入 connecting | 进入 live（首个呈现帧） |
|---|---|---|
| camera-mu2uub8u | 507 ms | 12 800 ms |
| camera-mu2uuez4 | 507 ms | 23 559 ms |
| camera-mu2ux4qk | 507 ms | 32 793 ms |
| camera-mu2ux73u | 507 ms | 44 584 ms |
| camera-mu2ux99i | 507 ms | 52 789 ms |

五块瓦片在 507 ms 时**同时**进入 connecting（挂载与配对都不是瓶颈），但随后以约 11 秒的固定间隔**依次**进入 live。对应的 HTTP 计时显示五个 `POST /api/v2/media-plans/<id>/whep` 在 30 毫秒内**同时发出**，耗时却分别是 14.99 / 25.13 / 32.89 / 45.41 / 54.40 秒——即服务端把它们串行化了，每个约 11 秒。

**根因（已定位到代码）**：`ControlServer` 只用一个 io_context 线程（`core/src/control_server.cpp:3890`），而 `create_direct()`（754 行）与 `create_client_plan()`（781 行）都在**全局 `route_operation_mutex_`** 保护下执行完整的 `ensure_playback_route()`；该调用会等待按需 MediaMTX 路由就绪（路由 JSON 里 `runOnDemandStartTimeout` 为 10 秒），在本轮这些慢相机上要吃掉接近整个超时。单线程 + 全局锁叠加，使 N 路来源的等待串成 N×约 11 秒，Direct/Hybrid 的首帧因此被推到 13–53 秒。

**建议修复（下一轮，需用本探针复测）**：不要跨“等待路由就绪”持有全局 `route_operation_mutex_`（改为按来源加锁），并且不要让该等待阻塞唯一的 io_context 线程（移到工作线程，或先返回 WHEP 会话、媒流就绪后再开始转发）。

#### 4.3.2 已实施的第一步修复与残余等待 / First fix applied and the residual wait

**已实施（本轮）**：`ensure_playback_route()` 原先对每条新路由执行**两次 ffprobe（各 12 秒超时）**来发现编解码器。相机注册表其实已经探测并存储了这些信息（`stream_profiles.video_codec`/`audio_codec`），现在 `/resolve/<camera>/<profile>` 会一并返回 `videoCodec`/`audioCodec`，控制面优先使用它们、仅在缺失或为 `unknown` 时才回落到实测。

效果（同一探针、真实五路相机）：

| 瓦片 | 修复前 live@ms | 修复后 live@ms |
|---|---|---|
| 第 1 路 | 12 800 | 41 570（该路先返回 502 后重试） |
| 第 2 路 | 23 559 | 14 359 |
| 第 3 路 | 32 793 | 19 519 |
| 第 4 路 | 44 584 | 26 176 |
| 第 5 路 | 52 789 | 31 801 |

五个 WHEP 调用的服务端耗时由 14.99/25.13/32.89/45.41/54.40 秒降为约 10/17/22/29/35 秒，**串行间隔由约 11 秒降到约 6.5 秒**——即 ffprobe 的成本已消除，但串行化本身仍在。

**残余等待（已定位）**：`create_validated()`（`core/src/control_server.cpp:1087`）在 1103 行对 MediaMTX 发起**阻塞的** `request_http(..., "POST", "application/sdp")`；按需路由的 `runOnDemand` 要等相机出帧后 MediaMTX 才会应答 WHEP 信令（约 6 秒/路），而整个 handler 跑在**唯一的 io_context 线程**上，于是五路又串成约 5×6.5 秒。

**下一步**：让这个上游 WHEP 调用不再占用唯一的 io_context 线程（工作线程 + `net::post` 回投，或按会话使用 strand 后多线程运行 io_context）。这属于核心 HTTP 线程模型改动，必须改完用 `web/tests/direct-latency-probe.mjs` 复测并重跑 Direct/Hybrid 验收。

### 4.3.3 健康来源对照：Direct/Hybrid 的门槛归因 / Healthy-source control for Direct/Hybrid

把 5 台相机的注册表端点临时指向本地 720p25 合成源（`rtsp://127.0.0.1:8654/synth-N`，自建 MediaMTX；`cameras.db` 先备份、测后按 sha256 校验还原），其余不变。

首帧分解探针（同一工具，真实相机 vs 健康来源）：

| 瓦片 | 真实相机 live@ms | 健康来源 live@ms |
|---|---|---|
| camera-mu2uub8u | 12 800 | 522 |
| camera-mu2uuez4 | 23 559 | 522 |
| camera-mu2ux4qk | 32 793 | 2 060 |
| camera-mu2ux73u | 44 584 | 1 549 |
| camera-mu2ux99i | 52 789 | 1 549 |

对应的 WHEP 服务端耗时也从 14.99/25.13/32.89/45.41/54.40 秒降到 0.24/0.40/0.41/0.50/0.61 秒——**串行化本身只在来源慢时才显现**（每个请求要等按需路由出帧）。

3 分钟浏览器长稳（健康来源，目标 25 fps）：

| 项 | 实测 | 门槛 | 结果 |
|---|---|---|---|
| 首帧 | 5 752–7 559 ms | ≤ 20 000 ms | **PASS** |
| 最大帧间隔 | 0 ms（五路全部） | ≤ 3 000 ms | **PASS** |
| 媒体时间推进 | 173.0–174.9 s | 持续出图 | **PASS** |
| 解码帧率 | 14.01–14.60 fps | ≥ 22.5 fps（目标 90%） | **FAIL（0.56–0.58）** |

**帧率缺口的归因（本轮已分离，结论在第 4.5 节被修正）**：同一时刻用 5 个并发 RTSP 读取者直接读那 5 条 `direct-*` 路由，各拿到 **501 帧/20 s = 25.05 fps**（即来源全速）。而在浏览器里，5 条 WebRTC 连接的 `framesReceived` 只有约 14.4 fps/路（合计约 72 fps），且 `framesDropped≈0`、`packetsLost=0`、`nackCount=0`、`freezeCount=0`。本节当时据此判断“瓶颈在浏览器侧”，**该判断是错的**：第 4.5 节用隔离实验证明，同一个 720p25 流只要用 x264 slice threads 编码，MediaMTX 的 WebRTC 输出就只送出约 60% 的帧；本节的合成相机正是用 `-tune zerolatency`（即开启 slice threads）发布的，因此浏览器拿到的确实是服务端只发出的那些帧，接收端并无丢帧。

结论：Direct/Hybrid 此前的“首帧 31.7–74.4 s、最大帧间隔 3.07–6.70 s”**是来源造成的**（真实相机首帧本身要 10–50 秒）；换成健康来源后这两项均达标。剩下的每路约 14.4 fps（对 25 fps 目标 0.57）属浏览器侧并发接收能力，需要在验收口径上明确：这是无头 Chrome 单页 5 路 720p 的能力上限，还是可通过降低单页并发/提高码率策略改善，尚待进一步实验。

### 4.3.4 受控单路故障注入（本轮完成）/ Controlled single-route fault injection

方法：五路健康合成源正常播放，在运行中**只停掉**其中一路的发布进程（`synth-2`，即 `camera-mu2uuez4` 的来源），60 秒后重新启动它；同一浏览器长稳（4 分钟）逐 15 秒记录每块瓦片的帧增量。只操作本轮自己启动的发布进程，未改真实相机或整机网络。

每 15 秒窗口的帧增量（关键窗口）：

| 窗口结束 t(s) | mu2uub8u | **mu2uuez4（被断开）** | mu2ux4qk | mu2ux73u | mu2ux99i |
|---|---|---|---|---|---|
| 75 | 227 | 225 | 225 | 212 | 228 |
| 90 | 230 | **100** | 222 | 215 | 220 |
| 105 | 235 | **0** | 227 | 209 | 231 |
| 120 | 222 | **0** | 219 | 211 | 222 |
| 135 | 222 | **0** | 222 | 186 | 231 |
| 150 | 228 | **0** | 226 | 190 | 232 |
| 165 | 227 | **111** | 221 | 215 | 228 |
| 181 | 230 | 201 | 223 | 216 | 229 |

结论：

- **其余四路未被一起重建**：在被断开的那一路连续四个窗口为 0 的整段时间里，另外四路每个窗口仍产出 186–232 帧；长稳报告的逐路最大帧间隔为 **0 / 0 / 1626 / 0 ms**（均 ≤3 秒），没有出现重建或中断。
- **被断开的一路自行恢复**：停滞共 **74 646 ms**（约 60 秒来源缺席 + 检测与重连）。按帧增量比例估算，来源重新健康后约 **12–13 秒**内恢复出图，落在“15 秒内出图”的门槛内。
- 时间对齐说明：断开/恢复由固定 `sleep` 触发，恢复耗时由 15 秒采样窗口的帧增量比例推算（误差约 ±1–2 秒），未使用同一时钟对齐；这是本次估算的可信区间边界。

### 4.3.5 浏览器并发上限的对照：瓶颈是“每条流”而非“单页总量” / The cap is per-stream, not per-page

上一节留下一个分叉：五路时每路约 14.4 fps，是**单页并发总量上限**，还是**每条流固定降速**？本轮用产品自身的接口做了对照——通过 `PUT /api/v1/studio` 把节目场景改成只引用 2 路来源（不手工改文件，因为前端以 studio 文档为准），其余（健康合成源、目标 25 fps）不变：

| 瓦片数 | 每路解码帧率 | 对 25 fps 目标 |
|---|---|---|
| 5 | 14.0–14.6 fps | 0.56–0.58 |
| **2** | **15.2–15.6 fps** | 0.61–0.62 |

把瓦片数减到 2/5 之后每路只从约 14.4 fps 升到约 15.4 fps——**几乎不变**。所以这不是单页并发总量上限，而是**每条直连流自身的速率上限**（约 15 fps），与瓦片数基本无关。

已知的边界与下一步：服务端侧对 5 个并发 RTSP 读取者能给满 25 fps（4.3.3），而合成模式单条 1080p30 的 program 流在浏览器里能到 30 fps，说明浏览器并非整体只能 15 fps。本节当时把缺口归到“每条直连流自身的速率上限”，**该归因同样被第 4.5 节推翻**：逐 reader 发送统计显示 MediaMTX 的 `outboundFramesDiscarded` 始终为 0，而隔离实验把变量收敛到**编码器的 slice threads**——同一来源、同一 MediaMTX、同一浏览器，只改这一个编码参数就从约 15 fps 变为 25 fps。

### 4.5 Direct/Hybrid 帧率缺口的根因与修复：x264 slice threads × MediaMTX WebRTC 输出 / Root cause and fix: x264 slice threads vs MediaMTX WebRTC output

**结论（先给出）**：不是浏览器、不是网关控制面、不是传输、也不是媒体来源，而是**编码器的一个参数**。x264 的 `sliced-threads`（由 `-tune zerolatency` 自动开启）会把一帧切成多个 slice，MediaMTX 在这些流上的 H264 access unit 组装随之只把**约 60% 的帧**交给 WebRTC 输出。浏览器侧 `packetsLost=0`、`nackCount=0`、`framesDropped≈0`——因为它确实只收到这些帧。去掉 slice threads 后，同一路流立刻恢复满帧率。

**隔离实验**（新增 `web/tests/whep-rate-probe.mjs`：直接对 MediaMTX 发 WHEP 并读取 `framesReceived`/`framesDecoded`/`getVideoPlaybackQuality()`，应用、鉴权与计划激活都不在链路里）。同一台 MediaMTX、同一个 Chromium，只改编码参数：

| 编码参数 | 浏览器接收 / 解码 / 呈现 fps |
|---|---|
| `ultrafast -tune zerolatency`（slice threads 开） | **15.99 / 15.99 / 15.99** |
| `ultrafast -tune zerolatency -x264-params sliced-threads=0` | **24.99 / 24.99 / 24.99** |
| `ultrafast -x264-params sliced-threads=1`（不开 tune） | **14.95 / 14.95 / 14.95** |
| `ultrafast`（两者都不设） | **24.99 / 24.99 / 24.99** |
| 离线编码后 `-c copy` 发布（对照） | **25.02 / 24.99 / 24.99** |

同一轮排除的其它变量：**码率**（700 kbps 与 2500 kbps 结果相同）、**并发**（1 路与 5 路，每路都是约 15 fps）、**传输**（WSL 内 Chromium 走 ICE/UDP 与 Windows Chrome 走 ICE/TCP，结果相同）、**浏览器解码能力**（新增 `web/tests/local-play-probe.mjs`：同一浏览器播放本地文件，720p25 为 25.00 fps、1080p30 为 30.13 fps）。

必须记录的负结果：MediaMTX 自己的 API 在这段时间内始终报告 `outboundFramesDiscarded: 0`，且 MediaMTX 日志里 `grep -i -E 'too slow|discarding'` **没有任何输出**。该计数器只覆盖“读取者太慢导致 ring buffer 丢弃”（`internal/stream/reader.go` 的 `push`），覆盖不到 H264 access unit 组装这一层，**因此不能用它排除服务端**。

**修复**：`gateway/transcode-on-demand.sh` 的 libx264 分支保留 `-tune zerolatency`（低延迟特性仍然需要），显式关闭 slice threads：

```sh
-c:v libx264 -preset veryfast -tune zerolatency -profile:v high \
    -x264-params sliced-threads=0 \
    -pix_fmt yuv420p -bf 0 -sc_threshold 0 -force_key_frames 'expr:gte(t,n_forced*2)'
```

**端到端验证**（真实脚本 + 真实 MediaMTX `runOnDemand` 接线，与 `control_server.cpp` 注册 `hybrid-*` 的方式一致）：同一条 25 fps 来源（离线编码后 `-c copy` 发布，排除来源自身因素）、同一条 `direct-` 路由，注册两条 `hybrid-` 路由，一条运行已提交的脚本、一条运行把该参数删掉的同一脚本：

| 路由 | 编码器参数 | 浏览器解码 fps |
|---|---|---|
| `hybrid-aaa…` | 修复前（删掉 `sliced-threads=0`） | **17.00** |
| `hybrid-bbb…` | 已提交脚本 | **24.99** |

**回归测试**：新增 `tests/test-transcoder-encoder.mjs`——用会打印 argv 的 ffmpeg 桩断言 libx264 分支必须带 `-x264-params sliced-threads=0`、不得出现 `sliced-threads=1`、同时仍保留 `-tune zerolatency`/`-bf 0`/`-sc_threshold 0`，并断言 `copy` 分支不出现 x264 参数。`node --test tests/test-transcoder-encoder.mjs tests/test-transcoder-mix.mjs` → **6/6 通过**。

同样的问题存在于仓库自带的相机夹具 `tests/rtsp-fixture/publish.sh`（H264 分支同样带 `-tune zerolatency`），已一并加上该参数；`publish-hevc.sh` 用 x265（无 slice-threads 语义），且 HEVC 只能经转码路径进入浏览器，保持原样。**尚未验证**：NVENC（`-tune ll`）与 VA-API 两条转码分支是否有同类行为——本环境默认走 x264，这两条路径没有实际触发。

**English.** The Direct/Hybrid frame-rate gap was neither the browser, nor the control plane, nor the transport, nor the sources: it was one encoder setting. x264's `sliced-threads`, which `-tune zerolatency` enables, splits every frame into several slices, and MediaMTX then hands only about 60% of that stream's frames to its WebRTC output (15.99 fps against 24.99 fps on the very same 720p25 source, with `packetsLost=0` and `nackCount=0` because the browser genuinely receives only those frames). Bitrate (700 kbps vs 2500 kbps), concurrency (1 vs 5 sessions), transport (ICE/UDP inside WSL vs ICE/TCP from Windows) and the browser's own decode capability (25.00 fps for a local 720p25 file, 30.13 fps for 1080p30) were eliminated in the same session. MediaMTX's `outboundFramesDiscarded` counter stayed at 0 and its log never printed a slow-reader warning, because that counter only covers ring-buffer drops for slow readers, not H264 access-unit assembly, so it must not be used to clear the server side. The fix keeps `-tune zerolatency` and adds `-x264-params sliced-threads=0` to the gateway's libx264 branch; end to end, through the real script and the real MediaMTX runOnDemand wiring on one shared 25 fps source, the committed script delivered 24.99 fps where the same script with the flag removed delivered 17.00 fps. `tests/test-transcoder-encoder.mjs` locks the flags in (6/6 passing together with the audio-mix suite). Not yet verified: whether the NVENC (`-tune ll`) and VA-API branches behave the same way; this environment defaults to x264 and neither branch was exercised.
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

- **负偏移（本轮已修正判据）**：`0:1.0:0:-2000,1:1.0:0:0` 实测 —— 转码器 stderr 输出 `新增端到端延迟: 2000ms (video and every track)`；同一轮抓取的音频中第一路立即出现（440Hz 幅度 **0.0626**）、第二路在归一化延迟后加入，符合 `B=2000` 下 `delay_0=0`、`delay_1=2000`。
- **视频位移已精确验证（本轮新增工具与证据）**：新增可重复执行的 `tests/verify-video-shift.sh` —— 它自建 MediaMTX 与双音轨合成来源，用与转码器**完全相同**的 filter graph 与 `setts=ts=TS+B/(1000*TB)` 各跑一次并写到**文件**（绕开 MediaMTX 的重新计时），比较两次的最大 PTS。实测（B=2000）：视频最大 PTS 位移 **2.003 s**，音频位移 **−0.017 s**，判据 PASS——即 `B` 被精确加到视频上，各轨延迟与 `B+d_i` 一致。之所以必须用文件输出，是因为从 RTSP/WebRTC 客户端读取时每条流都会被重新归零，看不到该位移。
- **客户端侧已实测通过（本轮闭环）**：用闪光+同步音脉冲素材（黑底 640×360，每 4 秒一次 120 ms 全白闪光，音频是与之对齐的 1 kHz 脉冲）经**真实转码器**的 audio-mix 发布，再在 Chrome 里用 `web/tests/av-sync-probe.mjs` 以同一个 `performance.now()` 时基同时检测画面闪光（canvas 亮度）与音频脉冲（AnalyserNode RMS）：

| mix 规格 | 闪光−脉冲（逐次，ms） | 中位数 |
|---|---|---|
| `0:1.0:0:0`（无偏移，对照） | −90 / −49 / −16 / 0 / 0 | **−16 ms** |
| `0:1.0:0:-2000`（B=2000） | 1955 / 1992 / 1996 / 2030 / 2033 | **1996 ms** |

  即：没有配置偏移时浏览器体验到约 0；配置 −2000 ms 时视频确实比该轨音频晚约 2.0 秒，与 `B` 一致。**F5-05 的负偏移不再是“只由构造保证”，而是端到端实测通过。**
- 复现前提（本轮踩到并记录）：`mix-*` 路由必须先用 MediaMTX API 注册（dev 网关不自动建路径）；独立启动 MediaMTX 时需带 `MTX_WEBRTCLOCALTCPADDRESS` 等 ICE/TCP 设置，否则 Windows 浏览器 ICE 永远连不上（日志 `deadline exceeded while waiting connection`），WHEP 会建会话但没有媒体。

驱动现状：已修正两个缺陷——(1) 录制与转码器首帧的竞争改为“捕获必须含信号，否则重试（最多 3 次）”，静音捕获现在报告为重试而不是产品失败；(2) 频率能量函数改回均值幅度并同步修正被判据（旧阈值 1e6 属于已被替换的 Goertzel 尺度，曾把正确结果判为失败）。修正后 `node tests/audio-regression.mjs` **三项全部通过**：首轨静音后第二轨仍可听（e880=0.0625、e440=0.0000）、0.25 增益只应用一次（12.04 dB）、负偏移归一化与逐轨延迟符合预期。

## 6. 本轮发现并修复的产品缺陷 / Product defects found and fixed

### 6.1 控制面串行激活：唯一 io_context 线程 + 全局路由锁 / Control-plane serial activation: one io_context thread behind one global route lock

**问题（已实测）**：`ControlServer` 只有唯一一个 io_context 线程，而 `create_direct()`/`create_client_plan()` 在**全局** `route_operation_mutex_` 保护下执行会阻塞的上游 I/O（MediaMTX 路由建立、按需等待、上游 WHEP 信令）。用一个**受控慢来源**复现——本地 TCP 端点接受连接但永不回应，只把其中一路相机端点临时改到它上面，用户设备不受影响：

| 指标（任意时刻只有一个慢来源） | 修复前 | 修复后 |
|---|---|---|
| `GET /api/v1/scene`（纯内存读）耗时 >1 s 的采样 | **16 / 102（最大 10.12 s）** | **0 / 248（最大 0.103 s）** |
| 五个并发 WHEP 调用耗时 | 10.2 / 10.3 / 20.3 / 20.4 / 20.4 s | 四路健康 **0.157 / 0.371 / 0.380 / 0.382 s**，只有慢来源自己 10.1 s 并重试 |
| 五路瓦片出图 | 2–3 路 live，其余被拖住 | **4 路在 515 ms 全部 live**，慢来源自己停在 connecting |
| 重复 activate 是否产生重复路由 | — | 5 路相机 = 5 条 `direct-` 路由（同一计划重试 7 次后仍是 5 条），1 条 `hybrid-` |

**修复**：

1. 请求处理移到**有界工作池**（`RequestPool`，默认 4 个工作线程，`WEBOBS_CONTROL_WORKERS` 可调，队列上限 256 条；满载时在调用线程内联处理而不是丢请求）。只有响应写回被 `net::post` 回会话自己的 executor，socket 仍只在单一 io_context 线程上操作。
2. 全局 `route_operation_mutex_` → **按来源**的路由锁（`route_lock_for(source_id)`）：不同来源互不阻塞，锁内不做网络等待，同一来源的重复请求因此复用它已建立的路由。整篇文档的 `reconcile_sources()` 改用独立的 `reconcile_mutex_`，不再挡住任何激活。
3. **共享状态审计**（把 handler 移出 io_context 线程的前置条件）：`ControlMetrics`/`RuntimeStatus` 已是原子；`BasicAuthenticator`、`SessionStore`、`SceneController`、`StudioController`、`WhepProxy` 已有各自互斥量；`NvrProxy`/`CameraProxy` 只有构造期常量；**`WebSocketHub` 原先没有锁**（`join` 在 io_context 线程、`broadcast` 现在在工作线程），已补锁并在锁外发送。
4. **关闭顺序**：停止接受新连接 → 工作池排空在途任务（此时 io_context 仍在运行，响应能真正写出）→ `context.poll()` → 停止 io_context → join。实测优雅停止 **5.31 s** 完成，无挂起。

**回归**：`ctest`（`webobs-unit-tests`）通过；受控慢来源对照（上表）；同一来源重复激活不产生重复路由/转码；认证路径不变（认证在派发**之前**于 io_context 线程完成，工作池不接触凭证判定）；关闭无挂起。

**未覆盖**：真实相机下的同一对照（本轮用受控端点隔离变量）、授权撤销与客户端断开的专项用例。

**English.** The control server has a single io_context thread, and `create_direct()`/`create_client_plan()` performed their blocking upstream I/O (MediaMTX route setup, on-demand waiting, upstream WHEP signalling) while holding the global `route_operation_mutex_`. Reproduced with a controlled slow source - a local TCP endpoint that accepts and never answers, temporarily used for one camera endpoint only: before the fix the trivial in-memory `GET /api/v1/scene` took over one second in 16 of 102 samples (max 10.12 s), the five concurrent WHEP calls took 10.2/10.3/20.3/20.4/20.4 s, and only two or three tiles ever went live. After the fix no sample exceeded 103 ms, the four healthy plans completed in 0.157-0.382 s while only the slow plan waited out its own timeout, and the four healthy tiles were live at 515 ms. The fix moves request handling onto a bounded worker pool (4 workers by default, `WEBOBS_CONTROL_WORKERS` configurable, 256-deep queue, served inline rather than dropped when saturated) and posts only the response write back to the session's executor, so sockets stay single-threaded; replaces the global route lock with per-source route locks taken without holding them across network waits; audits the shared state the handlers touch (`WebSocketHub` had no lock and now has one; the controllers, authenticator, session store, metrics and status were already safe); and fixes the shutdown order (stop accepting, drain the pool while the io_context still runs, then stop it) which measured 5.31 s with no hang. Repeated activations of one source still produce exactly five `direct-` routes and one `hybrid-` route, and the authentication path is unchanged because authorization runs before dispatch, on the io_context thread. Not covered: the same comparison against a real camera (this used a controlled endpoint to isolate the variable), and dedicated revoke/disconnect cases.


### 6.2 此前轮次修复的两个缺陷（保留记录）/ Two defects fixed in earlier rounds (kept for the record)

1. **Direct-only 网关启动即崩溃（`185197b`）**：`detect_video_encoder_capabilities(config, false)` 无条件调用 `encoder_registered()`，后者遍历 `obs_enum_encoder_types`；Direct-only 路径刻意跳过 `obs_startup`，于是在控制面监听之前 SIGSEGV（栈顶 `libobs.so.30(obs_enum_encoder_types+0xd)`，两个构建同样崩溃）。由 `361cada` 引入。修复后 Direct-only 可正常启动并返回如实的 `configuration=disabled`。**这是 Direct/Hybrid 验收长期缺失的直接原因。**
2. **未配对被误报为控制面不可达（`0a1026b`）**：`requestBrowserPlan()` 把 `browserDeviceHeaders()` 与 fetch 放在同一个 try 中，未配对时抛出的「此浏览器尚未完成配对」被改写成「控制面当前不可达」，把排查方向引向网关/网络。现在未配对会走 `DirectPreview` 的 needsPairing 分支并给出配对操作。

## 7. 仍未完成 / Still open

1. **“零来源重启”判据**：合成模式 30 分钟只剩这一项未通过（全场 4 次，camera-mu2ux4qk 与 camera-mu2ux99i 各 2 次），来自两路已知不稳定的真实相机。需要判断这是否应作为来源健康前提下的绝对门槛，或用健康来源复测以确认产品在来源健康时零重启。
2. ~~每来源 WHEP 直连的速率上限~~：**已定位并修复**（第 4.5 节）——根因是 x264 的 `sliced-threads`（`-tune zerolatency` 默认开启）与 MediaMTX WebRTC 输出的组合，修复为 `gateway/transcode-on-demand.sh` 显式 `-x264-params sliced-threads=0`，端到端由 17.00 fps 提升到 24.99 fps；**修复后的 Direct/Hybrid 30 分钟验收已重跑并通过全部四项判据（第 4.3.6 节）**。另有独立项：服务端 `/activate` 仍以约 2.57 秒/路串行（单 io_context 线程 + 全局路由锁），来源慢时仍会放大首帧。
2. ~~单路断开/恢复的受控故障注入~~：**已完成**（第 4.3.4 节）——其余四路全程不受影响（最大帧间隔 0/0/1626/0 ms），被断开的一路在来源恢复后约 12–13 秒内重新出图。剩余：在真实相机场景下同样复测一次（本轮用健康合成源以隔离变量）。
3. ~~音视频相对偏移的客户端侧确认~~：**已完成**（第 5 节）——闪光+同步音脉冲素材在 Chrome 内实测，规格 `0:1.0:0:0` 中位 −16 ms、规格 `0:1.0:0:-2000` 中位 **1996 ms**，与 `B` 一致。
4. **Docker / vGPU** 与跨设备音视频组合（按用户已确认范围留待后续）。

## 7. 命令 / Commands

```powershell
# 标准 Windows 入口（本轮已实测可启动到 WEBOBS_DEV_READY，并转发 --soak）
.\scripts\dev.ps1 -Composite -Soak

# 前端与启动器
web\node_modules\.bin\tsc.CMD --noEmit    # 工作目录 web
node --test tests/test-dev-launcher.mjs
node --test tests/test-transcoder-mix.mjs tests/test-transcoder.mjs
node --test tests/test-transcoder-encoder.mjs tests/test-transcoder-mix.mjs
node --test tests/test-soak-verdict.mjs

# 用修复后的判定器重新派生一条历史长稳（不覆盖原始证据）
node tests/soak-derive.mjs --browser tests/artifacts/browser-soak/<run> \
  --targets build/scratch/targets-direct.json --mode direct

# WHEP 速率探针（第 4.5 节的隔离实验；需一个 MediaMTX：rtsp 8554 / webrtc 8889）
# WSL 内 Chromium 走 ICE/UDP；WHEP_PROBE_CHANNEL=chrome 用已安装的 Chrome（ICE/TCP）
node tests/whep-rate-probe.mjs http://127.0.0.1:8889 path-a,path-b 30

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

合成模式已在原始 1920×1080 规格下通过正式 30 分钟验收：呈现 29.18 fps（目标 90% = 27）、首帧 3542 ms、最大帧间隔 0 ms、媒体时间推进 1800 s，服务端 30/30 采样健康且 program 路由全程 ready；唯一未通过的是“零来源重启”（全场 4 次，集中在两路已知不稳定的真实相机）。

本轮把帧率门槛的归因彻底做实：**瓶颈不是来源，也不是浏览器，而是 WSL 下 OBS 的 NVENC**。同一场景、同一来源、同一时刻只切换编码器的 A/B 显示 NVENC 24.5 fps、x264 29.6/29.8 fps；浏览器 `getStats()` 显示两条链路都 `packetsLost=0`、`nackCount=0`，NVENC 链路只收到 24.41 fps、x264 链路收到 30.07 fps（解码 30.03、呈现 28.7）。因此**改用 x264 后，即使面对本轮不稳定的真实相机，合成模式的“≥目标 90%”在服务端与浏览器两侧都已达成**；此前 73.2% 的结果应归因于编码器选择。据此启动器在 D3D12 后端 OpenGL 且用户未显式指定时默认 x264，并打印实测理由（显式 nvenc 仍可强制）。

**本轮的决定性进展：Direct/Hybrid 帧率缺口的根因已找到并修复（第 4.5 节）。** 缺口既不在浏览器、也不在网关控制面或传输，而是 x264 的一个参数：`-tune zerolatency` 会开启 `sliced-threads`，MediaMTX 随后只把约 60% 的帧交给它的 WebRTC 输出。隔离实验（`web/tests/whep-rate-probe.mjs` 直接对 MediaMTX 发 WHEP）里，同一路 720p25 来源开 slice threads 为 15.99 fps、关掉为 24.99 fps；码率（700k/2500k）、并发（1/5 路）、传输（ICE/UDP 与 ICE/TCP）、浏览器解码能力（本地文件 720p25=25.00、1080p30=30.13 fps）都被逐一排除。修复后，用真实 `transcode-on-demand.sh` 与真实 MediaMTX `runOnDemand` 接线、同一条 25 fps 来源做 A/B：修复前 17.00 fps、修复后 **24.99 fps**。因此**此前把 Direct/Hybrid 帧率缺口归因于浏览器侧并发接收能力（4.3.3/4.3.5）是错的**，正确结论是编码器侧的 slice threads；这也意味着 F5-06 的 Direct/Hybrid 帧率门槛需要在修复后的代码上重跑 30 分钟才能定论。

**This round's decisive result: the Direct/Hybrid frame-rate gap is root-caused and fixed (section 4.5).** The gap was neither the browser nor the control plane nor the transport but one x264 parameter: `-tune zerolatency` enables `sliced-threads`, after which MediaMTX hands only about 60% of the frames to its WebRTC output. In the isolated experiment (`web/tests/whep-rate-probe.mjs` speaking WHEP straight to MediaMTX) the same 720p25 source measured 15.99 fps with slice threads and 24.99 fps without them, while bitrate (700k vs 2500k), concurrency (1 vs 5 sessions), transport (ICE/UDP vs ICE/TCP) and the browser's own decode capability (local files: 720p25 = 25.00 fps, 1080p30 = 30.13 fps) were all eliminated. With the fix in place, the real `transcode-on-demand.sh` behind the real MediaMTX runOnDemand wiring delivered **24.99 fps against 17.00 fps** for the same script without the flag on one shared 25 fps source. The earlier attribution of the Direct/Hybrid gap to the browser's concurrent receive capability (sections 4.3.3 and 4.3.5) is therefore wrong; the true cause is the encoder-side slice threads, and the Direct/Hybrid frame-rate criterion now has to be re-run for 30 minutes on the fixed code before it can be judged.

本轮同时定位并修复了两个此前一直阻塞 Direct/Hybrid 验收的产品缺陷：**Direct-only 网关启动即崩溃**（`obs_enum_encoder_types` 在未 `obs_startup` 时被调用）与**未配对被误报为控制面不可达**。修复后 Direct/Hybrid 五路在真实产品页面上连续播放 1787.8 秒（29.8 分钟）且媒体时间全程推进，验收首次真正执行。

**总体状态（复核后）：已实现，受控来源的性能验证通过，原始部署的最终验收尚待关闭。** F5-01/F5-02 保持既有自动化验证；F5-03 的 OBS 渲染与编码均已在真实运行中启用并取证；F5-04/F5-06 在受控来源下的**呈现**帧率与首帧达标（Direct/Hybrid 24.63–24.65 fps／目标 25，composite 29.18 fps／目标 30，首帧 3.5–6.2 s），但这两次历史长稳按修复后的判定器均为 **INCOMPLETE**（1.1 节），不能作为正式验收通过；真实相机场景下的 Direct/Hybrid 首帧 31.7–74.4 s 与停顿 3.07–6.70 s 仍未关闭。F5-05 的批次 A/B/C 代码与单测已完成，端到端音频驱动通过。剩余：受控来源与真实来源各自的 1800 秒正式长稳（判定器修复后）、控制面串行激活修复、真实来源单路故障注入、NVENC/VA-API 转码分支的同类 slice 行为确认、以及真实来源的输入质量测量。

The composite mode has now passed a formal 30-minute acceptance at the original 1920x1080 spec: 29.18 fps presented (90% of the 30 fps target is 27), first frame 3542 ms, largest frame gap 0 ms, media time advancing for 1800 s, and 30/30 healthy server samples with the program route ready throughout. The only criterion still unmet is zero source restarts (four in total, concentrated on the two known-unstable real cameras).

This round finally pinned the frame-rate attribution: the limiter is neither the sources nor the browser but OBS NVENC under WSL. An A/B that changed only the encoder on the same scene, sources and moment gave NVENC 24.5 fps against x264 29.6/29.8 fps, while the browser getStats() showed packetsLost=0 and nackCount=0 on both legs: the NVENC leg received 24.41 fps and the x264 leg 30.07 fps (30.03 decoded, 28.7 presented). With x264 the composite acceptance therefore meets the at-least-90-percent threshold on both the server and the browser side even against this round's unstable real cameras, and the earlier 73.2% result is attributable to the encoder choice. The launcher now defaults to x264 when the OpenGL context is D3D12-backed and no encoder was chosen explicitly, printing the measured reason; an explicit nvenc still forces the hardware encoder.

The rendering and encoding side moved from software-only to a real hardware path (0.0% rendering lag, 0.7% encoding lag, NVENC registered and selected), and the original 1920x1080 five-source Composite played for a full 30 minutes inside the real product page with the first-frame and stall thresholds met. The frame-rate threshold is not met, and per-item measurement attributes that to the real camera feeds themselves (7.8-18 fps with HEVC packet loss) rather than to compositing, encoding or transport. This round also located and fixed the two product defects that had been blocking the Direct/Hybrid acceptance all along: the Direct-only gateway crashed on startup (obs_enum_encoder_types called before obs_startup) and an unpaired browser was misreported as an unreachable control plane. With both fixed, the Direct/Hybrid wall played for 1787.8 seconds (29.8 minutes) in the real product page with media time advancing throughout, so that acceptance finally ran. F5-01/F5-02 keep their existing automated verification, F5-03 has OBS rendering and encoding enabled and evidenced in a real run, F5-04/F5-06 have a 30-minute acceptance in each playback mode while the first-frame, stall and frame-rate thresholds are not all met against the real sources, with the frame-rate gap now root-caused to the encoder rather than to the sources or the browser (section 4.5), and the controlled-source results hold for presented frame rate and first frame (Direct/Hybrid 24.63-24.65 fps of a 25 fps target, composite 29.18 fps of 30, first frame 3.5-6.2 s), while both historical soaks are INCOMPLETE under the fixed oracle (section 1.1) and therefore do not constitute a formal acceptance; F5-05 has batches A/B/C implemented with unit tests and a passing end-to-end audio driver. Overall: implemented, with performance verified on controlled sources, and the original deployment's final acceptance still open. Still open: a formal 1800 s soak on controlled and on real sources under the fixed oracle, the control-plane serial-activation fix, single-route fault injection against a real source, the same-slice check for the NVENC/VA-API branches, and an input-quality measurement of the real sources.
