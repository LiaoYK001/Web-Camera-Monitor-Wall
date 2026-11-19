# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 272 · 2026-11-20T04:33:37+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261119-01；阻塞：无；下一步：rc.71 完成后执行 python3 scripts/v51-ci-gate.py 44609775780 --sha cdfe8182a4928a75d4eff31b7afe0b110f3bde92 --version 5.1.0-rc.71，并按 lastUiFailure.code 分支：window-handle-gone→查产品恢复路径为何销毁/重建顶层窗口；window-pid-mismatch→查装置读到的句柄是否过期；recoveredAfterAttempts>0→门禁已自愈，继续读后续 restore-pair/legacy-import/LAN/updater/upgraded-ui。若再次只是装置侧改动就要重编 OBS，则新增一个复用已发布候选安装包与当前测试脚本的 Windows 快速复测入口（完整候选仍优先，不阻塞出包）。六个 PR 的 head public CI 全绿且顺序试合无冲突，通过后再按 #67→#70→#71→#74→#75→#76 双语合入 dev 并派发 soak_minutes=120 冻结候选。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

rc.70（run 44599567300，源码 ed25609c…）再次停在 program-publish-disconnect，但新判定把范围缩小了：failureDetail 明确是断线后恢复推流的第二次开关；productControlWaits 显示首次调用即被 UI Automation 拒绝（unusableAttempts 空、lastUnavailable=null），不是本次 product-state.json 不可用；lastUiFailure 仍只有共享的 initialize/product-window，因为 product-ui.ps1 对 FromHandle 返回空与 Current.ProcessId≠FrontendPid 抛同一个 code，且该 code 在  赋值前设置，与启动阶段 wait_for(ui('inspect')) 的正常等待无法区分。修复 460789d：拒绝分开发回 window-handle-gone / window-pid-mismatch，并在触碰任何控件之前最多再问三次（400 ms，点击尚未发生）；Python 把 window_owner() 的现场判定写进 lastUiFailure.reportedHandles（gone/other-process(N)/frontend）。发布验收与阈值不变。栈再次重放：#70 3e485f9、#71 6c86adb、#74 bab66ab、#75 3bb51fa、#76 cdfe818（顶层完整 SHA cdfe8182a4928a75d4eff31b7afe0b110f3bde92，相对 ed25609 只差 3 个文件 37+/5-）。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
