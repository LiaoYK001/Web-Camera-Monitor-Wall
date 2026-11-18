# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 212 · 2026-11-19T00:50:50+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.33 绿后双语合并 #67 进 dev；#71/#70 base 改 dev；目标机声学/串音与安装包绑定仍在用户集中验收，不得写成通过
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR

## 最近一次同步

审阅 #70 时发现并修掉恢复回滚的半对缺陷：recover_interrupted 的“配置未落盘”分支只把旧配置放回原位，却忽略同一交换窗口里已换出的旧 OBS 档案（journal 记录了 nativeRollback 却从未使用），普通启动因此会读到缺失的 OBS 档案，旧档案永远停在 .webobs-native-rollback-* 无人认领。现在回滚分支成对收回两半；若配置已落盘且后续启动重建了活动档案，改为把这些字节挪到 .webobs-native-parked-* 保存并落下与已落盘配置成对的档案副本（不再报 inconsistent 拒绝启动），恢复失败路径同样改为挪开而非 shutil.rmtree 删除活动档案。本机 tests/test_encrypted_backup.py 12 项通过且去掉本修复两项新测试即失败（可证伪）；安装态门禁 backup_restore_windows.py 新增第二个交换窗口（OBS 档案换出后、配置落盘前）终止真实恢复进程再从安装入口启动，断言两半回到旧对且不再有滞留 parked/rollback。已提交 be25901(#70) 并按顺序 rebase #71=b3653a4、#74=eb1c61f 后推送；rc.51 仍 pinned 在旧栈顶 2e7695d 运行中，不重复派发。剩余：读 rc.51 回执判定 Program 捕获窗口内的冻结槽位成因；两个交换窗口的 Windows 门禁结果需新 run 回执。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
