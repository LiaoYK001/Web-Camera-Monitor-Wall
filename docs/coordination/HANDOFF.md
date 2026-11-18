# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 242 · 2026-11-19T03:16:24+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 结果决定下一步：若停滞输入名与逐路包数证明回环仍流动而 Program 专用输入零帧，则需在宿主做有界媒体重开；否则按 #67→#70→#71→#74 顺序合并并复跑 rc.53。
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

Program 发布传输收敛为回环 RTMP：固定 Windows OBS 树以 -DENABLE_WEBRTC=OFF 构建且锁定 vcpkg 无 LibDataChannel，安装态没有 whip_custom/whip_output（rc.16 运行时清单有 rtmp-services.dll/obs-outputs.dll，无 obs-webrtc.dll），故下一次失败是 stream-service-unavailable。现用 rtmp_custom+rtmp_output+ffmpeg_aac 发布到同一按需私有 MediaMTX，中继对外 RTSP+WHEP；发布 URL 无 app 段、key=program，用固定 v1.18.2 实测路径为 program（RTSP 回读 h264+aac，视频包持续前进），带 app 段则变成 program/program 且中继关闭发布。门禁新增传输=WHEP 端点应答断言，构建契约拒绝 whip_* 并要求 rtmp_*，本机 47/47 通过。OBS 侧 WHIP 直推仍记为缺口。/ Program publishing now uses loopback RTMP (rtmp_custom+rtmp_output+ffmpeg_aac) into the same private relay because the pinned Windows OBS tree builds with -DENABLE_WEBRTC=OFF and the locked vcpkg archive has no LibDataChannel, so whip_custom/whip_output do not exist in the installed host; verified against the pinned relay that a URL without an app segment plus key program maps to path program (RTSP reads h264+aac) while an app segment produced program/program and the relay closed the publish. Gate adds transport and WHEP-endpoint assertions, build contracts now refuse whip_* and require rtmp_*, 47/47 pass locally; direct OBS WHIP stays a documented gap.

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
