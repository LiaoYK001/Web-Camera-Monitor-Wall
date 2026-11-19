# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 268 · 2026-11-20T02:25:35+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261119-01；阻塞：无；下一步：rc.69 run 44587525224 @ e955d9ea5d7947917a4a85292b923c5e91afc6f6（soak_minutes=0，监视日志 /tmp/watch69.log）。完成后：python3 scripts/v51-ci-gate.py 44587525224 --sha e955d9ea5d7947917a4a85292b923c5e91afc6f6 --version 5.1.0-rc.69。通过则核对同 SHA 的 nsis/installed-ui/restore-pair/legacy-import/lan/updater/upgraded-ui 回执；失败则从新回执首个失败点继续，并先读 programTrackGain.toneReadings（本轮起参考与复测的分段读数与带宽峰值都在断言之前写入）。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

rc.68 run 44577184643（源码 2c0e99dc，soak_minutes=0）已完成并失败：49 项通过，首个失败点 phase=program-track-controls、detail=AssertionError: the unchanged gain configuration measured differently twice: {'440': 0.58, '880': 0.359}（checkpoint program-mix-audible-per-track gain reference repeat）；该轮只有 entry-ui 与 restore 两份回执，NSIS 安装、逐轨增益、成对恢复均未跑到。本轮只验证一个已定位失败点：测量把整窗一次性投影当成音调本身。用真实 FFmpeg（ffmpeg 8.1.3，本机 Fedora）回放录制形状复现——在 1.2 s 处丢掉 40 ms 音频块后，440 Hz 的整窗投影从 2890.0 掉到 991.3（比值 0.343）、880 Hz 掉到 0.814；偏离标称 0.4 Hz 时比值 0.286，而音调始终明显可闻。混音重采样带漂移校正并在流抖动时交接丢弃块，相位断裂后整窗投影读的是各段之和。修复 768fa07：幅度改为 0.5 s 短段在 ±1 Hz 带宽内最强投影的平均（平均而非中位数，保证窗口内静音仍按比例低估，lead-in 保护仍有效），并把增益对照的测量证据写在断言之前（rc.68 的比值是失败回执里唯一的数字）。验收阈值一字未改。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
