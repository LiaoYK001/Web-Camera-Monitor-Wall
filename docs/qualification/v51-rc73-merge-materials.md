# v5.1 rc.73 合并材料 / v5.1 rc.73 merge materials

> 会话 Agent ID：`qwen38-next-v51-20261120-02` · 任务 V51-008 · 状态：待回执齐全后交 Codex 主线程审阅，本会话不自行合并或发布。
> Session Agent ID `qwen38-next-v51-20261120-02`, task V51-008. Status: hand to the Codex main thread for PR integration once receipts are complete; this session does not merge or publish.

## 被测候选 / candidate under test

- 版本 version: `5.1.0-rc.73` → `5.1.0-rc.74` → `5.1.0-rc.75` → `5.1.0-rc.76` → `5.1.0-rc.77`（同 SHA 复现性轮）→ `5.1.0-rc.78` → `5.1.0-rc.79`（同 SHA 复现性轮）→ `5.1.0-rc.80`（同一栈顶分支 `codex/v51-r4-legacy-import`，PR #76）
- rc.73 源码 SHA `28c338840d5e5687ef4231885a70c3386f2cfdc8`，run [44718717601](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44718717601)（inputs `product_mode=true complete=true soak_minutes=0`）：**completed=failure**。Program 增益首次通过（controlRatios 440=1.004/880=0.998；880 降增益 585.9/3068.2≈0.191；逐段 peakHz 全部标称）；首个真实失败点为 `backup_restore_windows.py:319`「the installed entry left the native-swap journal behind」——归因为装置侧竞态（第一次启动遗留的 native-status.json 带 phase=running+旧 bootId，被 100ms 首个 tick 接受），产品收敛代码覆盖被杀窗口，非产品缺陷。test-only 修复见下。
- rc.74 源码 SHA `0bd1a2943dd2234e35194819aa80eadaa7ee7f0f`（含修复提交 `0bd1a29`），run [44728029615](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44728029615)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44728029615 --sha 0bd1a2943dd2234e35194819aa80eadaa7ee7f0f --version 5.1.0-rc.74`：**completed=failure**，Program 增益再次通过（controlRatios 440=0.976/880=0.938；880 降增益 611.8/3057.8≈0.200）；第二次安装态启动竞态修复生效，门禁推进到 `backup_restore_windows.py:390`「the refused paired restore leaked staging directories」（回执 phase 字段停留在 `interrupted-restore-pair-recovery` 仅为 checkpoint 滞后，traceback 行号才是首个失败点）。归因为装置记账缺陷：成对档案拒绝在自己的 `.webobs-decrypt-` TemporaryDirectory 内抛 `BackupError`，不可能新建暂存；失败实际记的是早前两次被 `TerminateProcess` 硬终止的恢复遗留的明文解密暂存（硬终止跳过上下文管理器清理，`recover_interrupted()` 只删除 journal 记录的暂存）。test-only 修复 `9b26035`（拒绝前快照暂存名单、只对拒绝新建目录记账、回执披露遗留项）。
- rc.75 源码 SHA `9b260351368770eec6e81458c9c50f1886e47d71`（含 `9b26035`），run [44735378274](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44735378274)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44735378274 --sha 9b260351368770eec6e81458c9c50f1886e47d71 --version 5.1.0-rc.75`：**completed=failure**，`9b26035` 生效、门禁首次越过 legacy-config-only-archive；Program 增益复过（controlRatios 1.0/1.001）。首个真实失败点为安装入口 program-streaming 视频窗口断言（26 帧/0.833 s span、首帧 4015 ms）；归因：同窗口宿主渲染 +421 帧、`streamConnected=true`、包连接 2 个 IDR@2.0 s，OBS 日志 6 次 `WebOBS async video backlog`（30 帧丢弃、间隙 2.689–3.000 s）与 1 次 async timestamp jump——单消费窗口与输入侧解码停滞竞态，属 rc.62 已记录的交付 vs 解码分裂，非产品逻辑缺陷。test-only 修复 `9c2b7af`（共享 `decodable_window` 谓词、一次新连接有界重读、只对最后尝试记账、`probeAttempts` 披露；持续饥饿仍两次失败）。
- rc.76 源码 SHA `9c2b7afbb90ce6d4a2886730d9d2ba610ae52ef0`（含 `9c2b7af`），run [44746006213](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44746006213)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44746006213 --sha 9c2b7afbb90ce6d4a2886730d9d2ba610ae52ef0 --version 5.1.0-rc.76`：**completed=failure**，`9c2b7af` 生效（视频窗口首轮 healthy 100 帧/3.3 s、无重试），entry-ui 首次推进过 program-streaming 与全部录制检查（48 checks）；随后在 `program-publish-disconnect` 出现**真实前端崩溃**（见披露节），门禁中止于该阶段，NSIS 与后续步骤未运行。
- rc.77 复现性轮：同一 SHA `9c2b7af`、同一输入（无代码改动），run [44751520752](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44751520752)。门禁 gate: `python3 scripts/v51-ci-gate.py 44751520752 --sha 9c2b7afbb90ce6d4a2886730d9d2ba610ae52ef0 --version 5.1.0-rc.77`：**completed=failure**，但**未到达 `program-publish-disconnect`**——更早失败于 `native-program-take`：main-preview 八个采样的第 0 个捕获 CUT TAKE 后墙格子重绘中途的变暗旧帧（`Wrong channel 1 in tile 0: 62,30,30`），1-7 采样通道正确、计数器推进、`temporalProgress=true`、fixture publisher 全部存活、无停滞路径。崩溃面复现性因此**无结论**（既未复现也未干净通过该阶段），rc.76 披露保持开放。首个真实失败点归因为装置捕获竞态（rc.47/48/50 已记录的中途交换窗口）：捕获起点与重绘竞态、非产品冻结（同阶段 rc.73/74/76 通过）。test-only 修复 `9460829`（见下）。
- rc.78 源码 SHA `9460829eea3908d2145083c6d623e54f4f5f86d9`（含 `9460829`），run [44795726091](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44795726091)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44795726091 --sha 9460829eea3908d2145083c6d623e54f4f5f86d9 --version 5.1.0-rc.78`：**completed=failure**，仍在 `native-program-take` 但形态更持久：program-after-take 八个采样通道全部正确而计数器完全冻结（全 `[31,31,38,38,38]`、`distinctClientCount=1`、`temporalProgress=false`、`Frozen final pixels on slot 1`），同期宿主渲染计数 9923→10702（~30 fps）、六个输入 serial 全部 advance、fixture publisher 全存活、feed 解码探测 32-38 个不同帧、开渲染探针复测仍部分冻结（tiles 0,2,3 stale 而 1,4 更新）——帧已到源、宿主在渲染、fixture 无故障，唯窗口像素不重绘，属**产品侧预览重绘停滞**（真实用户可见，见第六披露项）。`9460829` 的首采样瞬态形态正确地未匹配、未触发重试，回执如实失败。连续两轮失败于该阶段（rc.77 瞬态、rc.78 持久），交 Codex 主线程做宿主侧诊断；本会话未改代码。
- rc.79 复现性轮：同一 SHA `9460829`、同一输入（无代码改动），run [44800953316](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44800953316)。门禁 gate: `python3 scripts/v51-ci-gate.py 44800953316 --sha 9460829eea3908d2145083c6d623e54f4f5f86d9 --version 5.1.0-rc.79`：**completed=failure**，但**entry-ui 首次全绿**（50+ checks 全部通过，含 `native-program-take` 与 `program-publish-disconnect`——rc.78 整窗重绘停滞与 rc.76 崩溃面均未复现，持续性/确定性均无结论，第四、第六披露项保持开放），installed-ui/size-split/restore 亦 passed=true；首个失败点首次推进到 `native-product-nsis` 的 `interrupted-restore-pair-recovery`：`backup_restore_windows.py:412`「a configuration-only archive could not be restored」恢复进程非 0 退出。本机 Linux 对 `backup/encrypted_backup.py` 确定性复现**产品缺陷**：`restore()` 把归档内 `backup-manifest.json` 落进配置根，下一次 `create()` 将该残留清单当用户文件打包，新清单按陈旧大小自指记录后被自身覆盖，`verify_tree` 从此必然失败——任何「先恢复、再打备份」的用户档案永久不可恢复（与 Windows 无关）。产品修复 `54df2e3`（`stage_tree` 排除根级清单；`verify_tree` 跳过历史自指条目，使已被旧代码污染的既有档案重新可恢复）。该轮不改动代码的复现判定已完成：重绘停滞未复现；缺陷修复后的复验由 rc.80 承担。
- rc.80 源码 SHA `54df2e35e814453f224325e278dbd9691e86e299`（含产品修复 `54df2e3`），run [44814303103](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44814303103)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44814303103 --sha 54df2e35e814453f224325e278dbd9691e86e299 --version 5.1.0-rc.80`。验证备份修复在真实安装态生效并继续推进 restore-pair/legacy-import/lan/updater/upgraded-ui；重绘停滞与崩溃面若再次命中按其披露项处理，不构成放行。
- 每轮派发前核对 `gh run list` 无更新/进行中 run，未重复派发。No duplicate dispatch.

## PR 堆叠与换基顺序 / PR stack and retarget order

实际关系以最新 `baseRefName`/`headRefOid` 核对（2026-11-20 快照，六层全部 CLEAN、检查全绿，`windows-desktop-candidate` 在 PR 检查中有意 skipping，真实 Windows 证据来自上面的 run）：

| PR | 分支 head | HEAD | base | 层级提交数 |
| --- | --- | --- | --- | --- |
| #67 | codex/v51-r3-output | `9ed32ae` | dev | 63 |
| #70 | codex/v51-r4-backup-consistency | `d5b0727` | codex/v51-r3-output | 5 |
| #71 | codex/v51-r3-004-lan | `6a7042a` | codex/v51-r4-backup-consistency | 12 |
| #74 | codex/v51-r5-soak | `f6cf429` | codex/v51-r3-004-lan | 4 |
| #75 | codex/v51-r3-005-devices | `f60aab8` | codex/v51-r5-soak | 1 |
| #76 | codex/v51-r4-legacy-import | `54df2e3`（原 `28c3388`→`0bd1a29`→`9b26035`→`9c2b7af`→`9460829`） | codex/v51-r3-005-devices | 10 |

换基合并顺序 / retarget order（每步合并后把下一层 base 改为 `dev`，核对换基后 diff 只含该层自身改动）：

1. #67 → dev（Program 输出/UIA 归因/夹具登记等，最大层）。
2. #70 → dev（成对备份交换与中断收敛 + updater 有界错误码）。
3. #71 → dev（LAN/Web 入口与安装态门禁）。
4. #74 → dev（两小时长稳门禁，本轮 soak_minutes=0 不启用）。
5. #75 → dev（设备操作安装态门禁）。
6. #76 → dev（旧数据导入安装态门禁，含 rc.72–rc.78 六个 test-only 修复 `a27a766`、`28c3388`、`0bd1a29`、`9b26035`、`9c2b7af`、`9460829`，以及 rc.79 的产品修复 `54df2e3`（`backup/encrypted_backup.py`：恢复后再打的备份可再恢复，并让已被污染的既有档案重新可恢复——主线程应重点复核这一处产品改动）；`0bd1a29`/`9b26035`/`9c2b7af`/`9460829` 属 V51-007 的门禁文件，知会仍待协调人转达——agent-sync log 对 V51-007 被拒，内容见 revision 289）。

并行注意 / parallel notes：
- #69（发布链）base dev：合入 #67 后 rebase，`publish_candidate.py` 为 add/add，保留 #69 的超集实现并复跑发布链测试（V51-005）；发布链只验证到待发布状态，不自动发布。
- #73（发布说明）base dev、当前 UNSTABLE：在候选回执齐后按 V51-012 填实际摘要，最后合入。
- 冻结候选（soak_minutes=120）在全部六层并入 dev 后从 dev 派发，按 runbook 第 4 节设置候选 `update_feed`。

## 本轮已提交的验收回执 / receipts required this round

安装态门禁要求同一 run 内 `native-product-integration-receipts-5.1.0-rc.N` 含以下全部 `passed=true` 且绑定源码 SHA/版本（`upgraded-ui` 用同源 `rc.N+1` 夹具版本，如 rc.73 轮为 rc.74、rc.80 轮为 rc.81）：

| 回执 receipt（rc.73 首轮结果 → rc.74 复验） | 含义 | rc.73 状态 | rc.74 状态 |
| --- | --- | --- | --- |
| entry-ui | 便携门禁（Program 输出全路径，含增益/偏移/断开） | passed=true | passed=true |
| restore | 备份恢复契约 | passed=true | passed=true |
| installed-ui | 安装态门禁（普通启动入口） | passed=true | passed=true |
| nsis | NSIS 安装/重装/成对恢复 | passed=false（restore-pair 竞态，装置侧已修） | passed=false（`0bd1a29` 竞态修复生效，推进至 legacy 阶段断言；失败为装置记账归因，`9b26035` 已修，rc.75 复验） |
| restore-pair | 中断成对交换经真实已安装入口收敛 | 未产出（NSIS 门禁失败，后续步骤未跑） | 未产出（NSIS 门禁在 legacy 阶段断言中止；其内成对恢复与第二次/第三次启动均已通过） |
| legacy-import | 包内旧数据导入（账户权限、保留链接、失效旧会话） | 未产出 | 未产出 |
| lan | LAN 入口（记录 lanHttpsQualified / remoteDeviceQualified / 降级原因） | 未产出 | 未产出 |
| updater | 更新器契约 | 未产出 | 未产出 |
| upgraded-ui | 覆盖升级同源夹具（rc.73 轮为 rc.74 版本） | 未产出 | 未产出 |
| size-split | 同源码组件体积报告 | passed=true | passed=true |

另需 `webobs-wall-complete-candidate-<version>` 安装包工件（rc.73 未产出）。rc.73 的 `native-product-nsis.json` 显示 `freshInstalledEntryQualified=true`、footprint/快捷方式检查全部通过，仅成对恢复第二次启动被装置竞态阻断。

rc.75 复验：entry-ui/restore/size-split passed=true；installed-ui（NSIS 流程中新安装入口内嵌运行写出的 `native-product-installed-ui.json`，13:25:45）passed=false，失败于 program-streaming 视频窗口（装置单窗口与输入侧解码停滞竞态，`9c2b7af` 已修）；nsis passed=false（phase `installed-entry-ui-and-media`，同一内嵌运行的级联）。nsis 门禁已越过 legacy-config-only-archive（`9b26035` 生效，legacy 阶段断言全部通过）；restore-pair/legacy-import/lan/updater/upgraded-ui 仍未产出（内嵌 UI 运行之后的阶段未跑到）。

rc.76 复验：restore passed=true；entry-ui passed=false——`9c2b7af` 生效（视频窗口首轮 healthy、48 checks 首次越过 program-streaming 与全部录制检查），checkpoint `program-publish-disconnect-reported` 已写出（中继被杀已正确上报），随后前端 0xC0000005 异常退出，回执如实记账该断言（见第四披露项），未做掩盖性修改；size-split/nsis/restore-pair/legacy-import/lan/updater/upgraded-ui 与安装包工件均未产出（entry-ui 失败使后续步骤未运行）。

rc.77 复验（同 SHA 复现轮）：restore passed=true；entry-ui passed=false——未触及 `program-publish-disconnect`（崩溃面复现性无结论，第四披露项保持开放），失败于更早的 `native-program-take`（第 0/8 采样捕获中途交换重绘帧，1-7 采样正确且进度已证实，见第五披露项，`9460829` 已修）；size-split/nsis/restore-pair/legacy-import/lan/updater/upgraded-ui 与安装包工件均未产出。

rc.78 复验：restore passed=true；entry-ui passed=false——同一 `native-program-take` 但为整窗持久重绘停滞（八采样计数器完全冻结、`temporalProgress=false`，而宿主渲染计数、输入 serial、feed 内容与 publisher 健康均正常，开探针仍部分冻结；见第六披露项，`9460829` 瞬态形态正确地未触发、未掩盖）；size-split/nsis/restore-pair/legacy-import/lan/updater/upgraded-ui 与安装包工件均未产出。

rc.79 复验（同 SHA 复现轮）：entry-ui passed=true（首次全绿，含 `native-program-take` 与 `program-publish-disconnect`——第四、第六披露项的两个失败面该轮均未复现，确定性均无结论，两项保持开放）；restore/size-split/installed-ui passed=true（installed-ui 自 rc.75 失败后首次通过，`freshInstalledEntryQualified=true`、footprint 6972 文件与快捷方式检查全部通过）；nsis passed=false——phase `interrupted-restore-pair-recovery`，`backup_restore_windows.py:412`「a configuration-only archive could not be restored」：中断交换两次硬杀、真实入口两次收敛、retry 全量恢复与成对拒绝断言全部通过后，**首个真实失败点为产品备份缺陷**——恢复把 `backup-manifest.json` 落进配置根，随后 create 把残留清单打包成自指条目（陈旧大小被自身覆盖），verify_tree 必然失败；Linux 确定性复现，产品修复 `54df2e3`（含历史污染档案兼容恢复）。restore-pair/legacy-import/lan/updater/upgraded-ui 与 complete-candidate 安装包工件仍未产出。

## 必须保留的已知缺口声明 / disclosed known gap（不得因本轮通过而关闭）

rc.72（run 44711476489）暴露的窗口：`backup/encrypted_backup.py` 中 `os.replace(activated, config_root)` 返回与记录 `nativeRollback` 的 journal `fsync` 落盘之间的微秒级崩溃窗口会真正丢失原生半区引用。`28c3388` 只是把测试哨兵挪到 journal 写入之后（test-only），产品恢复算法本身未改。**rc.73 该阶段通过不能证明该间隙安全**；该边界属产品恢复算法，已交 Codex 主线程复核（见 HANDOFF 2026-11-20 交接段与 DEVLOG `3a99fa4`）。合并材料不将其列为已解决。

The rc.72 finding stands: a crash between `os.replace` returning and the journal `fsync` that records `nativeRollback` can genuinely drop the native-half reference. `28c3388` moves only the test sentinel after the journal write; the product recovery algorithm is unchanged. A passing rc.73 gate does **not** prove the window safe — it stays open for Codex main-thread review.

第二个必须保留的披露项（rc.74 归因）：被硬终止（`TerminateProcess`/SIGKILL）的恢复进程会跳过 `TemporaryDirectory` 清理，把明文解密暂存 `.webobs-decrypt-*` 留在账户私有目录里；`recover_interrupted()` 只删除 journal 记录的暂存，从不清扫这个未记录目录，产品代码也没有任何其他路径会移除它。也就是说真实用户崩溃/强杀后，私有目录可能留存含明文配置的解密暂存。`9b26035` 只修正门禁记账（拒绝前快照、只对新建目录记账、回执披露 `staleStagingFromKilledRestores`），未改产品行为；是否应在恢复/启动路径清扫未跟踪的解密暂存属崩溃恢复算法与隐私边界设计，交 Codex 主线程复核。Linux 语义复现确认：拒绝路径不产生新暂存、被杀恢复的遗留持续存在。

Second disclosed gap (rc.74 attribution): a hard-killed restore skips `TemporaryDirectory` cleanup and leaves plaintext decrypt staging `.webobs-decrypt-*` in the private account directory. `recover_interrupted()` removes only journal-recorded staging and no other product path sweeps the untracked decrypt directory, so a real crash can leave plaintext extracted configuration behind. `9b26035` fixes gate accounting only (pre-refusal snapshot, charge-new-only, receipt disclosure `staleStagingFromKilledRestores`); whether the product should clean untracked decrypt staging is crash-recovery/privacy design held for the Codex main thread.

第三个披露项（rc.75 归因）：软件解码 runner 在高负载安装流程中出现输入侧解码停滞——单次启动日志 6 次 `WebOBS async video backlog`（各丢弃 30 个未绘制帧、间隙 2.689–3.000 秒）与 1 次 async timestamp jump。`9c2b7af` 的一次有界重读只容忍"单个消费窗口恰好撞上瞬时停滞"的记账竞态，不证明持续媒体行为健康；标记计数仍经回执暴露，真实设备/相机与 OBS 性能验收保持开放（R7-001）。

Third disclosed gap (rc.75 attribution): input-side decode starvation on the software-decode runner during the heavy install flow (six async-backlog drops of 30 undrawn frames, gaps 2.689–3.000 s, plus one async timestamp jump per boot). The one bounded retry in `9c2b7af` tolerates only a consumer window racing a transient stall; it does not claim sustained media behavior is healthy. Marker counts stay visible in receipts, and real device/camera/OBS-parity qualification remains open (R7-001).

**第四披露项（rc.76）：Program 发布中继被杀后的前端访问违例崩溃。** run 44746006213 在 `program-publish-disconnect`：私有 MediaMTX 中继被终止、`publish-relay-exited` 正确上报后，OBS 前端宿主以 `0xC0000005`（访问违例）异常退出——`currentBootFailure=frontend-exited`、`serviceExits` frontend exitCode 3221226505、无 `Shutting down` 标记（非正常退出）、窗口句柄 `gone`、恢复尝试 0 次成功；断言「the product publish control could not resume Program publishing after the relay loss」记账于该崩溃。时间线：14:04:37 中继被杀后 fixture 源断连/重连，14:04:52.940 三路 async timestamp jump，14:04:56 门禁报告时前端已退出。宿主自计量（`a75d0cf` 加入的发布开关 UI 线程归因）：`publishStopWaitMs 5943`、`uiStallMaxMs 5752`、`relayStopMaxMs 5034`。rc.73–75 在同一代码路径同输入下均通过该阶段，属**间歇性竞态崩溃**；归因（中继被杀、media source 异步重连与发布 teardown 在宿主侧的竞态）属崩溃恢复算法与复杂诊断，**交 Codex 主线程排查**，本会话未做掩盖性测试修改、无法本机（Linux）复现。rc.77/rc.78（同 SHA 重跑）未到达该阶段（更早失败于 `native-program-take`），rc.79（同 SHA）首次干净通过该阶段（entry-ui 全绿、中继断连正常上报、前端未退出）——至今 1 次崩溃、4 次通过、2 次未到达，属间歇性；复现性仍**无结论**，任何回执通过都不能关闭本项。

**Fourth disclosed gap (rc.76): frontend access-violation crash after the Program publish relay is killed.** In run 44746006213's `program-publish-disconnect`, once the private MediaMTX relay was terminated and `publish-relay-exited` correctly reported, the OBS frontend host exited with `0xC0000005` (access violation) — `currentBootFailure=frontend-exited`, frontend exit code 3221226505, no `Shutting down` marker (abnormal exit), window handles `gone`, zero successful recovery attempts; the resume assertion was charged to that crash. Timeline: relay killed 14:04:37, fixture sources disconnect/reconnect, three async timestamp jumps at 14:04:52.940, frontend already exited by the 14:04:56 report. Host self-measurement (`a75d0cf` publish-control UI-thread attribution): `publishStopWaitMs 5943`, `uiStallMaxMs 5752`, `relayStopMaxMs 5034`. rc.73–75 passed the same path under the same inputs, so this is an **intermittent race crash**; attribution belongs to crash-recovery/complex diagnostics and is **handed to the Codex main thread** — no masking test change was made and it cannot be reproduced locally (Linux). rc.77/rc.78 (same SHA re-runs) never reached that phase (earlier `native-program-take` failures) and rc.79 (same SHA) cleanly passed it for the first time (entry-ui fully green, relay loss reported, frontend alive) — one crash, four passes and two non-reached observations so far, intermittent; reproducibility stays **inconclusive** and no passing receipt may close it.

**第五披露项（rc.77）：CUT TAKE 后墙格子一次约 0.5 s 的瞬态重绘。** run 44751520752 的 `program-after-take` 捕获中，main-preview 八个采样的第 0 个显示 `Wrong channel 1 in tile 0: 62,30,30`（变暗旧帧），其后 7 个采样通道正确且计数器持续推进（`temporalProgress=true`、`stalledPaths=[]`、publisher 全存活）——即 TAKE 提交并确认收敛后，真实用户仍可能看到墙格子首帧约半秒处于中途重绘态。归因与 rc.47/48/50 已记录的“捕获窗口起点与 Program 重绘竞态”同类：同阶段在 rc.73/74/76 全部通过，本次仅第 0 个采样命中，属间歇性观察。`9460829` 只做装置侧有界重捕获（同身份、整窗、每角色全过才算通过），不修改产品行为；该瞬态重绘本身未修复、不得写成已解决。

**Fifth disclosed gap (rc.77): one ~0.5 s transient repaint of a wall tile after the cut TAKE.** In run 44751520752's `program-after-take` capture, main-preview sample 0 showed `Wrong channel 1 in tile 0: 62,30,30` (a darkened stale frame) while samples 1-7 carried correct channels with continuously advancing counters (`temporalProgress=true`, `stalledPaths=[]`, all publishers alive) — a real user can still see one wall tile mid-repaint for roughly half a second after the TAKE is committed and settled. The attribution matches the documented mid-swap capture-start race (rc.47/48/50): the same phase passed in rc.73/74/76 and only sample 0 hit this time, so it is an intermittent observation. `9460829` adds only a bounded device-side settled re-capture (same identity, whole window, every role must pass); the product behavior is unchanged and this repaint itself is not fixed — do not mark it resolved.

**第六披露项（rc.78）：cut TAKE 后产品侧预览整窗重绘停滞（真实用户可见）。** run 44795726091 的 `program-after-take`：main-preview 八个采样通道与布局全部正确，但时间码计数器完全冻结（全 `[31,31,38,38,38]`、`distinctClientCount=1`、`distinctTileCounts=[1,1,1,1,1]`、`temporalProgress=false`），SerialWatch 观测窗 26.03 s；同一窗口宿主渲染计数 9923→10702（~30 fps）、六个输入 serial 全部 advance、五个 fixture publisher 全存活、无停滞路径、feed 解码探测每路 32-38 个不同帧——帧已到达源、宿主在渲染、合成 feed 内容在变化，唯独已绑定格子在捕获窗口里不重绘。开启宿主渲染探针复测仍部分冻结（tiles 0,2,3 stale、1,4 更新，`renderFramesPerSecond 30.4`），排除整体捕获失效与 fixture 故障两类解释。这是真实用户可见的预览重绘停滞；与 rc.76 前端 AV 崩溃同属 cut TAKE retirement/rebind 宿主竞态的疑似根因族（rc.77 该阶段瞬态失败、rc.78 持久失败、rc.76 同族代码曾通过）。属复杂诊断/崩溃恢复面，**交 Codex 主线程**；本会话未改代码、无法本机（Linux）复现；门禁按设计如实失败（瞬态重试形态未匹配、未触发）。rc.79（同 SHA 重跑）该阶段未复现（entry-ui 首次全绿），持续性**无结论**——该阶段历史为 rc.73/74/76/79 通过、rc.77 瞬态失败、rc.78 持久失败；任何通过都不关闭本项。

**Sixth disclosed gap (rc.78): product-side full-window preview repaint stall after the cut TAKE (user-visible).** In run 44795726091's `program-after-take`, main-preview showed correct channels and layout in all eight samples but the timecode counters were completely frozen (all `[31,31,38,38,38]`, `distinctClientCount=1`, `distinctTileCounts=[1,1,1,1,1]`, `temporalProgress=false`) over a 26.03 s SerialWatch window, while inside the same window the host render counter advanced 9923→10702 (~30 fps), all six input serials advanced, all five fixture publishers were alive with no stalled paths, and the feed decode probe found 32-38 distinct frames per path — frames reached the sources, the host was rendering, and the synthetic feed content was changing, yet the bound tiles did not repaint in the captured window. Re-capturing with the host render probe open stayed partially frozen (tiles 0,2,3 stale, 1,4 updating, `renderFramesPerSecond 30.4`), ruling out both whole-capture staleness and fixture faults. This is a user-visible preview repaint stall; it belongs to the same suspected root-cause family as the rc.76 frontend access-violation crash (cut-TAKE retirement/rebind host race: rc.77 transient failure and rc.78 persistent failure at the same phase, rc.76 passed on the same-family code). Complex diagnostics/crash-recovery territory, **handed to the Codex main thread**; no code change was made and it cannot be reproduced locally (Linux); the gate failed by design (the transient retry form did not match and did not fire). rc.79 (same SHA re-run) did not reproduce the stall (entry-ui green for the first time), so persistence is **inconclusive** — the phase history is rc.73/74/76/79 pass, rc.77 transient failure, rc.78 persistent failure; no passing receipt may close it.

## 本机回归证据 / local regression evidence（2026-11-21，`.worktrees/v51-legacy` @ `54df2e3`）

- @`54df2e3` 备份修复复验：Linux 确定性复现 run 44800953316 的失败序列（成对档案→两次守护哨兵硬杀→`recover_interrupted` 收敛两次→retry 全量恢复→成对拒绝→legacy config-only 恢复），修复前 legacy 恢复 exit=1 `backup file integrity verification failed`（自指清单条目 size 306 对实际 425），修复后 exit=0、config 标记恢复为 backup、native 保持 kept-native、无 journal 残留；`tests/test_encrypted_backup.py` 14 项 OK（新增恢复后再打备份往返、历史自指清单验收两项）；`native-host/tests/test_complete_supervisor.py`/`test_native_updater.py` 脚本 PASS；`test_build_contract.py` 仍 63 项 62 通过（唯一错误为未初始化 obs 子模块）。修复未触碰硬终止明文暂存披露项（第二披露项保持开放）。@`9460829` 复验：`test_build_contract.py` 63 项中 62 通过（新增中途交换重捕获契约；唯一错误仍为未初始化 obs 子模块）；`test_pixels.py` 31 通过 2 跳过；`py_compile product_windows.py` OK；`git diff --check` OK；谓词 Linux 语义复现——rc.77 形态（仅第 0 采样失败、8 采样齐备、进度已证实、Program 阶段）被容忍，冻结多采样、无进度、后段采样失败、非 Program 阶段、预算耗尽与短窗口一律拒绝。捕获调用抽为 `run_capture` 由主循环与重试共用（契约钉死两处调用与顺序：fixture 修复优先、重捕获先于 probe 窗口）。此前 @`9c2b7af` 各项证据保留如下。
- `native-host/tests/test_build_contract.py`：加入第二次启动、拒绝记账与视频窗口重试三个静态契约（并把关键帧窗口既有契约改钉共享 `decodable_window` 谓词）后 62 项中 61 通过，唯一错误为本 worktree 未初始化 `obs/obs-studio` 子模块（缺 CMakePresets.json），与前轮记录一致。
- 第二次启动竞态的 Linux 语义复现（2026-11-20）：旧谓词第一 tick 即接受遗留 bootId；修复谓词拒绝 `status-from-previous-boot`，直到本次启动发布新 bootId 且 journal 已收敛才接受——与第三次启动既有守卫同形。
- 拒绝暂存记账的 Linux 语义复现（2026-11-20，真实 `backup/encrypted_backup.py` + libsodium）：守护哨兵后硬终止的恢复遗留 `.webobs-decrypt-*` 与 journal/暂存；随后对成对档案的 config-only 调用抛 `BackupError` 拒绝且未新建任何暂存（其自身 TemporaryDirectory 正常清理），journal 与已记录暂存被该调用的先行 `recover_interrupted()` 收敛，旧断言恰好在这一点把被杀恢复的遗留记到拒绝头上；修复谓词（快照差集）在有遗留时通过。
- 视频窗口重试的 Linux 语义复现（2026-11-20）：用 run 44735378274 实际观测值构造窗口（stalled 26 帧/0.833 s 拒绝，healthy 83 帧/2.733 s 接受）——stalled→重试→healthy 被接受、连续两次 stalled 被拒绝、首轮 healthy 不重试。Windows 解码停滞本身无法本机复现，属披露项。
- `tests/test_encrypted_backup.py` 12 项 OK（unittest 复跑）；`native-host/tests/test_pixels.py` 31 通过 2 跳过（改动后复跑，真实 FFmpeg 音调短段回归在列）；`py_compile` 改动文件 OK；`git diff --check` OK。
- `native-host/tests/test_product_lan.py` 24 OK；`native-host/tests/test_complete_supervisor.py` PASS；`native-host/tests/test_native_updater.py` PASS；`tests/test_camera_registry.py` 58 OK。
- Linux 语义回归与合同判定不覆盖真实 Windows/相机/目标机验收；R7-001 保持开放。

## 交 Codex 主线程的动作清单 / checklist for the Codex main thread

1. 读 run 44718717601 门禁 JSON：`result=review-install-evidence`（exit 0）时按上表核对回执；`inspect-first-failure` 时先读 `failureReceipts`/`uiAttribution` 再决定返工或重派。
2. 复核六层 diff 与换基顺序；合并保留双语标题/正文，显式覆盖 GitHub 英文默认合并信息。
3. #69 超集冲突由主线程处理；#73 最后填回执。
4. 集成后按第 4 节派发 120 分钟冻结候选；候选字节用 `publish_candidate.py --verify-only` 校验后再走授权发布流程。
5. 崩溃窗口（上节）需要产品侧结论：prepared 成对回滚或 journal 先行 fsync 的顺序调整，属迁移/恢复算法，归主线程。
6. 硬终止后未跟踪的明文解密暂存 `.webobs-decrypt-*` 是否纳入恢复/启动路径清扫，属崩溃恢复与私有数据边界设计（见披露节与 `9b26035` 门禁记账），归主线程；本轮门禁只披露、不代为修改产品行为。
7. rc.76 前端访问违例崩溃（第四披露项）需主线程排查：私有 MediaMTX 中继被杀后，media source 异步重连与发布 teardown 在 OBS 宿主侧的竞态疑似导致 `0xC0000005`；证据见 run 44746006213 回执（`publishStopWaitMs 5943`、`uiStallMaxMs 5752`、`relayStopMaxMs 5034`、无 `Shutting down`）。属真实崩溃恢复算法与复杂诊断，本会话未改代码、无本机复现；rc.77/rc.78（同 SHA）未到达该阶段、rc.79（run 44800953316，同 SHA）首次干净通过该阶段——至今仅 rc.76 一次崩溃，确定性仍无结论，按后续轮次继续判定后再决定宿主侧修复方向。
8. rc.78 整窗预览重绘停滞（第六披露项）需主线程做宿主侧诊断：run 44795726091 的 `program-after-take` 八采样计数器完全冻结（`distinctClientCount=1`、`temporalProgress=false`），而宿主渲染计数 ~30 fps 前进、六输入 serial 全 advance、feed 探测每路 32-38 个不同帧、publisher 全存活，开宿主渲染探针复测仍 tiles 0,2,3 stale——疑似与第四披露项同族的 cut TAKE retirement/rebind 宿主竞态。连续两轮失败于该阶段（rc.77 瞬态、rc.78 持久）；rc.79（run 44800953316，同 SHA）未复现（entry-ui 首次全绿），持续性无结论，修复方向待后续命中再定。属复杂诊断面，本会话未改代码、无法本机（Linux）复现；`9460829` 的瞬态重试形态正确地未触发，不构成掩盖。
9. `54df2e3` 是本段栈内唯一产品代码改动，主线程重点复核：`restore()` 落进配置根的 `backup-manifest.json` 曾被下一次 `create()` 当用户文件打包（自指条目记录陈旧大小后被自身覆盖），恢复后再打的备份永久不可恢复；修复为 `stage_tree` 排除根级清单 + `verify_tree` 跳过历史自指条目（已污染档案恢复可用）。Linux 确定性复现与回归见第 6 节；真实 Windows 安装态生效由 rc.80（run 44814303103）验证。硬终止后明文 `.webobs-decrypt-*` 清扫（第二披露项）与本修复正交，仍归主线程。
