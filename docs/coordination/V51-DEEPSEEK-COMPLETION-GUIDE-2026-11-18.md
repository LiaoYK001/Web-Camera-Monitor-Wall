# DeepSeek 执行手册 · 从当前分支完成 Windows v5.1

2026-11-18，Asia/Shanghai。用户把本手册交给你后，从当前提交继续开发，完成 Windows x64 WebOBS Wall v5.1。先解决已经定位的 Windows 音频回归，再把合成输出及剩余业务做成一个能安装、能迁移、能长期使用的产品。内部构建和合成媒体回归由开发侧完成。用户将用冻结后的 v5.1 完整候选集中验证本人旧数据、真实相机和目标机体验，之后走正式发布流程。

## 1. 先用十分钟接上当前现场

| 工作 | 交接时核对到的证据 | 接续位置 |
| --- | --- | --- |
| 安装、迁移、更新、投影位置 | PR #65 已合入 `dev@07c4be0`。内部 rc.16 在 `472f3fe` 上通过便携／安装后／升级后各 55 项、恢复隔离 9 项。升级使用同源码下一版本夹具，实际执行更新器和 NSIS | [PR #65](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/65) · [Windows 44194328169](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44194328169) |
| 多轨声音 | PR #66 对 `dev` 开放，`44ce627` 的 rc.23 已结束，真实产品 UI 步骤失败；完整回执已可读，具体原因见下一节 | [PR #66](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/66) · [Windows 44224335029](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44224335029) |
| Program 输出、托盘、备份、支持包 | PR #67 堆叠于音频分支，远端 `c3f8e52`。rc.24 最后复查时产品 UI 步骤已失败，独立的恢复隔离步骤仍在执行，等日志确认具体断言。输出工作树本地 `2c64a5a` 比远端多一份文档提交 | [PR #67](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/67) · [Windows 44224358528](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44224358528) |
| 发布 | v5.1 未发布，历史 v5.0.0-rc.1 是预发布，当前 GitHub Latest 为 v4.0 | [Releases](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases) |

共享账本在 `/home/czl/projects/monitor_wall_czl` 根目录。它所在的 `codex/windows-native-monitor@24fd012` 是旧代码，并带有既有协作改动。音频实际代码在 `.worktrees/v51-audio` 的 `codex/v51-r2-003`，输出在 `.worktrees/v51` 的 `codex/v51-r3-output`，两树检查时均无未提交修改。保留各工作树和本地文档提交。

先读根目录 AGENTS、STATUS、TASKS、HANDOFF、DECISIONS 和 PLAYBOOK。R2-003 的当前账本负责人是 `codex-v51-continue-20261117-01`。原会话可按原认领继续；新会话按协作规则与原负责人交接，再用自己的唯一 ID 认领。V51-002 已完成，保留它的验证。共享账本通过根目录脚本更新，生成页由脚本维护。日志有时落后于正在跑的 CI，始终同时核对提交 SHA、实际日志和账本。

```bash
cd /home/czl/projects/monitor_wall_czl
git worktree list
git -C .worktrees/v51-audio status --short --branch
git -C .worktrees/v51 status --short --branch
python3 scripts/agent-sync.py check
gh pr view 66 --json headRefOid,baseRefName,state,statusCheckRollup
gh pr view 67 --json headRefOid,baseRefName,state,statusCheckRollup
gh run view 44224335029 --log-failed
gh run view 44224358528 --json headSha,status,conclusion,jobs
```

## 2. 第一件改动 · 修正 rc.23 的来源匹配，再证实多轨

### 已定位的失败

rc.22 的回执音量停在 `-120 dBFS`。rc.23 包含 `44ce627` 的 OBS 电平单位修正。其失败回执已经显示下列状态。

```text
failurePhase = native-program-take
lastCheckpoint = program-take-committed
programSceneId = fixture-alt
programApplyState = applied
program.mediaSources = 2
audioSources[0].sourceId = fixture-alt.fixture-alt-source
audioSources[0].available = true
audioSources[0].peakDbfs ≈ -20.87
audioSources[0].mixers = 2
```

