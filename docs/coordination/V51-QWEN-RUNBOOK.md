# 本地 Qwen 3.8 Next 接手 Windows v5.1

## 直接交给 Qwen 的启动指令

> 你在 `/home/czl/projects/monitor_wall_czl` 继续交付 Windows x64 v5.1。读根目录 `AGENTS.md` 和本手册，按“接手检查”执行。先运行只读命令，输出一条带 task ID、worktree、完整 SHA、CI run ID 和第一个失败阶段的简报。确认当前任务已交接并以自己的唯一会话 ID 认领后，从第一个失败点开始。每轮只验证一个假设，复现、修复、跑相关测试、更新账本。完成本轮后按照结果表进入下一轮。正在跑的 CI 用 run ID 恢复检查。用户的真实 Windows 验收集中在完整候选。最终目标是完整产品和同配置下不高于 OBS 的监看开销。

## 1. 接手检查

在共享账本 checkout 执行。`.worktrees/` 内的 PR 代码和这里的账本是不同 checkout。

```bash
project=/home/czl/projects/monitor_wall_czl
git -C "$project" status --short --branch
git -C "$project" worktree list
python3 "$project/scripts/agent-sync.py" --root "$project" check
gh run list -R LiaoYK001/Web-Camera-Monitor-Wall \
  --workflow windows-obs-native-host.yaml --limit 8 \
  --json databaseId,headBranch,headSha,status,conclusion
gh pr view 67 -R LiaoYK001/Web-Camera-Monitor-Wall \
  --json state,headRefName,headRefOid,baseRefName,mergeStateStatus
```

1. 读 `STATUS.md`、`TASKS.md`、`HANDOFF.md`、`DECISIONS.md` 和 `PLAYBOOK.md`。账本的 run 可能较旧，与 GitHub 和实际 worktree 对一次。用 `git -C "$worktree" status --short --branch` 和 `git -C "$worktree" rev-parse HEAD` 核对准备修改的目录。任务范围以 `TASKS.md` 为准。
2. `V51-008` 是当前 Program 输出验收任务。历史账本把它和其他开发任务登记在 `deepseek-v51-20261118-01` 下。Qwen 用新会话 ID。旧归属仍存在时，先做只读诊断，由原会话或协调人按协作规则完成交接，再认领同一任务。协调人处理原会话已退出的情况。共享 worktree 中已有的脏文件、分支和任务记录都保留。
3. PR #67 对应 Program 修改，接手快照的源码目录为 `.worktrees/v51`。全栈构建从最新顶层分支运行，rc.59 对应 `.worktrees/v51-legacy`。接手快照的栈是 `#67 → #70 → #71 → #74 → #75 → #76`，实际关系用最新 PR 的 `baseRefName` 和 `headRefOid` 核对。每个堆叠分支只带自己的改动，换基后核对 diff 和 SHA。#69 是发布链，#73 是发布说明。
4. 每次实际动手前写一行检查点，例如 `V51-008 | worktree … | SHA … | rc/run … | failurePhase … | 本轮只验证 …`。读源码时先从失败断言向上追到产出该证据的函数，然后再看产品路径。CI 开跑后登记 run ID、SHA、版本、参数和预期回执，下一会话可直接恢复。

## 2. 证据检查脚本

脚本只调用 GitHub 只读 API、下载该 run 的回执到新临时目录，并输出 JSON。它依据 workflow、完整 SHA 和版本核对回执。默认检查安装证据，`--freeze` 额外要求同一 Windows 安装的 120 分钟实测。退出码和 `result` 都要读。

```bash
python3 "$project/scripts/v51-ci-gate.py" 44385767337 \
  --sha a5337f8c205180de1f45ec5f6276ec84d44eb287 --version 5.1.0-rc.59
```

| 退出码和 `result` | 下一步 |
| --- | --- |
| `2` `wait-for-ci` | 记录 `activeSteps`。复用同一个 run ID，继续本地可完成的工作。 |
| `3` `inspect-first-failure` | 先看 `failedSteps` 和 `failureReceipts`。没有失败回执时，读该 job 的失败日志并记录最先出错的命令和断言。 |
| `3` `inspect-ci-conclusion` | 对取消、超时等结果确认原因和当前分支，再决定是否重派。 |
| `4` `identity-mismatch` 或 `cannot-read-evidence` | 核对 SHA、版本、run ID、GitHub CLI 和回执是否过期。 |
| `4` `collect-missing-evidence` | 按 `issues` 补安装、升级、回执或长稳证据。 |
| `0` `review-install-evidence` | 审阅同源安装和覆盖升级，确认 PR 子栈与被测 SHA 一致。 |
| `0` `review-frozen-candidate` | 进入候选字节校验及发布评审。目标 Windows 实机、真实旧档案和 OBS 性能需要独立证据。 |

