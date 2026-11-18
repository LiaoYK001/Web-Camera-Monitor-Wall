# v5.0 成品开发：当前交接手册

> **已被2026-11-17的[v5.1最新交接手册](V51-NEXT-AGENT-HANDOFF-2026-11-17.md)替代。** 后续正式目标为v5.1，实际代码在`.worktrees/v51`、PR65；不要按本页旧PR58/R1负责人快照接手。

核对时间：2026-11-16 20:26–20:32，Asia/Shanghai。本文是交接快照，不是后台实时状态。

**下一位 AI 先读本文，再全文执行 [v5.0 完整成品任务书](V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md)。旧的同日 `NEXT-AGENT-HANDOFF` 已被本快照替代。**

用户最新要求：“查阅目前情况，然后交给下一个 AI AGENT 的交接手册和任务书。goal 是尽可能完成到 v5.0 的完整版发布，也就是当前项目的‘完全体’至少给我出一版了要，不然一直没有成品出来，太慢了目前。”

## 1. 当前结论

- v4.5 原生监看预览已发布，用户实测反馈“可以，性能占用不错了”。继续已验证的 OBS 原生路线，无需重做播放器。
- **v5.0 完整产品尚未形成，也没有发布。** 可变路数监看和部分权限已做，但 Studio/TAKE、完整声音与业务回接、旧数据迁移、原生更新仍有实质缺口。
- 下一阶段以“一个统一入口、可从安装包使用旧功能的完整候选”为交付目标。优先复用原有业务服务和受认证管理页，避免所有页面重写 Qt；本地媒体继续只有一个 OBS 宿主。
- 目前不能按任务关闭数量推算产品完成百分比或可靠发布日期。先落实任务书中的 W1–W4 成品节点，再冻结最终候选；最终目标和 OBS 同条件性能要求不撤销。

## 2. 两个工作树：不要走错目录

| 位置 | 本次实查身份 | 用法 |
| --- | --- | --- |
| `/home/czl/projects/monitor_wall_czl` | `codex/windows-native-monitor@24fd012`；存在既有协作工具、AGENTS 和文档未提交修改 | **唯一共享账本入口**；保留全部原有改动，不能 reset/clean/stash 或切换此共享分支 |
| `/home/czl/projects/monitor_wall_v5` | **干净**，`codex/r1-001-auth-exec-audit@8709f3dd6256dc6622f6b0791936f2b7c1906212`，跟踪同名 origin 分支 | **当前实际开发代码**；此树已被上一位 Agent 切到 R1 工作分支，不能照旧交接误认还是 `codex/windows-v5-integration` |
| GitHub `dev` | API 本次查询为 `e8e60e2b0d27e6ab0ac1d070e7cfa5cfcb9a53a5` | PR #57 已合并；PR #58 尚未合并，下一位先重新查询 |

上一个交接所说“无任务占用、R1-001 可直接认领”**现在已失效**。共享账本本次起读快照为 revision57、28任务；本轮仅追加交接任务。根目录协作资料仍未整体提交，跨机器接手需先携带/正常同步这些文件，不能假定 GitHub 已含此账本。

## 3. 最新进行中工作：R1-001 / PR #58

