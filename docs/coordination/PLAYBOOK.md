# 多 Agent 协作约定 / Multi-agent playbook

适用项目：Web Camera Monitor Wall / `monitor_wall_czl`。Codex 订阅、Codex API、DSH 和人工开发者使用同一套文件；模型名称不充当负责人身份，每个客户端/会话使用唯一 Agent ID。

## 从哪里接手

1. 阅读根目录 [AGENTS.md](../../AGENTS.md)，执行 `git status --short --branch`，确认当前分支、实际源码和已有未提交修改。
2. 阅读 [STATUS.md](STATUS.md)、[HANDOFF.md](HANDOFF.md)、[TASKS.md](TASKS.md) 与相关任务的证据。
3. 查看 [DECISIONS.md](DECISIONS.md) 中的当前产品范围，按 [ROADMAP.md](ROADMAP.md) 和原任务书理解验收门槛。
4. 用下面的命令认领任务，确认成功后再修改。分支/工作目录不同也不能把同一个 Agent ID 当作自己。

## 唯一事实源与同步

- [state.json](state.json) 是当前任务、负责人、下一步、阻塞和新增开发日志的唯一数据源。`STATUS/ROADMAP/TASKS/DEVLOG/HANDOFF.md` 均由脚本生成，不能分别手改。
- 既有[完整任务书](../windows-webobs-wall-release-plan-2026-11-11.md)、[功能矩阵](../windows-native-feature-parity.md)、[历史执行日志](../windows-obs-parity-execution.md)保留原有职责。新任务关闭或能力状态变化时，在相应原始文档补充证据，再把位置记录到账本。
- 同一结论不在多处手抄。当前状态看本目录生成页；产品历史看原日志；约束优先级为用户最新明确决定、AGENTS.md、带证据的新记录、历史材料。
- 脚本在同一 checkout 内加锁，原子保存 JSON，并从同一快照重建五个页面。异常中断后运行 `render` 修复页面，`check` 检查有无不同步。
- 这不是后台监视器，也不会自动理解聊天、代码 diff 或 CI 结果。**Agent 必须在认领、实质进展、测试结果、阻塞、退出/交接时主动更新。** 长任务每完成一小项留下检查点，避免只在最后一次汇总。
- 同一台机器、同一 checkout 中，保存后其他客户端即可读取；浏览器中的旧上下文仍需重新读取文件。不同电脑或不同 clone 需要正常 Git 同步，不能把本机文件锁当成分布式锁。

## 常用命令

从仓库根目录执行；Windows 可将 `python3` 换为 `python`。脚本只依赖 Python 3.10+ 标准库。

```bash
python3 scripts/agent-sync.py status
python3 scripts/agent-sync.py claim R0-002 --agent dsh-session-example --note '核对当前功能矩阵与最新执行记录'
python3 scripts/agent-sync.py update R0-002 --agent dsh-session-example --note '已核对 AUTH/RBAC，尚未完成其余项目' --next '继续核对 Studio 与声音入口' --evidence '相关文档/测试命令和实际结果'
python3 scripts/agent-sync.py update R0-002 --agent dsh-session-example --status blocked --blocker '具体缺少的环境/输入/外部状态' --next '恢复所需条件及可独立推进的事项' --note '记录已尝试的方法和实际结果'
```

结束任务时必须提供本轮证据；只有自己认领的任务才能标为完成。证据写命令、环境、结果、源码/构建身份、限制以及可定位的脱敏文档位置；不能把旧通过记录当作本轮重跑。

```bash
python3 scripts/agent-sync.py update R0-002 --agent dsh-session-example --status done --note '矩阵各项已对照实际入口，未知项继续开放' --next '交给后续任务处理尚未迁移的功能' --evidence '本轮实际检查命令/结果及文档位置'
python3 scripts/agent-sync.py check
git diff --check
```

暂停自己的进行中任务供他人接手：