手动读日志优先使用 `gh run view <run-id> -R LiaoYK001/Web-Camera-Monitor-Wall --log-failed`。长日志按失败阶段和函数名筛选。额外下载时遵守根 `AGENTS.md`，每次新建临时目录。账本仅记录脱敏摘要、版本、SHA、run 和数值。

### 工具权限控制

如果本地 Agent 的工具层支持限制，给它工作任务 worktree 和账本脚本的访问权限。常用入口是 `git status/diff/log`、`rg`、测试、上面的检查脚本和 `agent-sync.py`。将 `git push`、`gh workflow run` 与批准后的发布命令绑定到具体 PR、分支和环境，沿用项目现有授权。共享 checkout 保留他人的文件和历史。`main`、Tag、更新源和历史 Release 附件由正常发布流程操作。此仓库脚本控制证据判定，工具权限由 T3 或实际运行器执行。

## 3. 当前第一项任务是 rc.59 的音轨增益

2026-11-19 的直接证据为 [rc.59](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44385767337) 的 `native-product-entry-ui.json`。46 项通过后，`program-track-controls` 失败。Portable 五路 HEVC、Program MP4、回环 RTMP 后通过 RTSP 解码双音、总线隔离、逐轨静音、ONVIF 模拟设备操作与拒绝结果已记录。安装步骤跳过，因此成对恢复、旧数据导入和 LAN 没有本轮安装证据。若 GitHub 有更新的失败，以更新回执的第一项为准。

| 音调 | 两轨增益 `1.0` | 仅第二轨增益 `0.2` | 比值 |
| --- | ---: | ---: | ---: |
| 440 Hz，第 0 轨 | 1261.6 | 2164.5 | 1.716 |
| 880 Hz，第 1 轨 | 828.1 | 432.2 | 0.522 |

按这个顺序做，每一步记下结果：

1. 在 #67 当前源码里搜索 `reducing one track`、`record_program_output` 和 `wait_program_mix_audible`。断言在 `native-host/tests/product_windows.py`。样本幅度取自 `native-host/tests/pixel_windows.py` 的 `tone_amplitude()`，混音滤镜在 `native-host/src/product_scene.cpp`。现有图按轨加 `volume` 后用 `amix:normalize=0`。确认实际输入索引、应用的音量和样本窗口。
2. 用相同的两路合成音调、相同的输出总线，从稳定区间做 `1.0 → 1.0 → 0.2` 对照。为每段记录开始时间、窗口和两频振幅。先证明两路都已进入录制，用一致的固定窗口避开启动段。若 `1.0 → 1.0` 已漂移，查每轨就绪、采样起点、旧场景退出以及两段素材是否相同。若基线稳定，比较进入 OBS 前混音输出与最终 AAC/MP4，判断差异首次出现的位置。
3. 把修复限制在已定位的那一层。保留逐轨静音和总线隔离，保留未改增益音轨的门槛。确认测试在故意把轨道增益写错时仍失败。若回执不足以定位，先加窄范围数值诊断，保存脱敏数据，避免只重试同一 SHA。
4. 先在 Fedora 用合成媒体和实际解码工具复现相关行为。在实际源码 worktree 运行 `python3 -B native-host/tests/test_build_contract.py` 和 `git diff --check`。然后在修复后的全栈顶层派发 Windows `product_mode=true complete=true soak_minutes=0` 的新候选，核对新版本是否已用并登记完整 SHA。再次失败时从新回执首个失败点继续，保留此前同版本路径的证据。
5. 增益通过后核对 `program-track-offset` 和 `program-publish-disconnect`。偏移当前检查混音参数，声学偏移需要实际输出证据。断开私有中继后验证明确报错、成功恢复和真实消费者收到推进的视频帧。当前传输为 OBS 回环 RTMP → MediaMTX → RTSP/WHEP。HTTP 端点应答只证明 WHEP 端点可达，浏览器握手及出画面需要单独验证。