`native-host/tests/product_windows.py` 在 `program-take-committed` 后的等待条件要求 `sourceId == "fixture-alt-source"`。运行态实际返回 `fixture-alt.fixture-alt-source`，来源由 `core/src/studio_document.cpp` 展平场景时生成，随后经 `product_scene.cpp` 和 `product_window.cpp` 写入状态。当前回执已显示 Program 切换和可测音频信号，**这个来源 ID 比较足以让整条等待条件超时**。已对 rc.23 脱敏回执重新求值，原短 ID 条件为假，仅替换成完整 ID 后条件为真，Program、来源可用性和峰值等条件均保持。这需要在修正后的 Windows 运行中复验。

### 改动和验证顺序

1. 在音频分支修断言。对这个固定 fixture 精确匹配 `fixture-alt.fixture-alt-source`，或从已验证的运行态场景绑定取得该 ID 再精确匹配。保留 `available` 和峰值条件。短 ID 后缀匹配和“任意来源有声音”都会掩盖串源。产品运行态 ID 也应继续区分不同场景的同名来源。
2. 将等待分成**切换已生效**、**指定混音源出现**、**指定源有非静音信号**三个检查点。失败记录阶段、预期和实际 ID、峰值、混音进程状态、OBS 媒体状态与总线。日志下次就能区分是 TAKE、来源、传输还是声音；回执只带合成夹具及脱敏诊断。
3. 继续原来的 `/api/v1/studio/runtime` revision 回执、切前切后像素和源退役检查。对新 SHA 运行 Windows 产品流程，核对便携、安装后和升级后实际经过新断言。旧 run rerun 仍使用旧提交。
4. 一个峰值只能证明至少有信号。给双轨夹具使用可区分的频率或节奏，在 Program 拉流或录制产物中解码音频验证两路。做逐轨静音、增益和可区分的偏移正反对照。若要复用既有工具，先读 `tests/rtsp-fixture/probe-audio.py`、`tests/run-m5-real-audio.ps1` 和 `tests/scenes/m5-audio-*.json`。采用合成音源和实际解码结果，避免把 UI 布尔值当成音频证据。
5. 分开验证三种配置：省略 `audioInputs` 的旧行为、显式空数组的静音行为、非空的逐轨混音行为。验证缺失轨给出明确错误，检查监听与输出设置各自生效，切场景／撤权／注销后释放混音进程。相同账号和相同配置下多个视图共享来源，不要产生重复扬声器输出。

若修正 ID 后仍无信号，按下表排查。一次变更对应一条可证伪假设，先用短小的合成媒体探针，再用完整 Windows 测试确认。

| 观察 | 先查的实际边界 | 能确认结果的证据 |
| --- | --- | --- |
| fixture 的 RTSP 上没有两轨 | `pixel_windows.py` 有文件生成和 RTSP 发布两段，分别探测文件和 **RTSP endpoint** 上的流 | 两处都列出预期音轨，样本能解码；文件有两轨、RTSP 只有一轨时查发布映射 |
| 选轨成功但未送入 OBS | `product_scene.cpp` 的 FFmpeg 参数、进程启停、回环 TCP、监听与连接顺序 | 音频专用混音进程确实读取预期流，连接建立并交付连续音频；日志保留有界错误 |
| OBS 源存在但没有节目音频 | 区分 `available` 的进程状态、OBS media state、volmeter 回调和实际下游编码 | 在源进度确认持续信号，再在目标输出中确认正确音轨；选用实际 dBFS 单位 |
| 多窗口或切场景时双声、断声 | 原视频源是否同时送音、共享键包含哪些音频配置、旧图与混音进程释放时间 | 两视图不会重复输出，同一来源配置更改后旧声停止，输出随新 Program 有序切换 |

已有音频专用 FFmpeg 和 TCP 链路在 rc.23 测到了信号。先修断言，不要再次改 transport、改 OBS 渲染或把视频塞进转码器。独立音频拉流及其开销应纳入后续测量。

## 3. 第二件改动 · 在 Program 产物上验证音轨和托盘

先读取 #67 的 rc.24 回执。若它在音频断言处失败，将经验证的 #66 修复带入 #67 后再复跑。#66 通过后正常合入 `dev`，把 #67 更新到最新 `dev` 并改目标到 `dev`，确认 diff 只含输出等对应变更。保留本地 `2c64a5a` 文档提交和其他会话的提交。整轮绿色后再按对应证据合并。

