# 当前决定与证据索引 / Decisions and evidence index

建立日期：2026-11-16。本页梳理仓库现有明确决定，不新增产品范围或发布授权。

| 决定 | 当前执行方式 | 原始依据 |
| --- | --- | --- |
| 2026-11-16 先交付 v4.5 Windows x64 原生监看预览 | 认证 RTSP/Profile、受支持已保存相机场景/布局、固定 Scene 投影；独立安装/数据；仅 prerelease | [AGENTS.md](../../AGENTS.md)、[v4.5 说明](../release-notes-v4.5.md) |
| 2026-11-11 完整融合 R0–R7 保持开放 | 预览交付不能替代完整 Studio/声音/业务回接/迁移/性能目标 | [完整任务书](../windows-webobs-wall-release-plan-2026-11-11.md) |
| 单一固定 OBS 原生 frontend/Qt 媒体所有权 | 产品集成放在上游子模块之外；普通本地监看不强制启动额外网关/转码 | [AGENTS.md](../../AGENTS.md)、[功能矩阵](../windows-native-feature-parity.md) |
| 日常开发集成到 dev | main 仅经过审查的版本发布流程更新；双语提交/PR；本轮不自动提交/推送 | [分支规则](../versioning-and-branches.md)、[贡献指南](../../CONTRIBUTING.md) |
| Android/容器交付继续暂停 | 保留历史和源码兼容；相关共享安全检查不省略；不要求其设备/镜像验收阻塞当前 Windows 预览 | [AGENTS.md](../../AGENTS.md) |
| 当前用户要求多 Agent 同步 | 项目限定 monitor_wall_czl；统一账本、认领、路线图、开发日志和交接 | 本聊天 2026-11-16 指定 “wall monitor”；[协作规则](PLAYBOOK.md) |

## 接手时特别注意

- 基线源码 `24fd012ea8ee130ffb9d42473c489d708c9326c3` 及当前任务状态见 [STATUS.md](STATUS.md)。基线只标识建立账本时的源码；不等于以后 HEAD，也不等于最终发布二进制。
- 建账时的 run `43744978600` 是历史失败候选；后续最终 run `43783406841`（source `24fd012`）整轮通过，v4.5 已发布为15附件 prerelease，PRE-003/PRE-004已完成。最新完整开发代码见 v5 工作树与共享账本，不重复构建/发布旧预览。
- [功能矩阵](../windows-native-feature-parity.md)和[逐轮执行记录](../windows-obs-parity-execution.md)包含不同日期/候选的证据。新进展必须带源码/运行身份，不能把某次 dev 门禁的绿色转写成完整 R 阶段完成。
- root ROADMAP 和旧 handover 中保留的 v4.0/更早内容用于历史背景；当前短入口统一为本目录生成页面。

## 决定变更格式

后续有新决定时记录日期、明确来源、替代哪项旧约定、涉及任务/验收、仍然有效的限制；在任务日志中登记证据位置。产品范围冲突由用户或既有明确决定解决，不由某个 Agent 的推测覆盖。

## 2026-11-16 · 完整版本从 v5.0 开始

来源：本开发会话用户明确要求“继续开发，后续完整版本发布均从v5.0开始”。取代仅对下一完整融合版沿用 v4.x 的预期；v4.5 保留已发布的原生监看预览身份和附件，完整目标、功能迁移、数据保留、原生更新与 OBS 同机性能门槛不变。当前仍以 Windows x64 开发为主，Android/容器等暂停范围不因 v5.0 编号自动恢复。开发记录使用 v5.0，不提前宣称完整稳定版合格或发布。实际代码工作树：`/home/czl/projects/monitor_wall_v5`，分支 `codex/windows-v5-integration`；共享账本仍由本集成 checkout 的 agent-sync.py 维护。

The latest explicit user decision assigns v5.0 onward to complete releases. Existing v4.5 preview bytes remain immutable. Full migration, data/update and OBS-parity gates remain open; numbering does not resume paused platforms or qualify publication.