### rc.60 起改到的两个失败面：TAKE 后的冻结层级与 Program 发布帧数 / the two failure faces since rc.60

增益的 Fedora 对照已完成，Windows 侧现在先停在别处：rc.60（run 44474401536）停在 `native-program-take` 像素，rc.61（run 44524750280）通过 TAKE 后停在 `program-streaming` 的 `published Program did not deliver enough video frames`。两处都按“一轮只验证一个已定位失败点”处理。

- 发布帧数：读回执里的 `programStreamVideoProbe`（ffprobe 返回码、stderr 片段、实际帧数、`pts_time` 跨度、实测帧率、读取前后的宿主 `renderFrames`/`laggedFrames`、`streamError`）。返回码非 0 指向中继或读取路径，帧数与实测帧率过低指向编码器 pacing，`renderFrames` 在窗口内停滞指向宿主图形线程。断言阈值未放宽，不要用重试掩盖。
- 渲染探针现在是按窗口开的：宿主只在 `product-state.json` 同目录的 `product-render-probe.control`（`{"schema":1,"untilMs":<unix ms>}`）打开的窗口内绘制，缺文件、窗口过期或 `untilMs: 0` 都不绘制。像素断言所在窗口内探针关闭，所以像素与发布帧证据不含探针开销；只有像素断言即将失败时才额外采一次探针开启的短窗口，写进 `pixelFailureDiagnostics.probeOnWindow`。若该窗口画面重新流动而断言窗口是冻结的，说明冻结依赖探针会改变的状态（源 show/activate 或只在绘制时推进的图形线程），不是馈送；若同样冻结，看探针自身的逐格摘要判断 Scene 渲染是否在底层变化。

Probe draws are window-scoped: the host only draws while `product-render-probe.control` (next to `product-state.json`, `{"schema":1,"untilMs":<unix ms>}`) has an open window, so an absent file, an expired window or `untilMs: 0` draws nothing. Asserted pixel windows run with the probe closed, and only a pixel failure adds one probe-open capture in `pixelFailureDiagnostics.probeOnWindow`. Read `programStreamVideoProbe` for the published-frame failure instead of retrying the same SHA.

### rc.62 起：Program 发布视频要先等关键帧 / Program published video must wait for a keyframe (since rc.62)

rc.61（run 44524750280）与 rc.62（run 44534272424）连续两轮停在 `program-streaming`，详情同为 `published Program did not deliver enough video frames`；同轮 TAKE 像素、录像双音、发布流双音都通过。回执里 ffprobe 返回码 0、`frames` 0、`ptsSpanSeconds` 0.0，stderr 是 `co located POCs unavailable` 与 `mmco: unref short failure`，而宿主 `renderFrames` 在该窗口 +60、`laggedFrames` 不变、`streamConnected` true、`streamError` 空，`observedState.renderProbe` 为 `{"available": false}`。这组数值说明宿主在产出帧、中继在推流，解码端一帧都不认：晚加入的 RTSP 客户端落在编码器当前 GOP 内，旧探针只读 20 个包（约 0.7 s），而 `product_output.cpp` 两处都设 `keyint_sec 2`。另外 `pts_time` 是字符串，旧代码只接受数字，跨度恒记为 0。