- **先查一个实际音轨接线缺口。** rc.23 fixture 用 `audioTrack: 2`，回执显示 `mixers=2`，对应 OBS 第二总线。当前 `product_output.cpp` 的 AAC 和 Opus encoder 创建都传入零基 mixer `0`。这在非默认总线配置下可能出现“电平有信号、录制／推流静音”。用默认总线和非默认总线两组真实输出复现，按旧产品的输出轨规则或明确的输出配置选择总线，再在产物解码确认；不要迁移用户轨道来配合测试。源电平和输出有音轨头都不能替代可听样本。
- **合成录像。** 复用 `ProductProgramOutput` 和 OBS encoder／muxer。Start → TAKE 或转场 → Stop → 从输出目录打开，检查实际 H.264 动态帧、所选节目音轨音频、时长和完整封装。观察临时 MKV 到 MP4 的流复制，测试只读目录、空间不足、停止失败、进程中断。保留可恢复的原始录像并显示错误。现有同步等待与 remux 也要观察 UI 是否长时间无响应。
- **WHIP。** 复用已接入的原生输出和私有 MediaMTX。在隔离 Windows 上验证输出启动后能从已配置的回环读取端解码真实视频帧和 Opus 信号，切换 Program 可观察到新内容。停止、断线、端口冲突、撤权和退出均有明确结果。无消费者／无输出任务的本地监看不应启动编码器或 MediaMTX。
- **托盘。** 活动录像或推流时关主窗，后台仍有输出和音视频；从托盘重新显示，不创建第二宿主或重复启动输出。普通退出、显式停止退出、会话被撤销和宿主崩溃分别验证。再验证 NVR／远端消费者与本地托盘的实际语义，不能从“Program 录像时能隐藏”推出全部后台场景合格。
- **已知编码配置。** 当前合成输出用 x264；用与 Program 相同的 CPU/GPU 口径测它。基础监看保持直接 RTSP。若有必要支持 OBS 原生硬件编码，按实际可用性和失败行为验证，不把硬件编码等同于摄像机硬解。

主要文件为 `native-host/src/product_output.cpp`、`native-host/src/product_window.cpp`、`native-host/tests/product_windows.py`。实际音轨、文件、可解码流、背后进程和退出后的清理应有同源码回执。

## 4. 把其余功能做成安装后的操作路径

以 [原始完整任务书](../windows-webobs-wall-release-plan-2026-11-11.md) 和实际代码树功能矩阵为范围。优先复用旧业务服务和现有管理页，把每项做成可从桌面到达、保存、重启可恢复、可卸载的用户操作。依账本认领修改范围，同一文件有重叠工作时串行协调。