## 2026-11-16 · 换 Agent 与 v4.5 实机反馈

用户要求交接给下一Agent继续，并明确反馈“v4.5测试下来可以，性能占用不错了”。记录为有效的用户实机正向定性反馈，继续OBS原生融合路线；本轮没有量化CPU/GPU/内存、OBS同条件基线或逐路硬解证据，不扩大为性能目标/完整v5通过。后续完整版本仍从v5.0开始，下一任务R1-001；交接见[NEXT-AGENT-HANDOFF-2026-11-16.md](NEXT-AGENT-HANDOFF-2026-11-16.md)。

The user requests another agent and reports usable v4.5 with good resource usage. Preserve this positive qualitative field feedback without inventing quantitative OBS parity or full-v5 qualification. Complete releases remain v5.0 onward.

## 2026-11-16 晚间 · 以v5.0完整成品为接续目标

用户再次要求核对当前情况，并交给下一AI交接手册和任务书，明确“尽可能完成到v5.0完整版发布”“完全体至少出一版”，认为长期没有成品过慢。本次交付以实际成品W1–W4节点组织既有R1–R7任务：复用已验证OBS媒体与旧业务/管理页，完成产品接线、同机组件、数据迁移、原生更新、完整候选及最终集中验收后发布；不扩展任意新功能，不改变真实性、安全、旧数据和性能要求。

最新手册：[V5-CURRENT-HANDOFF-2026-11-16.md](V5-CURRENT-HANDOFF-2026-11-16.md)；可直接交下一AI的执行任务书：[V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md](V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md)。本轮实查R1已有负责人，PR58@8709f3d仍OPEN、CI43848916218 completed/failure；未接管其代码或释放其任务。旧同日交接已标记被替代。用户偏好最终GitHub Release下载，不要求用户逐个试内部开发包；稳定公开仍按原最终验收与发布流程。

The user prioritizes a complete, usable v5.0 delivery. This handoff organizes existing work around installed-product outcomes; it does not waive feature, migration, update or qualification gates, nor transfer another active agent's task ownership.

## 2026-11-17 · 下一正式交付目标调整为v5.1

用户在rc.1独立核查后要求“继续优化，争取在v5.1版本rel正式版修复所有这些缺点后发布”，并明确后续用v5.1在本人Windows进行主要验证。下一完整修复交付转为v5.1，rc.1保留既有候选身份；先修可复现的迁移路径、缓存安装器完整性与版本比较，再补音频/输出/远端/离线及迁移更新、成本和长稳等现有缺口。开发、构建和中间回归由Agent继续，不反复要求用户试包；版本号/公开意图不意味着未实现功能或未测目标机性能已经合格。

实际新开发工作树`/home/czl/projects/monitor_wall_czl/.worktrees/v51`，`codex/v51-hardening`，基于origin/dev2258a37；统一账本继续在本checkout。保留此前工作树和未提交协作文件。Windows x64范围及Android/容器暂停决定不变。

The next requested official delivery is v5.1; the user's main Windows validation will use that version. Preserve historical releases and truthful evidence boundaries while continuing implementation, automated regression and release preparation.

## 2026-11-17 晚间 · 转交下一Agent完成v5.1

用户针对“v5.1尚未正式发布，多轨/输出/远端仍未补齐”的状态要求一份可直接交其他Agent完成的交接。本会话只整理交接、不另改产品或发布；V51-002由原负责人`codex-v51-20261117`明确释放为planned，下一Agent用自己唯一ID接手。最新代码`codex/v51-hardening@2f676e9`在`.worktrees/v51`，PR65仍OPEN，dev仍2258a37；Windows44057825506正在业务服务构建（预检查与OBS/Qt编译已通过），主验收/稳定发布未完成。

最新单文件入口：[V51-NEXT-AGENT-HANDOFF-2026-11-17.md](V51-NEXT-AGENT-HANDOFF-2026-11-17.md)。它替代旧v5.0接手续作快照，保留原完整功能/数据/性能要求并指定v5.1目标；旧的源代码/任务占用判断不再作为当前状态。
