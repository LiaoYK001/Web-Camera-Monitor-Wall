# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 259 · 2026-11-19T23:43:15+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261119-01；阻塞：无；下一步：读 rc.65 的 audioMixHelperWatch：若同一 FFmpeg 混音在停止前就消失且宿主仍声明 mixers 2，则问题在混音生命周期而非 Program 停止路径，按身份定位到 product_scene/product_output 的混音持有；若只在停止后消失，则检查停止路径是否释放了仍需的混音或未回收退出码。同轮继续核对 NSIS 安装是否跑到，齐全才合入 dev 并派发 soak_minutes=120。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

rc.64 通过 49 项：关键帧窗口读取在 Windows 首次通过（首次推流 89 帧/跨度 3.866s/首个可解码帧 2437ms/包探针 3 个关键帧包），恢复推流 65 帧/跨度 2.2s 通过，逐轨静音·增益·偏移首次取得 Windows 声学实测。新的第一失败为辅助进程归属：停止 Program 输出后两个宿主拥有的 FFmpeg 混音进程只剩一个，而宿主仍报 mixers: 2、processExitCode: -1。已加身份观察（阶段开始/停止前/停止后三采样 + 脱敏命令行 + 宿主声明），断言仍为精确 PID 集合相等。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
