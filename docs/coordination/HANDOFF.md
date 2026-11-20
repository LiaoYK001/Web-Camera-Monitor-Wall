# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 292 · 2026-11-20T21:38:29+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261120-02；阻塞：无；下一步：rc.74 结束后读 entry-ui/restore/installed-ui/nsis/restore-pair/legacy-import/lan/updater/upgraded-ui/size-split 全部回执；齐了把合并材料交 Codex 主线程审阅换基与合并顺序。rc.72 journal 间隙声明保留，需主线程产品侧结论。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

rc.75 run 44735378274 completed=failure：9b26035 记账修复生效、门禁首次越过 legacy-config-only-archive 并推进到安装入口的 program-streaming；Program 增益复过（controlRatios 1.0/1.001）。首个真实失败点为 Program 视频窗口断言（frames 26/ptsSpan 0.833s、首帧 4015ms、monotonic true），归因证据：同窗口宿主渲染 +421 帧、中继 streamConnected=true、包连接 140 packets/2 IDR@2.0s，且该启动 OBS 日志 6 次 WebOBS async video backlog（30 帧丢弃、间隙 2.689-3.000s）与 1 次 async timestamp jump——单消费窗口与输入侧解码停滞竞态，同 rc.62 记录的交付 vs 解码分裂，非产品逻辑缺陷；Windows 侧无法本机复现，做低风险有界重试修复 9c2b7af（共享 decodable_window 谓词、一次新连接重读、只对最后尝试记账、probeAttempts 披露、断言消息原样；持续饥饿仍两次失败），并同步更新既有关键帧窗口契约。Linux 语义复现（stalled→retry→healthy 接受、连续 stalled 拒绝、healthy 不重试）、契约 62 项 61 通过（唯一错误仍为 worktree 未初始化 OBS 子模块）、test_pixels 31 通过 2 跳过、py_compile/diff-check OK。派发 rc.76 run 44746006213 @9c2b7af（同输入），轮询中。运行器解码停滞本身保留为披露项（经启动标记），未宣告健康；rc.72 journal/fsync 窗口与硬终止明文暂存清扫两项继续开放交 Codex 主线程。EN: rc.75 passed the legacy-import phase (9b26035 effective) and failed the Program video-window assert: 26 frames over 0.833 s while the host rendered 421 frames, the relay reported a connected stream and the packet probe saw two IDRs 2 s apart - a single consumer window racing input-side async-backlog decode stalls, the documented rc.62 delivery-vs-decode split, not a product logic defect. Low-risk test-only fix 9c2b7af (shared decodable_window predicate, one fresh-connection retry, charge-last-attempt only, probeAttempts disclosure, verbatim message; sustained starvation still fails twice). rc.76 run 44746006213 dispatched at 9c2b7af. Runner decode starvation stays disclosed via boot markers; the rc.72 journal/fsync window and the hard-kill decrypt-staging sweep question remain open for the Codex main thread.

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