从 `codex/v51-r3-output@d6d2624` 起，两个 Program 发布视频门禁（首次推流与中继被杀后的恢复推流）共用 `published_video_window()`：同一条连接读 6 秒（≥2 个关键帧周期），`float()` 解析字符串 `pts_time`，输出 `firstDecodableFrameMs`、`windowTimedOut`、`elapsedMs`、`unparsableStamps`，并由独立线程读完 stderr。断言为 ≥10 帧、时间戳严格递增、跨度 ≥ 一个关键帧周期；返回码要求去掉，因为窗口结束会主动终止这条刻意长开的连接。副连接 `published_packet_window()` 给出 `packetProbe`（包数、关键帧包数、`firstPacketIsKey`、首个关键帧 pts、关键帧间隔）。`test_build_contract.py` 里的 `test_published_program_video_gate_waits_past_a_keyframe_for_a_late_join` 从 `product_output.cpp` 解析 `keyint_sec` 并要求与门禁常量一致、窗口 ≥2 倍、两处都用共享读取器、文件内不得残留 `%+#20`。
本机已用固定 MediaMTX v1.18.2 与 `product_output.cpp` 同形状的私有中继配置复现过：推流约 6 秒后以晚加入者身份读取，旧的 20 包读取返回码 0、`frames` 0；同一连接读 6 秒得到 148 帧、时间戳单调、跨度 4.9 s、`firstDecodableFrameMs` 1977 ms（正是一个关键帧周期）、实测 30.2 fps；副连接包探针给出 181 包、关键帧包 3、`firstPacketIsKey` false、首个关键帧 pts 1.0676、关键帧间隔 `[2.0, 2.0]`。也就是说中继确实会把编码器每 2 秒的 IDR 交给晚加入者，只是第一个包不是关键帧；缺陷在读取窗口，不在产品侧推流。复现命令：下载 `mediamtx_v1.18.2_linux_amd64`，用上面的 YAML 起中继，`ffmpeg -re -f lavfi -i testsrc2=size=320x180:rate=30 -c:v libopenh264 -g 60 -pix_fmt yuv420p -an -f flv rtmp://127.0.0.1:<port>/program`（本机 ffmpeg 无 libx264），再分别跑两种探针。stderr 的 `[libopenh264] DecodeFrame failed` 与 CI 里的 `co located POCs unavailable` 同源，都是从 GOP 中间起解的提示。


读 rc.64（run 44548882087，源码 `0a7726a983694bd62621e46617d90b3c0f3ccb2b`，内部 `5.1.0-rc.64`，`soak_minutes=0`）时按这个顺序判断。rc.63（run 44544305133）本身没有产生产品结论：它的 `ValueError: unsupported format character ':'` 来自门禁用 %-格式化生成含 `%` 的 MediaMTX 读取区间，并且因为 `programStreamVideoProbe` 在两个探针都完成后才写入，已跑完的 6 秒帧窗口结果也被丢掉。从 `c28ddea` 起读取区间改为拼接，诊断整体在 `try/except` 内并记为 `diagnosticFailed`（同时保留 `readInterval`），主断言不再受诊断影响：


1. `packetProbe.keyframes >= 2` 且 `frames >= 10`、跨度 ≥2 s：发布路径已通，继续看 `program-track-controls`、`program-track-offset`、`program-publish-disconnect` 与 NSIS 安装回执是否齐全。
2. `packetProbe.keyframes` 为 0：编码器送出的 IDR 没有到达新客户端，对照编码器侧送出与 MediaMTX 交给新连接的首包，检查 IDR 与 SPS/PPS 在哪一段缺失（例如是否需要 `repeat_headers`），再决定改产品还是改探针。
3. 有关键帧包但 `frames` 仍为 0：参数集没到解码器，或 `unparsableStamps`/`stderrTail` 指向具体解码失败；不要靠加长窗口通过。
4. `firstDecodableFrameMs` 明显大于窗口长度的一半以上：把它和 `windowTimedOut` 一起读，区分“等到下一个 IDR”与“根本没等到”。


### rc.64 起：Program 输出后混音辅助进程的归属 / mixer helper ownership since rc.64

rc.64（run 44548882087）通过 49 项后停在 `program-publish-disconnect`：`stopping Program output changed the Scene audio mixers ([5092, 6176] -> [6176])`，同轮 OBS 日志里混音媒体源 `Disconnected. Reconnecting` 9 次、`MP: Failed to open media: tcp://127.0.0.1:<port>` 8 次。rc.65（run 44557855349，源码 `8603c025`）带的是身份观察：每个 FFmpeg 子进程的净化命令行、宿主 `audioSources` 声明、以及阶段开始/停止前/停止后三次采样；它仍在同一断言处失败，而门禁步骤失败后作业只剩恢复与安装步骤会运行、回执上传步骤不会执行，所以该轮没有可下载产物，已在恢复步骤中取消，把时间留给带端口归属与收敛断言的下一轮。读身份观察时按这个顺序：

1. 先看丢失 PID 的身份：含 `amix` 与回环监听地址的是混音辅助进程；含 `-i <private>/*.mkv` 且没有回环端口的是 `product_output.cpp` 在录像收尾时启动的一次性重混子进程。后者正常退出不是产品缺陷，而是原 PID 集合断言多计了一个非混音子进程。
2. 再看它是在停止之前还是之后消失：`gone before the stop` 非空说明问题发生在推流/中继阶段，而不是停止 Program 输出时。
3. 再看宿主声明：`available` 仍为 true 而该进程已经不存在，是产品没有察觉辅助进程退出（监督缺口）；`available` 为 false 且带 `processExitCode`，是产品在如实报告失败。
4. 同轮 `fixturePublishers` 与 `currentBootObsMarkers` 用来排除夹具侧断流；不能把夹具断流当成产品混音缺陷。

