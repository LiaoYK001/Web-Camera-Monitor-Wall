# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 271 · 2026-11-20T03:34:48+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261119-01；阻塞：无；下一步：rc.70 完成后执行 python3 scripts/v51-ci-gate.py 44599567300 --sha ed25609c58933b10c52f4f86fd98369ad6d0d489 --version 5.1.0-rc.70；通过则按 #67→#70→#71→#74→#75→#76 双语合入 dev（已在临时 worktree 试合过六次均无冲突），再从 dev 集成源码派发 5.1.0-rc.71、soak_minutes=120 的冻结候选并用 --freeze 复核，最后以 GitHub prerelease 提供安装包下载链接。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

rc.69（run 44587525224）首次跑到 NSIS 安装态：NSIS 新装、便携门禁、TAKE 像素、录像/发布双音、总线隔离、逐轨静音/增益（比值 1.01/1.005，降至 0.201）/偏移、设备操作、录像失败路径共 45 项通过，随后停在 program-publish-disconnect，failureDetail 只有 'AssertionError: '（裸 assert ui(...) 无消息），lastUiFailure 还停留在启动阶段。定位：ui() 返回 False 有两种原因——本次启动 product-state.json 不可用，或 UI Automation 拒绝被拥有窗口——空消息把两者混在一起。修复 4a79201：state() 记录 lastStateObservation（state-file-count/state-file-unreadable/state-from-other-boot），ui() 在提前返回前记录 lastUiUnavailable（matchedWindows、reportedRoles、用 user32 IsWindow+GetWindowThreadProcessId 现场判定的 reportedHandles：gone/other-process/frontend），发布开关改用 ui_control（仅窗口暂不可寻址时有界等待并记录 productControlWaits；真实 UIA 拒绝不重试，因为点击从未发生），failure_detail() 在无消息断言时附上判定。发布验收与阈值未改。栈按依赖重放推送：#70 b25624c、#71 324413b、#74 8996b94、#75 0f59dc7、#76 ed25609（顶层完整 SHA ed25609c58933b10c52f4f86fd98369ad6d0d489，相对 bf8c1ce 只差这两个文件 194+/4-）。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