| 任务 | 从哪里接入 | 交付前怎样验证 |
| --- | --- | --- |
| R2-002 场景编辑和嵌套 | 现有 Web Studio 工作台、`core/src/studio_document.cpp`、原生 graph resolve/apply | 编辑嵌套、裁剪、层级、锁定及混合布局，重开后按 ID 恢复；Preview 与 Program 分开，两个编辑客户端的 revision 冲突能提示，冲突或编辑不直接改变 Program；有实际动态像素 |
| R2-004 投影恢复 | `product_window.cpp`、`projector_placement.hpp`、账号工作区 | 同时保存固定 Scene 身份与每个窗口的几何偏好，登录且获授权后可恢复；已删除或无权场景不重新开媒体，同源重复投影不重复解码；用合成测试验生命周期，物理多屏、DPI 和睡眠唤醒纳入用户集中验证 |
| R3-001 设备操作 | 已安装的 camera 服务、相机目录/管理页 | 从普通安装进入相机操作，核对角色和相机权限；用可控设备/fixture 验证快照、预置位、PTZ 停止及对讲关闭后收尾；最后确认真实设备 |
| R3-002 NVR、回放、证据 | 已有 `nvr/`、`archive/`，`tests/test_nvr_media.py`、`tests/test_nvr_storage.py`、`tests/test_nvr_evidence_integration.py` | 原码流录制与 Program 合成录像各自可播放；检查计划、配额、多卷、掉盘、恢复、时间线 seek／Range 和导出内容摘要/审计，测安装态实际媒体 |
| R3-003 事件、检测、网站源 | 已打包的 events、analytics、go2rtc、锁定解析器，沿用网站源测试入口 | 事件订阅、持久 outbox、重启和选定实际通知目标；检测做最终叠层像素；网站做固定 relay 的受认证实际播放。自检只证明组件可启动。普通 RTSP 监看保持无需求不转码 |
| R3-004 远端与离线 | 以 `native-host/scripts/product_supervisor.py` 的现有 Composite 代理为起点，参考旧 `desktop/src/supervisor.mjs` 的 Origin 设置和既有 Caddy 配置。复用 `DeviceSyncPanel.tsx`、`useDeviceSync.ts`、`syncRuntime.ts`、`docs/offline-workspace.md` | Windows 安装后通过显式配置在受控网络用第二客户端验证 HTTPS 登录、Direct/Composite 实播、账号和相机隔离，以及远端退出不误停其他消费者。管理和内部媒体监听默认回环。用实际安装服务验证配对、断网编辑、恢复队列、冲突选择、显式复制到 Preview，保持 Program 内容不变；复用既有离线浏览器用例 |
| R3-004 诊断 | #67 的原生支持包与已有 Problem Center | 验证普通用户/管理员权限、文件大小边界、合成数据中的 URL/令牌/路径标记不出现在导出；必要故障能从可见入口定位，不输出真实私密日志 |
| R4-001/002 数据和生命周期 | 已合并的迁移器、已安装更新器、#67 的双目录加密备份和托盘 | 在隔离 Windows 分别升级受支持的 4.x、v4.5、上一个 v5.1 候选；覆盖账号、设备、Scene/Studio、音轨、工作区、录像索引与路径、密钥和重试。检查新 `config` 与 `native-profile` 都被备份/恢复，旧 config-only 备份仍可用；测试断网、截断、不足空间、更新失败保留数据。最后拿本人档案副本集中验证 |

特别关注“双目录加密备份”的一致性。查看 `backup/encrypted_backup.py` 的备份／恢复流程和 `tests/test_encrypted_backup.py`。测试在两个目录转换的中间步骤故障后依旧能恢复到一致旧状态或安全重试。按 SDK／架构版本正确选择组件，实际程序须经用户确认后更新。开发验收使用隔离目录、合成数据和测试账户。

## 5. 把 Windows 时间花在有诊断价值的运行

1. 先跑本机可验证的命令与相应测试。共享脚本 `agent-sync.py check`、代码树 `git diff --check`，Web 改动跑 typecheck/build 和对应 Playwright。迁移与升级复用 `test_migrate_legacy.py`、`test_native_updater.py`、`test_upgrade_runtime.py`、`update_windows.py`；视频和 UI 复用 `product_windows.py` 及当前 Windows 主流程。
2. dispatch 前记录分支、完整 SHA、版本、待验证的失败点。上一 run 已能提供结果时先读它的回执。部分阶段成功照实记下，失败要落到具体断言或状态。网络／runner 失败才对同源码重试；逻辑失败修好后用新 SHA。带有产品变更的 head 须通过匹配的实际 Windows 检查。
3. 现有独立完整工作流为 `windows-obs-native-host.yaml`，输入 `product_mode=true`、`complete=true`、`native_preview=false`、`pixel_test=false`、`version=5.1.0-rc.N`。取当前未占用的内部编号并确认远端 head，不能从高编号推断已成熟。候选更新源沿用固定 Tag 的测试入口。内部 workflow artifacts 可由 Agent 取回验收，用户最终下载用 GitHub Release。
4. 每次把最小证据写到统一账本。格式用“任务 ID / SHA / 版本 / run / 具体运行步骤及结果 / 尚待验证对象 / 下一条命令”。正式冻结时看同一源码的完整回执。修音频断言时可以核对现有回执和局部复现，不需要给已知失败的旧提交再构建一套产品。

## 6. 性能、安装空间和最终测试

