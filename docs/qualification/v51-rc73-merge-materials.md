# v5.1 rc.73 合并材料 / v5.1 rc.73 merge materials

> 会话 Agent ID：`qwen38-next-v51-20261120-02` · 任务 V51-008 · 状态：待回执齐全后交 Codex 主线程审阅，本会话不自行合并或发布。
> Session Agent ID `qwen38-next-v51-20261120-02`, task V51-008. Status: hand to the Codex main thread for PR integration once receipts are complete; this session does not merge or publish.

## 被测候选 / candidate under test

- 版本 version: `5.1.0-rc.73` → `5.1.0-rc.74` → `5.1.0-rc.75`（同一栈顶分支 `codex/v51-r4-legacy-import`，PR #76）
- rc.73 源码 SHA `28c338840d5e5687ef4231885a70c3386f2cfdc8`，run [44718717601](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44718717601)（inputs `product_mode=true complete=true soak_minutes=0`）：**completed=failure**。Program 增益首次通过（controlRatios 440=1.004/880=0.998；880 降增益 585.9/3068.2≈0.191；逐段 peakHz 全部标称）；首个真实失败点为 `backup_restore_windows.py:319`「the installed entry left the native-swap journal behind」——归因为装置侧竞态（第一次启动遗留的 native-status.json 带 phase=running+旧 bootId，被 100ms 首个 tick 接受），产品收敛代码覆盖被杀窗口，非产品缺陷。test-only 修复见下。
- rc.74 源码 SHA `0bd1a2943dd2234e35194819aa80eadaa7ee7f0f`（含修复提交 `0bd1a29`），run [44728029615](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44728029615)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44728029615 --sha 0bd1a2943dd2234e35194819aa80eadaa7ee7f0f --version 5.1.0-rc.74`：**completed=failure**，Program 增益再次通过（controlRatios 440=0.976/880=0.938；880 降增益 611.8/3057.8≈0.200）；第二次安装态启动竞态修复生效，门禁推进到 `backup_restore_windows.py:390`「the refused paired restore leaked staging directories」（回执 phase 字段停留在 `interrupted-restore-pair-recovery` 仅为 checkpoint 滞后，traceback 行号才是首个失败点）。归因为装置记账缺陷：成对档案拒绝在自己的 `.webobs-decrypt-` TemporaryDirectory 内抛 `BackupError`，不可能新建暂存；失败实际记的是早前两次被 `TerminateProcess` 硬终止的恢复遗留的明文解密暂存（硬终止跳过上下文管理器清理，`recover_interrupted()` 只删除 journal 记录的暂存）。test-only 修复 `9b26035`（拒绝前快照暂存名单、只对拒绝新建目录记账、回执披露遗留项）。
- rc.75 源码 SHA `9b260351368770eec6e81458c9c50f1886e47d71`（含 `9b26035`），run [44735378274](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44735378274)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44735378274 --sha 9b260351368770eec6e81458c9c50f1886e47d71 --version 5.1.0-rc.75`
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
| #76 | codex/v51-r4-legacy-import | `9b26035`（原 `28c3388`→`0bd1a29`） | codex/v51-r3-005-devices | 7 |

换基合并顺序 / retarget order（每步合并后把下一层 base 改为 `dev`，核对换基后 diff 只含该层自身改动）：

1. #67 → dev（Program 输出/UIA 归因/夹具登记等，最大层）。
2. #70 → dev（成对备份交换与中断收敛 + updater 有界错误码）。
3. #71 → dev（LAN/Web 入口与安装态门禁）。
4. #74 → dev（两小时长稳门禁，本轮 soak_minutes=0 不启用）。
5. #75 → dev（设备操作安装态门禁）。
6. #76 → dev（旧数据导入安装态门禁，含 rc.72–rc.75 四个 test-only 修复 `a27a766`、`28c3388`、`0bd1a29`、`9b26035`；`0bd1a29`/`9b26035` 属 V51-007 的门禁文件，知会仍待协调人转达——agent-sync log 对 V51-007 被拒，内容见 revision 289）。

并行注意 / parallel notes：
- #69（发布链）base dev：合入 #67 后 rebase，`publish_candidate.py` 为 add/add，保留 #69 的超集实现并复跑发布链测试（V51-005）；发布链只验证到待发布状态，不自动发布。
- #73（发布说明）base dev、当前 UNSTABLE：在候选回执齐后按 V51-012 填实际摘要，最后合入。
- 冻结候选（soak_minutes=120）在全部六层并入 dev 后从 dev 派发，按 runbook 第 4 节设置候选 `update_feed`。

## 本轮已提交的验收回执 / receipts required this round

安装态门禁要求同一 run 内 `native-product-integration-receipts-5.1.0-rc.73` 含以下全部 `passed=true` 且绑定源码 SHA/版本（`upgraded-ui` 用同源 `5.1.0-rc.74` 夹具版本）：

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

## 必须保留的已知缺口声明 / disclosed known gap（不得因本轮通过而关闭）

