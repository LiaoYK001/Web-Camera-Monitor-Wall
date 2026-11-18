# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 211 · 2026-11-19T00:37:12+08:00（UTC+08）

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

rc.50(run 44339344891)在 pixels-program-before-take-observed 失败：点名一个 OBS 报告 showing/active/PLAYING(mediaState=1) 但 serial 始终为 0 的输入(stalledMs=1370)。宿主每 2s 刷新一次逐输入健康，stalledMs 只能按 2s 刻度变化，且刚创建的 Program 专用源在媒体打开前 serial 必为 0，两者都不是画面冻结，旧计数器门无法判定。已提交 a92d11b(#67 codex/v51-r3-output)：等待改为实测推进(两次≥2.5s 快照必须出现更新的帧计数，仅覆盖已真正计过帧的输入)，零帧/仍在打开的输入改为记录并命名；状态快照新增 name/removed；回执新增 inputWaitLogLines(点名该输入的 OBS 日志行/MP: 行)、fixtureServerLogTail(脱敏 MediaMTX 推流日志尾部)与更多 media_playback 标记。已按顺序 rebase #70(78e8b60)→#71(3147f40)→#74(2e7695d) 并推送，从栈顶 codex/v51-r5-soak 派发 rc.51 run 44349201714(product_mode=true,complete=true,measure_obs_baseline=true,upgrade_previous=true,soak_minutes=0)。本地 test_build_contract 45 项、test_product_lan 24 项、test_encrypted_backup 10 项通过；本机无 Qt6/MSVC，C++ 仍以 Windows CI 编译为准。剩余：读 rc.51 回执判定零帧输入到底是哪一层；若仍是产品侧的“打开但静默”，需在宿主加有界重开并如实登记。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