- **先做 Agent 可以做的长稳。** 用完整安装和固定合成五路 H.265 运行至少两小时，记录每路帧进度、CPU、私有内存、进程和句柄变化、混音连接数、Windows Job 清理。用同一个包在同样环境运行纯监看与音频／输出／远端等开启状态，记录增量。安排断流、重连、停止输出、切场景后重复测量。两小时长稳应有单独时间范围和采样效果，跑了一整天 CI 的累计时间没有这个意义。
- **量实际资源。** 普通监看复用一个 libobs/OBS 窗口系统，统计所有产品进程以及按需子进程的开销。保留 setup 文件字节、安装树 logical/allocation、首启数据、临时维护工具和可选组件增量。rc.16 基线约 212.2 MB 下载、794.6 MB 安装逻辑大小。用同口径量官方 OBS，再按清单查独立影音工具、浏览器及模型资源是否有可去重或按需安装的部分。可选功能留同机可用和离线安装办法。禁止以少显示一路、降低分辨率/帧率、静音换指标。
- **准备 RTX 4090 显卡对照。** 目标机为 i9-13900HX / RTX 4090 Laptop。使用同五路真实 H.265、同画布/FPS/音轨/可见窗口与 OBS 原生预览或投影。两边分次运行，不同时争用摄像机和解码器。采集全产品树 CPU、各 GPU 引擎的 Video Decode/3D/Copy、私有内存和掉帧；区分渲染适配器与解码适配器。参考 [采集工具说明](/home/czl/projects/monitor_wall_czl/.worktrees/v51/native-host/qualification/README.md) 及 [目标机手册](/home/czl/projects/monitor_wall_czl/.worktrees/v51/docs/windows-target-qualification-runbook.md)。现有轮询采集明确是进程树下界，只有覆盖足够的同机证据才能判断是否 ≤ OBS。
- **集中交付用户的版本。** 先关闭能在 Agent 或 Windows CI 上解决的功能与缺陷。冻结一份明确 SHA、安装器摘要、安装/升级记录的完整候选，附本人旧档案备份/回退、五路显示、实际声音/多屏/设备、长稳和同机对照的短清单。确认缺陷后修复并有针对性地复验，候选有变更时重新绑定用户所测的实际文件和证据。

## 7. 正式 v5.1 发布怎么收口

1. 按 [发布流程](/home/czl/projects/monitor_wall_czl/.worktrees/v51/docs/release-flow.md) 和 [版本规则](/home/czl/projects/monitor_wall_czl/.worktrees/v51/docs/versioning-and-branches.md) 核对目标。准备 `dev → main` 的双语指定版本 Release PR，提交实际功能、数据、媒体、安装/升级、长稳和目标机证据。只发布 Windows x64，Android/容器保持暂停。
2. **预备脚本还要对齐。** #67 加了可移植 `native-host/scripts/publish_candidate.py`，但其当前 final 路径简单拼 `"v" + version`，会算出 `v5.1.0`。仓库功能版本规则为 **Tag `v5.1`，应用/安装器版本 `5.1.0`**。同时现行原生构建策略仍主要接受 rc 版本。正式打包前补齐稳定模式、Tag／版本映射、稳定更新元数据与对应测试，校验构建来自已审查的 `main` 提交。准备候选或草稿时保持预发布和正式更新通道的边界；候选脚本的参数能执行并不代表稳定链已验证。
3. 绑定最终安装包名/字节/SHA-256、`latest.yml` SHA-512 和 size、实际 NSIS 安装回执、源码/依赖 manifest、SBOM、许可证和匹配第三方对应源码。检查版本化 Tag 与提交、稳定元数据下载和旧版本升级。若正式候选经过重建，重新验证该文件，不沿用另一包的摘要或安装结果。现有未签名发布按项目规则标明。
4. 先核对现有 Tag、Release 和草稿，保留已公开 v4.5 及 v5.0.0-rc.1。按审查后的发布流程上传并在公开后抽查实际下载、摘要和更新入口。向用户提供 GitHub 下载、版本、摘要和升级/回退，标明仍未测的平台或条件。源码可编译、普通 PR 绿灯、创建 Release 草稿和公开正式包是不同交付节点，逐项以真实结果更新账本。

下一条可执行动作是打开 [rc.23 失败日志](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44224335029)，修正夹具来源 ID 并拆清三个断言。验证逐轨声音后推进 Program 实际录像／推流，然后按第四至第七节持续完成 v5.1。
