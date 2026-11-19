# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 270 · 2026-11-20T03:05:28+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261119-01；阻塞：无；下一步：等 rc.69（run 44587525224，源码 e955d9ea5d7947917a4a85292b923c5e91afc6f6，5.1.0-rc.69，soak_minutes=0）完成后用 python3 scripts/v51-ci-gate.py 44587525224 --sha e955d9ea5d7947917a4a85292b923c5e91afc6f6 --version 5.1.0-rc.69 读回执；通过则按 #67→#70→#71→#74→#75→#76 双语合入 dev，再从 dev 集成源码派发 5.1.0-rc.70、soak_minutes=120 的冻结候选并用 --freeze 复核。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

长稳门禁补上 Linux 回放回归（#74 提交 0686c2b）：假宿主、假时钟、假夹具发布进程重放同一个 soak_watched_inputs，夹具发布进程窗口内退出被重启并继续观察、不记成产品停滞，而输入停滞、进程树变化、私有内存/句柄增长、不可读进程、CPU 过低与回环服务退出仍分别失败；换回 1861627 的父提交即失败、换回修复版即通过。栈已按依赖重放推送：#75 da2fc15、#76 bf8c1ce（顶层完整 SHA bf8c1ce…，只差测试文件）。另外在临时 worktree 里把 #67→#70→#71→#74→#75→#76 顺序试合进 origin/dev：六个 merge 全部自动干净，合并树 native-host/tests/test_*.py 除两个需 --probe 的真机探针与未初始化 obs 子模块外全部 OK；workflow 在 soak_minutes>0 时 job timeout 为 260 分钟，够容纳 120 分钟长稳。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
