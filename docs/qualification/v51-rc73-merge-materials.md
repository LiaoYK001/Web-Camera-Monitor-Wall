# v5.1 rc.73 合并材料 / v5.1 rc.73 merge materials

> 会话 Agent ID：`qwen38-next-v51-20261120-02` · 任务 V51-008 · 状态：待回执齐全后交 Codex 主线程审阅，本会话不自行合并或发布。
> Session Agent ID `qwen38-next-v51-20261120-02`, task V51-008. Status: hand to the Codex main thread for PR integration once receipts are complete; this session does not merge or publish.

## 被测候选 / candidate under test

- 版本 version: `5.1.0-rc.73` → `5.1.0-rc.74`（同一栈顶分支 `codex/v51-r4-legacy-import`，PR #76）
- rc.73 源码 SHA `28c338840d5e5687ef4231885a70c3386f2cfdc8`，run [44718717601](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44718717601)（inputs `product_mode=true complete=true soak_minutes=0`）：**completed=failure**。Program 增益首次通过（controlRatios 440=1.004/880=0.998；880 降增益 585.9/3068.2≈0.191；逐段 peakHz 全部标称）；首个真实失败点为 `backup_restore_windows.py:319`「the installed entry left the native-swap journal behind」——归因为装置侧竞态（第一次启动遗留的 native-status.json 带 phase=running+旧 bootId，被 100ms 首个 tick 接受），产品收敛代码覆盖被杀窗口，非产品缺陷。test-only 修复见下。
- rc.74 源码 SHA `0bd1a2943dd2234e35194819aa80eadaa7ee7f0f`（含修复提交 `0bd1a29`），run [44728029615](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44728029615)，输入同 rc.73。门禁 gate: `python3 scripts/v51-ci-gate.py 44728029615 --sha 0bd1a2943dd2234e35194819aa80eadaa7ee7f0f --version 5.1.0-rc.74`
- 派发前核对 `gh run list --limit 8` 无更新 run，未重复派发。No duplicate dispatch.

## PR 堆叠与换基顺序 / PR stack and retarget order

实际关系以最新 `baseRefName`/`headRefOid` 核对（2026-11-20 快照，六层全部 CLEAN、检查全绿，`windows-desktop-candidate` 在 PR 检查中有意 skipping，真实 Windows 证据来自上面的 run）：

| PR | 分支 head | HEAD | base | 层级提交数 |
| --- | --- | --- | --- | --- |
| #67 | codex/v51-r3-output | `9ed32ae` | dev | 63 |
| #70 | codex/v51-r4-backup-consistency | `d5b0727` | codex/v51-r3-output | 5 |
| #71 | codex/v51-r3-004-lan | `6a7042a` | codex/v51-r4-backup-consistency | 12 |
| #74 | codex/v51-r5-soak | `f6cf429` | codex/v51-r3-004-lan | 4 |
| #75 | codex/v51-r3-005-devices | `f60aab8` | codex/v51-r5-soak | 1 |
| #76 | codex/v51-r4-legacy-import | `0bd1a29`（原 `28c3388`） | codex/v51-r3-005-devices | 6 |

换基合并顺序 / retarget order（每步合并后把下一层 base 改为 `dev`，核对换基后 diff 只含该层自身改动）：

1. #67 → dev（Program 输出/UIA 归因/夹具登记等，最大层）。
2. #70 → dev（成对备份交换与中断收敛 + updater 有界错误码）。
3. #71 → dev（LAN/Web 入口与安装态门禁）。
4. #74 → dev（两小时长稳门禁，本轮 soak_minutes=0 不启用）。
5. #75 → dev（设备操作安装态门禁）。
6. #76 → dev（旧数据导入安装态门禁，含 rc.72–rc.74 三个 test-only 修复 `a27a766`、`28c3388`、`0bd1a29`；`0bd1a29` 属 V51-007 的门禁文件，知会仍待协调人转达——agent-sync log 对 V51-007 被拒，内容见 revision 289）。

并行注意 / parallel notes：
- #69（发布链）base dev：合入 #67 后 rebase，`publish_candidate.py` 为 add/add，保留 #69 的超集实现并复跑发布链测试（V51-005）；发布链只验证到待发布状态，不自动发布。
- #73（发布说明）base dev、当前 UNSTABLE：在候选回执齐后按 V51-012 填实际摘要，最后合入。
- 冻结候选（soak_minutes=120）在全部六层并入 dev 后从 dev 派发，按 runbook 第 4 节设置候选 `update_feed`。

## 本轮已提交的验收回执 / receipts required this round

安装态门禁要求同一 run 内 `native-product-integration-receipts-5.1.0-rc.73` 含以下全部 `passed=true` 且绑定源码 SHA/版本（`upgraded-ui` 用同源 `5.1.0-rc.74` 夹具版本）：