```bash
python3 scripts/agent-sync.py release R0-002 --agent dsh-session-example --note '交接：已完成哪些行、未提交文件、验证结果、待做内容'
```

`blocked` 任务保留负责人和阻塞原因。条件恢复后原负责人先 `update --status planned --note '条件如何恢复/交接给谁'`，再由接手者认领。长期无更新不自动强占；先联系负责人或由用户/协调者确认交接。暂停平台不能靠命令自行解锁。

新增任务必须写修改范围、依赖、验收和下一步；任务登记不扩大发布授权：

```bash
python3 scripts/agent-sync.py add R2-005 --agent coordinator-example --title '经确认的新任务' --milestone R2 --scope native-host/src/specific-file.cpp --acceptance '可复核的完成条件' --depends-on R2-001 --next '第一个具体步骤' --note '决定来源及拆分理由'
```

## 多人修改与工作树

- 同一任务只能有一个负责人；有重叠 `scope` 的进行中任务拒绝同时认领。`scope` 是协作约束，不是操作系统权限隔离，Agent 仍须自觉遵守。
- 多个任务需要改同一模块时，先细分任务/范围，或由一个集成负责人串行合入；不要为了绕过检查把范围写小。
- 共用工作目录禁止替他人 `reset/clean/stash`、切换分支或丢弃未提交修改。需要分支隔离时使用独立 worktree，保留原工作目录。
- 使用独立 worktree 时指定**一个**集成 checkout 为共享账本写入口：`python3 scripts/agent-sync.py --root '<集成 checkout>' ...`；代码测试记录仍说明实际工作树/源码身份。脚本默认基于自身所在 checkout，不能想当然地跨 worktree 同步。
- 新里程碑、任务范围调整、用户决定变化由协调者审查 `state.json` 后合并，保留已有事件，递增快照/日志编号，再 `render` 和 `check`。不同 clone 发生 JSON 冲突时保留两侧任务和事件，统一编号；不能简单选 ours/theirs 丢弃一侧日志。
- 日常提交/PR 面向 `dev`，提交和 PR 信息中英双语；main/Tag/公开发布沿用既有规则。本次协作设置不自动提交、推送、构建候选或发布。
- 不同 Unix 用户共用 checkout 时，还需要该项目已有访问权限及目录默认 ACL。同步脚本原子替换已存在文件时保留其访问模式，避免临时文件的 `0600` 掩掉协作 ACL；首次生成的新文件仍默认私有，需显式共享。此机制不自行授予访问权限，也不把文件改成对所有用户可写。

## 完成、验证与交接标准

- `planned` 待开始；`in_progress` 有明确负责人；`blocked` 必须有具体阻塞；`done` 依赖关闭且有本轮证据；`on_hold` 是用户暂停范围。
- 完成表示本任务验收条件满足。源码接线、Linux fixture、Windows 合成媒体、真实 NSIS、目标机/真实相机和发布资格分别记录。
- 交接记录至少说明：任务 ID、分支/源码身份、改动文件与接口、已完成/待做、命令与通过/失败/跳过、证据位置、阻塞、下一条可执行步骤。写入任务 `--note/--next/--evidence` 后会同步到日志和交接页。
- 不把密码、Token、真实摄像机地址、录像、完整私密日志和签名密钥写到账本/Git。证据只登记脱敏摘要，原始资料保存在仓库外。
- 管理员操作仍受用户任务范围和临时租期约束：先 `sudo -n true`，可用时只用 `sudo -n`；不得自行 grant/续期/创建永久免密规则，不索要密码。

## English quick contract

Read AGENTS, the status/task/handoff views and current decisions first. Claim a uniquely identified task before editing; respect declared file ownership and preserve others' work. Update the canonical JSON through the script at checkpoints, tests, blockers and handoffs. Generated views are not independent editable records. Local locking coordinates one checkout, not distributed clones; use one integration ledger and normal reviewed Git synchronization. Completion needs current evidence and satisfied dependencies. Existing publication, privacy and platform limits remain authoritative.
