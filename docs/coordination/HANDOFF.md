# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 303 · 2026-11-21T09:42:33+08:00（UTC+08）

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

rc.85（run 44848537440 @ bae0610 同 SHA 复现轮）completed=failure：entry-ui 于 program-after-take 失败——第六披露项整窗重绘停滞第三次持久命中、同 SHA 连续第二次命中：八采样通道/布局正确、tiles 0-3 摘要全窗恒定、tile 4 恰跳一次（52ae516d→f3f318a3、计数器 24→20）、progressError『Frozen final pixels on slot 1』、distinctClientCount=2、temporalProgress=false、staleTiles=[0,1,2,3]；同窗 26.469s 宿主渲染 9982→10822（~31.7fps）、六输入 serial 全 advance（maxFrameAgeMs≤113）、15 次 publish、feed 身份全观测；前端存活、崩溃面未命中（第四披露项开放）。rc.84/85 与 rc.83（全绿）产品代码逐字节相同（差异仅 test-only bae0610、且只在 nsis 段执行），排除装置修复引入停滞；同 SHA 连续两中对照 rc.83 同码通过，间歇性/宿主侧依赖成立。按判定计划：第三次持久命中→强化第六披露项、链路暂停、不派发 rc.86，交 Codex 主线程宿主侧诊断；bae0610 末段安装态验证随之顺延，十回执目标待主线程诊断后恢复。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