从 `c6ffb7f` 起，宿主在 `audioSources` 行里给出该混音监听的回环端口 `mixerPort`，门禁把命令行里的回环端口保留为 `tcp:<port>`（远程端点仍整体脱敏），`otherHelpers`（无端口的一次性子进程，如录像收尾重混）单独记录，每次采样同时记录 harness 回环发布进程状态，避免把夹具断流算在产品账上。从 `89fe334` 起断言改为按同一时刻比较：每次采样要求宿主声明的每个混音端口都有存活辅助进程，停止 Program 输出后 40 秒内收敛到“存活端口多重集等于声明端口集合”，并把 `mixerPortSettleMs`、`sceneAudioMixerPids` 落进回执。复核 rc.64 现场（宿主只声明 1 条混音、当时也只有 1 个存活辅助进程）说明消失的 PID 属于正在释放的上一版 Scene 图，跨阶段 PID 差会把这种正常释放判为失败；收敛窗口只容忍这种释放，不允许宿主声明的混音长期没有辅助进程，也不允许辅助进程超出其混音源存活。

从 `329178b` 起，端口在截断之前读取：`mixer_identities()` 返回 `{identity(160), tail(80), port}`，端口来自掩码后的完整命令行，而不是被截断的显示串。真实混音命令行约 485~509 字符、回环目标 `tcp://127.0.0.1:<port>?listen=1` 落在末尾，若先截断再解析，每个存活混音都会返回 `None`、`watched_ports()` 为空，收敛断言会把正常服务的混音报成“声明端口没有辅助进程”。读收敛失败回执时先看 `processes[].port` 是否全为 `null`：全为 `null` 说明是门禁读法问题，此时 `tail` 里仍有 `tcp:<port>` 可核对；端口确实存在而声明端口无人服务，才是产品侧混音监督缺口。

从 `0874fd4` 起，混音观察返回它写入 `audioMixHelperWatch` 的回执行，不再是辅助进程 PID 列表；`watched_ports()`/`claimed_ports()` 会先断言收到的是行。读法：若某轮在 `program-publish-disconnect` 抛 `TypeError: list indices must be integers or slices, not str`，那是门禁把 PID 列表当成了回执行，不代表混音失败；先看 `audioMixHelperWatch` 各行是否已经记下 `processes[].port` 与 `hostClaims[].mixerPort`。rc.67（run 44568325933，源码 `c29227a8`）正是这种读法：49 项通过、端口已读到（start `51078`/`51389`，停止前后 `51389`）、宿主唯一声明的混音 `mixerPort=51389`，按收敛规则本应判为通过。

在 Fedora 里用脱敏回执复跑混音端口结论（不需要 Windows）：容器 `v51qt`（fedora:44）把根 checkout 挂在 `/src`，但 `.worktrees` 在容器内不可读，因此要先把测试目录复制进 `/wt`。

```bash
podman exec v51qt bash -lc 'rm -rf /wt/native-host/tests /wt/native-host/scripts && mkdir -p /wt/native-host'
podman cp .worktrees/v51/native-host/tests v51qt:/wt/native-host/tests
podman cp .worktrees/v51/native-host/scripts v51qt:/wt/native-host/scripts
podman cp <receipt>/native-product-entry-ui.json v51qt:/wt/rc67-entry-ui.json
podman exec v51qt bash -lc 'cd /wt && python3 -B native-host/tests/test_build_contract.py -k mix'
```

再用回执里的 `audioMixHelperWatch` 各行直接调用 `watched_ports()`/`claimed_ports()`：每个采样都要求声明端口无人服务集合为空，停止 Program 输出后要求存活端口等于声明端口。rc.67 的脱敏回执在这一步给出 `live=[51078,51389] claimed=[51389]`（首采样，游离辅助进程属于正在释放的 Scene 图）与停止前后 `live=[51389] claimed=[51389]`，结论为收敛通过，说明该轮失败只来自门禁把观察返回的 PID 列表当成回执行。

