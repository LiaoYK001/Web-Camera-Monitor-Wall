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