| 回执 receipt（rc.73 首轮结果 → rc.74 复验） | 含义 | rc.73 状态 | rc.74 状态 |
| --- | --- | --- | --- |
| entry-ui | 便携门禁（Program 输出全路径，含增益/偏移/断开） | passed=true | 待填 pending |
| restore | 备份恢复契约 | passed=true | 待填 pending |
| installed-ui | 安装态门禁（普通启动入口） | passed=true | 待填 pending |
| nsis | NSIS 安装/重装/成对恢复 | passed=false（restore-pair 竞态，装置侧已修） | 待填 pending |
| restore-pair | 中断成对交换经真实已安装入口收敛 | 未产出（NSIS 门禁失败，后续步骤未跑） | 待填 pending |
| legacy-import | 包内旧数据导入（账户权限、保留链接、失效旧会话） | 未产出 | 待填 pending |
| lan | LAN 入口（记录 lanHttpsQualified / remoteDeviceQualified / 降级原因） | 未产出 | 待填 pending |
| updater | 更新器契约 | 未产出 | 待填 pending |
| upgraded-ui | 覆盖升级同源夹具（rc.73 轮为 rc.74 版本） | 未产出 | 待填 pending |
| size-split | 同源码组件体积报告 | passed=true | 待填 pending |

另需 `webobs-wall-complete-candidate-<version>` 安装包工件（rc.73 未产出）。rc.73 的 `native-product-nsis.json` 显示 `freshInstalledEntryQualified=true`、footprint/快捷方式检查全部通过，仅成对恢复第二次启动被装置竞态阻断。

## 必须保留的已知缺口声明 / disclosed known gap（不得因本轮通过而关闭）

rc.72（run 44711476489）暴露的窗口：`backup/encrypted_backup.py` 中 `os.replace(activated, config_root)` 返回与记录 `nativeRollback` 的 journal `fsync` 落盘之间的微秒级崩溃窗口会真正丢失原生半区引用。`28c3388` 只是把测试哨兵挪到 journal 写入之后（test-only），产品恢复算法本身未改。**rc.73 该阶段通过不能证明该间隙安全**；该边界属产品恢复算法，已交 Codex 主线程复核（见 HANDOFF 2026-11-20 交接段与 DEVLOG `3a99fa4`）。合并材料不将其列为已解决。

The rc.72 finding stands: a crash between `os.replace` returning and the journal `fsync` that records `nativeRollback` can genuinely drop the native-half reference. `28c3388` moves only the test sentinel after the journal write; the product recovery algorithm is unchanged. A passing rc.73 gate does **not** prove the window safe — it stays open for Codex main-thread review.

## 本机回归证据 / local regression evidence（2026-11-20，`.worktrees/v51-legacy` @ `28c3388`）

- `native-host/tests/test_build_contract.py`：加入第二次启动静态契约后 60 项中 59 通过，唯一错误为本 worktree 未初始化 `obs/obs-studio` 子模块（缺 CMakePresets.json），与前轮记录一致。
- 第二次启动竞态的 Linux 语义复现（2026-11-20）：旧谓词第一 tick 即接受遗留 bootId；修复谓词拒绝 `status-from-previous-boot`，直到本次启动发布新 bootId 且 journal 已收敛才接受——与第三次启动既有守卫同形。
- `native-host/tests/test_pixels.py`：31 通过 2 跳过（真实 FFmpeg 音调短段回归在列）。
- `native-host/tests/test_product_lan.py` 24 OK；`native-host/tests/test_complete_supervisor.py` PASS；`native-host/tests/test_native_updater.py` PASS；`tests/test_camera_registry.py` 58 OK。
- `native-host/tests/test_encrypted_backup.py` 以 unittest 复跑通过；`py_compile` 四个门禁文件 OK；`git diff --check` OK。
- Linux 语义回归与合同判定不覆盖真实 Windows/相机/目标机验收；R7-001 保持开放。

## 交 Codex 主线程的动作清单 / checklist for the Codex main thread

1. 读 run 44718717601 门禁 JSON：`result=review-install-evidence`（exit 0）时按上表核对回执；`inspect-first-failure` 时先读 `failureReceipts`/`uiAttribution` 再决定返工或重派。
2. 复核六层 diff 与换基顺序；合并保留双语标题/正文，显式覆盖 GitHub 英文默认合并信息。
3. #69 超集冲突由主线程处理；#73 最后填回执。
4. 集成后按第 4 节派发 120 分钟冻结候选；候选字节用 `publish_candidate.py --verify-only` 校验后再走授权发布流程。
5. 崩溃窗口（上节）需要产品侧结论：prepared 成对回滚或 journal 先行 fsync 的顺序调整，属迁移/恢复算法，归主线程。