### rc.68 起：音调幅度按短段带宽测量 / tone amplitude is measured per short band segment (since rc.68)

rc.68（run 44577184643，栈顶 `2c0e99d`）49 项通过，首个失败点是 `program-track-controls`：
`the unchanged gain configuration measured differently twice: {'440': 0.58, '880': 0.359}`。
同一份未改动的增益配置两次录制却测出不同幅度，说明失败在测量而不是产品。本机用真实
FFmpeg（ffmpeg 8.1.3）把录制形状回放出来：混音重采样带漂移校正，流抖动时还会交接一个被
丢弃的音频块，因此文件里的音调不是同一段连续相位。对整窗做一次性投影，读到的是各段投影
之和：在 1.2 s 处丢掉 40 ms，440 Hz 的读数从 2890.0 掉到 991.3（比值 0.343）、880 Hz 掉到
0.814；偏离标称 0.4 Hz 时比值 0.286。两个音调在同一处时间断裂下的比值比（0.359/0.58 ≈
cos(2·比值差)）也正好符合丢弃约 30 个采样造成的相位旋转，而不是 400 ppm 以上的时钟漂移。

从 `768fa07` 起，`pixel_windows.pitch_projection()` 给出幅度和诊断：把窗口切成 0.5 s 短段，
每段在 ±1 Hz 带宽内取最强投影，再取各段的**平均**。三点理由：平均（不是中位数）保证窗口
内的静音仍按静音比例低估，rc.59 的 lead-in 保护仍然有效；真正更安静的窗口仍测得更低；
每个测量音高的 `peakHz` 与 `segmentAmplitudes`、`weakestSegment` 都落进回执，所以真实的
丢包仍然看得见，只是不再让读数塌陷。验收阈值一字未改（可闻 >200、缺失 <60、
增益比值 0.05–0.55、未改音轨比值 0.6–1.5、对照比值 0.8–1.25）。增益对照的测量证据现在写在
断言之前，rc.68 那次失败只在断言文本里留下两个比值，回执里没有可复核的幅度、窗口与分段。

读法：`programTrackGain.toneReadings.reference|repeat|reducedToneReadings`。若两个参考窗口的
`peakHz` 都停在标称值而比值仍偏离，才是真实的电平漂移；若 `weakestSegment` 明显低于
`amplitude`，说明该窗口里有一次音频交接断裂，属测量可见的正常抖动，不应当成产品缺陷。
本地回归在 `native-host/tests/test_pixels.py` 的 `AudioWindowContractTests`（真实 FFmpeg，
Fedora 可跑）：丢弃块对照、偏离标称的音调、相邻音高仍判为缺失、回执形状；把
`pixel_windows.py` 换回修复前版本会分别得到 0.343、0.286 与 `toneReadings` KeyError。

### 公开仓库审计：测试夹具里的 RTSP  userinfo 必须登记 / test fixtures must declare their RTSP userinfo

`public-audit` 的 `Audit and build the public PWA` 步骤用 `git grep --cached` 扫
`rtsps?://[^space/@]+(:[^space/@]*)?@`，命中项必须在 `tests/run-public-audit.sh` 与
`tests/run-public-audit.ps1` 的允许列表里按 `path|userinfo`（sh）或 `path -> userinfo 列表`（ps1）
登记。混音辅助进程夹具需要携带 userinfo 才能证明净化器真的剥离凭据，因此从 `e5a87b0` 起
用仓库既有约定 `fixture-user:fixture-password` 加 TEST-NET 文档网段 `192.0.2.9`，并登记该
引用；未登记会让 #67/#70/#71/#74/#75/#76 的 PR 检查全红并阻塞合并。本机复跑该规则：
在目标 worktree 里按同一 pattern 与允许列表比对，输出应为 `RTSP AUDIT OK`（注意 `git grep
--cached` 读索引，改动要先 `git add` 才能复跑）。