rc.72（run 44711476489）暴露的窗口：`backup/encrypted_backup.py` 中 `os.replace(activated, config_root)` 返回与记录 `nativeRollback` 的 journal `fsync` 落盘之间的微秒级崩溃窗口会真正丢失原生半区引用。`28c3388` 只是把测试哨兵挪到 journal 写入之后（test-only），产品恢复算法本身未改。**rc.73 该阶段通过不能证明该间隙安全**；该边界属产品恢复算法，已交 Codex 主线程复核（见 HANDOFF 2026-11-20 交接段与 DEVLOG `3a99fa4`）。合并材料不将其列为已解决。

The rc.72 finding stands: a crash between `os.replace` returning and the journal `fsync` that records `nativeRollback` can genuinely drop the native-half reference. `28c3388` moves only the test sentinel after the journal write; the product recovery algorithm is unchanged. A passing rc.73 gate does **not** prove the window safe — it stays open for Codex main-thread review.

第二个必须保留的披露项（rc.74 归因）：被硬终止（`TerminateProcess`/SIGKILL）的恢复进程会跳过 `TemporaryDirectory` 清理，把明文解密暂存 `.webobs-decrypt-*` 留在账户私有目录里；`recover_interrupted()` 只删除 journal 记录的暂存，从不清扫这个未记录目录，产品代码也没有任何其他路径会移除它。也就是说真实用户崩溃/强杀后，私有目录可能留存含明文配置的解密暂存。`9b26035` 只修正门禁记账（拒绝前快照、只对新建目录记账、回执披露 `staleStagingFromKilledRestores`），未改产品行为；是否应在恢复/启动路径清扫未跟踪的解密暂存属崩溃恢复算法与隐私边界设计，交 Codex 主线程复核。Linux 语义复现确认：拒绝路径不产生新暂存、被杀恢复的遗留持续存在。

Second disclosed gap (rc.74 attribution): a hard-killed restore skips `TemporaryDirectory` cleanup and leaves plaintext decrypt staging `.webobs-decrypt-*` in the private account directory. `recover_interrupted()` removes only journal-recorded staging and no other product path sweeps the untracked decrypt directory, so a real crash can leave plaintext extracted configuration behind. `9b26035` fixes gate accounting only (pre-refusal snapshot, charge-new-only, receipt disclosure `staleStagingFromKilledRestores`); whether the product should clean untracked decrypt staging is crash-recovery/privacy design held for the Codex main thread.

## 本机回归证据 / local regression evidence（2026-11-20，`.worktrees/v51-legacy` @ `9b26035`）

- `native-host/tests/test_build_contract.py`：加入第二次启动与拒绝记账两个静态契约后 61 项中 60 通过，唯一错误为本 worktree 未初始化 `obs/obs-studio` 子模块（缺 CMakePresets.json），与前轮记录一致。
- 第二次启动竞态的 Linux 语义复现（2026-11-20）：旧谓词第一 tick 即接受遗留 bootId；修复谓词拒绝 `status-from-previous-boot`，直到本次启动发布新 bootId 且 journal 已收敛才接受——与第三次启动既有守卫同形。
- 拒绝暂存记账的 Linux 语义复现（2026-11-20，真实 `backup/encrypted_backup.py` + libsodium）：守护哨兵后硬终止的恢复遗留 `.webobs-decrypt-*` 与 journal/暂存；随后对成对档案的 config-only 调用抛 `BackupError` 拒绝且未新建任何暂存（其自身 TemporaryDirectory 正常清理），journal 与已记录暂存被该调用的先行 `recover_interrupted()` 收敛，旧断言恰好在这一点把被杀恢复的遗留记到拒绝头上；修复谓词（快照差集）在有遗留时通过。
- `tests/test_encrypted_backup.py` 12 项 OK（unittest 复跑）；`py_compile` 两个改动文件 OK；`git diff --check` OK。
- `native-host/tests/test_pixels.py`：31 通过 2 跳过（真实 FFmpeg 音调短段回归在列）。
- `native-host/tests/test_product_lan.py` 24 OK；`native-host/tests/test_complete_supervisor.py` PASS；`native-host/tests/test_native_updater.py` PASS；`tests/test_camera_registry.py` 58 OK。
- Linux 语义回归与合同判定不覆盖真实 Windows/相机/目标机验收；R7-001 保持开放。

## 交 Codex 主线程的动作清单 / checklist for the Codex main thread

1. 读 run 44718717601 门禁 JSON：`result=review-install-evidence`（exit 0）时按上表核对回执；`inspect-first-failure` 时先读 `failureReceipts`/`uiAttribution` 再决定返工或重派。
2. 复核六层 diff 与换基顺序；合并保留双语标题/正文，显式覆盖 GitHub 英文默认合并信息。
3. #69 超集冲突由主线程处理；#73 最后填回执。
4. 集成后按第 4 节派发 120 分钟冻结候选；候选字节用 `publish_candidate.py --verify-only` 校验后再走授权发布流程。
5. 崩溃窗口（上节）需要产品侧结论：prepared 成对回滚或 journal 先行 fsync 的顺序调整，属迁移/恢复算法，归主线程。
6. 硬终止后未跟踪的明文解密暂存 `.webobs-decrypt-*` 是否纳入恢复/启动路径清扫，属崩溃恢复与私有数据边界设计（见披露节与 `9b26035` 门禁记账），归主线程；本轮门禁只披露、不代为修改产品行为。
