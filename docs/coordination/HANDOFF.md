# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 251 · 2026-11-19T14:45:03+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261119-01；阻塞：无；下一步：rc.52 结果决定下一步：若停滞输入名与逐路包数证明回环仍流动而 Program 专用输入零帧，则需在宿主做有界媒体重开；否则按 #67→#70→#71→#74 顺序合并并复跑 rc.53。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

V51-008 | worktree .worktrees/v51 (codex/v51-r3-output) | rc.59 run 44385767337 @ a5337f8 | failurePhase program-track-controls | 本轮只验证逐轨增益。结论：不是混音增益缺陷——回执同一文件内 432.2/2164.5=0.1997，说明第二轨被线性缩放 0.2 且第一轨未受影响；两轨都为 1.0 的对照低到 0.58/0.38，原因是门禁在录制文件前 3 秒做相关测量，那段仍含 owned 混音器 adelay 与后到音频轨的前导静音。产品混音图未改。修复只在测量层：pixel_windows 新增 steady_tone_window()（跳过前导静音、要求半窗一致 ±25%，无连续窗口以实测数值失败），隔离/静音/增益都改用它，并新增同配置二次录制的 1.0→1.0 对照（0.8–1.25）；原阈值不变。本机 Fedora 复现 1250/1850ms 前导静音得 1.63/0.50，与 rc.59 的 1.716/0.522 同形；稳态窗口回到 1.000/0.200；写错轨(0.2)与忽略增益(1.0)仍被判失败；全静音报无连续窗口。test_build_contract 47/47、test_pixels 28/28（2 跳过）。已派发 rc.60 run 44474401536 @ 3c9d6f67591aece94a69a8c5d7bc2beeadc4f8cd（product_mode/complete，soak 0）。 / Diagnosis: mixer gain was correct (0.1997 in the same file); the reference window held lead-in silence. Fix confined to the measurement layer plus a 1.0-to-1.0 control; thresholds unchanged; rc.60 dispatched.

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