当前轮：`5.1.0-rc.69`（run [44587525224](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44587525224)，派发栈顶 `e955d9ea5d7947917a4a85292b923c5e91afc6f6`，`soak_minutes=0`；监视日志 `/tmp/watch69.log`）。上一轮 `5.1.0-rc.68`（run [44577184643](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44577184643)，派发栈顶 `2c0e99dc04a81fd8d92f878a5e2f6da682507420`，`soak_minutes=0`）。rc.69 是 v5.1 里第一次可能真正运行 NSIS 安装态脚本（`installed-ui`、`nsis`、`restore-pair`、`legacy-import`、`lan`、`updater`、`upgraded-ui`）：门禁步骤失败时该步骤不会运行，本机也没有 PowerShell 可预解析，只能静态核对被调用的 Python 文件与其参数。NSIS 安装步骤只在门禁步骤成功时运行，所以本轮也是第一次可能取得安装态回执（`installed-ui`、`nsis`、`restore-pair`、`legacy-import`、`lan`）。只有 TAKE、发布视频、逐轨增益与完整 NSIS 在同一轮齐全，才推进合并与冻结候选；若某声明端口仍无存活辅助进程，才在产品侧补混音监督（在同一端口重新拉起并保持源设置），并让断言继续覆盖重复与游离辅助进程。

## 4. 全栈通过后走到成品

| 次序 | 要完成的动作 | 可接受的证据 |
| --- | --- | --- |
| 1. 安装态 | 同一完整候选跑便携、NSIS、升级入口、ONVIF、LAN、成对恢复和导入。 | 回执匹配源码与版本。成对恢复使用普通启动入口。旧数据导入覆盖账户权限、保留链接及失效旧会话。LAN 记录 `lanHttpsQualified` 和 `remoteDeviceQualified`，无私网地址的降级保留原因。 |
| 2. 归并 | 按实际依赖顺序将 PR 转向 `dev` 并合并，保留双语标题和正文。 #69 同步 #67/#68 内容后重新跑发布链；#73 最后填实际回执。 | PR 最新 HEAD 检查、合并后的 `dev` SHA、修改后的最终工作流。堆叠快照仅作为定位起点。 |
| 3. 完整功能 | 用 [功能矩阵](../windows-native-feature-parity.md) 和实际入口逐项补产品能力并关闭对应任务。覆盖场景编辑、投影、NVR 回放/证据、LAN/离线、检测、事件及可选组件。 | 可从已安装应用运行的操作，以及与该能力对应的动态证据。旧版本人档案和真实设备留给目标机确认。 |
| 4. 冻结 | 从已集成源码派发 `product_mode=true complete=true soak_minutes=120`，按发布脚本要求设置明确的候选 `update_feed`。 | `v51-ci-gate.py --freeze` 的结果、安装长稳回执、同源 NSIS/更新回执、体积拆分。确认五路始终推进，附完整进程树 CPU、内存和句柄。 |
| 5. 候选 Release | 用现有 `publish_candidate.py --verify-only` 校验实际候选，再按已授权流程上传 GitHub prerelease，把下载链接交给用户。 | 源码 SHA、安装包字节与哈希、`latest.yml` 值、安装与回滚说明、候选验收缺口。 |
| 6. 正式版 | 完成用户目标机的真实五路 H.265、个人旧档案、物理多屏、实际音频和 OBS 同条件性能，再走审阅的 `dev → main` 发布 PR。 | Windows x64 正式 `v5.1`、真实验收回执、稳定更新元数据。历史 v4.5/v5.0.0-rc.1 附件保持原样。 |

完整产品工作流中的覆盖升级使用同源 `rc.N → rc.N+1` 夹具，若需上一公开安装包的升级证据，单独用真实公开包和隔离档案验证。`measure_obs_baseline` 和 `upgrade_previous` 两个输入在该工作流只触发原型路径。完整产品体积报告读取固定 OBS 安装参考值。Windows 目标机性能另做同条件 A/B，记录五路相同流、布局和帧率，以及 CPU、内存、Intel/NVIDIA 的 Video Decode/3D/Copy 和显存。Windows 托管 runner 的合成结果用于开发验收。

## 5. 每轮交接模板

```text
任务 / Agent ID / worktree / 完整 SHA
候选版本 / Windows run ID / CI 状态
第一失败阶段 / 证据文件 / 实测数值
本轮假设 / 做了什么 / 测试通过、失败或跳过
账本更新 / 下一条可以执行的命令 / 需要的外部条件
```

一次做完有证据的一步。更新账本用自己的唯一 ID。派发前检查已有进行中的 run，避免给同一个 SHA 重复派发同配置。暂停时先落账本，使下一次会话能够用同一个 task ID、完整 SHA 和 run ID 接着做。