- 负责人：`next-v5-t3-acp-1116-e364e40c`。本交接不冒用该 ID、不替其关闭/释放任务，也不修改其产品代码。
- [PR #58](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/58)：OPEN，head=`8709f3d`，base=`dev`。
- 两项提交：`b23eec1` 设备管理面 `node.manage` 与排队读会话复检；`8709f3d` 直接 sources 路由 camera scope、排队请求身份复检、legacy WebSocket 撤权轮询。
- 相对 dev 改4文件：`core/src/control_server.cpp`、`native-host/tests/product_http_runtime.py`、功能矩阵、历史执行记录；约140行增加/6行删除。
- 上一负责人记录本机：core CTest9/9、真实HTTP internal/preview 双模式通过、cluster42/42；事件服务本机8/8。**这是其记录，不冒充本轮重跑。**
- 本轮重新查 [CI 43848916218](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43848916218)：**completed/failure**，不再是“仍在跑”。9个 job success、`public-audit` failure、`windows-desktop-candidate` skipped。
- 实际失败日志：`tests/test_event_service.py:122`，`test_index_latency_and_outbox_ceiling_are_bounded`，p95 **139.45ms > 50ms**。可能存在 runner 调度抖动，但未经再次验证不能断言是假失败；后续 Web 构建/浏览器测试因该失败跳过。
- **本次没有为8709f3d进行完整 Windows OBS/Qt 媒体、NSIS 安装/升级构建。** Windows 契约 job 成功不等于这个源码的完整安装器通过。

第一条实质动作：核对现负责人是否仍运行；协调接续后重跑该失败 job，若稳定失败定位并修复，不能调大预算换绿。审查真实认证缺口、完成适用产品回归后按双语 PR 合入 dev，再推进 Studio。不要把等待该 job 当作停止所有不冲突准备工作的理由。

## 4. 已有可靠交付与可复用成果

| 交付 | 证据与边界 |
| --- | --- |
| v4.5 公开预览 | [Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.5)，15附件，prerelease；源码24fd012；Windows run43783406841 success，40便携/40安装/9恢复。用户认可可用性和占用；不可改其 Tag/已发布附件 |
| v5 快捷墙/目录权限 | PR #57 合入dev=e8e60e2；1–64格选择、共享目录、按账号保存/认证恢复；普通管理目录所有原生模式统一授权 |
| 最近完整 Windows 开发门禁 | [run43816563388](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43816563388)，**实际构建源码4291556**、版本5.0.0-dev.1，43便携/43真实安装/9恢复；1/4/7格动态最终像素通过。后续38f99b5/e8e60e2仅文档/合并身份，8709f3d的运行时代码新增不在此资格内 |

长期证据在当前代码树：`docs/qualification/windows-v5-quick-wall-2026-11-16.json`、`docs/windows-native-feature-parity.md`、`docs/windows-obs-parity-execution.md`。`/tmp` 原始回执只是辅助，不能保证保留。

v4.5 安装器70,249,426B；首启前安装逻辑200,614,374B / allocation204,053,288B。内部v5-dev.1安装器70,147,554B。**均不是完整业务融合后体积**。历史完整dev.18约1.459GB的主要成本是Electron、独立工具、OBS树、Python重复/常驻打包；当前Web模型+ORT仍约55.2MB，未做可用组件安装前不能直接删出总量。

## 5. 下一处真实产品缺口

当前 `core/src/obs_scene_runtime.cpp` 中 `ObsSceneRuntime::prepare` 在 `runtime_enabled=false` 时只是 `disabled_prepared`；`StudioController::take` 调控制文档路径。`native-host/src/product_window.cpp` 当前对原生 Preview 建图，Program 保持独立空图。

所以“调用 `/studio/take` 成功”**不证明原生 Program 已切换**。R2-001 必须把授权、revision/相机版本、宿主线程执行、真实OBS状态回读、成功回执和失败恢复接成一条链；不要在core启动第二套libobs，也不要仅新增未接线adapter或按钮。完整任务见任务书 W1。

## 6. 接手命令和所有权

```bash
cd /home/czl/projects/monitor_wall_czl
cat AGENTS.md docs/coordination/STATUS.md docs/coordination/HANDOFF.md
cat docs/coordination/TASKS.md docs/coordination/DECISIONS.md docs/coordination/PLAYBOOK.md
python3 scripts/agent-sync.py check
git status --short --branch
git worktree list

cd /home/czl/projects/monitor_wall_v5
git status --short --branch
git log -5 --oneline
gh pr view 58 --repo LiaoYK001/Web-Camera-Monitor-Wall --json state,headRefOid,statusCheckRollup
gh run view 43848916218 --repo LiaoYK001/Web-Camera-Monitor-Wall --json status,conclusion,headSha
```

**认领前先协调R1原负责人。** 用户本次已经要求交接，不必重新询问是否继续；先核实旧会话检查点和是否仍在写文件。若其仍工作，协调停止/交接后再编辑；若已停止，由协调者按PLAYBOOK记录转交并保留旧证据，再用自己的唯一会话ID认领。本文不代表旧进程已经停止，不得强占正在写入的工作。不要复制旧负责人ID。R2-001登记依赖R1-001，不能为赶进度谎报关闭；必要的真实依赖拆分先记录依据和剩余验收责任。

后续所有任务更新始终使用主checkout账本：

```bash
python3 /home/czl/projects/monitor_wall_czl/scripts/agent-sync.py \
  --root /home/czl/projects/monitor_wall_czl status
# 确认任务已可认领后，将任务ID和Agent ID替换为实际值：
python3 /home/czl/projects/monitor_wall_czl/scripts/agent-sync.py \
  --root /home/czl/projects/monitor_wall_czl claim TASK-ID \
  --agent UNIQUE-CLIENT-SESSION-ID --note '已核对代码、任务、前负责人检查点和修改范围'
```

## 7. 本轮做了什么

仅核对工作树、账本、代码缺口和GitHub最新状态，编写本交接和完整执行任务书；未重跑产品媒体测试、未改产品代码、未重跑/合并PR58、未构建/发布新安装包。本轮测试与链接检查结果写入HANDOFF-002及共享账本。

English: continue from the actual v5 worktree and coordinate the existing R1 owner. PR58 is open and its public CI has finished with one event-latency failure; it has no new full Windows installer qualification. Deliver an integrated v5.0 candidate through W1–W4, reuse existing business services, preserve v4.5 bytes and legacy data, and concentrate physical acceptance on the final candidate.
