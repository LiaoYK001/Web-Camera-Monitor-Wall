# 当前进度 / Current status

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 299 · 2026-11-21T06:46:36+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

当前继续Windows x64 v5.1完整修复与正式交付准备；用户主要Windows验证使用v5.1。rc.1发行/基础门禁属实，但审查复现迁移/更新缺陷，完整声音、合成输出、远端/离线等仍需开发；不以历史候选或版本号认定完整通过。v4.5/rc.1公开字节与暂停平台不变。

基线源码：`24fd012ea8ee130ffb9d42473c489d708c9326c3`。本页是仓库证据快照，不是实时 CI/Release 查询。

## 基线事实与边界

以下为建账时核对的事实；后续进展以任务和日志中的新证据为准。

- 2026-11-17：v5.0.0-rc.1 prerelease 已发布；源码 8828532，run 43956468003 success，安装器 212,117,618 B / SHA-256 3d16014dab7700e6bc4f73c5c0bfba5700382c78fb3f24041589b58a4e67016c。
- 完整候选实际门禁：便携 52/52、安装态 52/52、恢复 9/9、35 组最终像素；真实 Program TAKE、NVR/事件/网站解析器、撤权、正常关闭/重启/崩溃清理和同机 rc.1→rc.2 升级通过。
- 安装树首启前 794,551,075 logical / 806,587,720 allocation B，6,972 files；候选 Release 13 assets 含安装器、latest.yml、校验和、验收摘要、来源清单、候选 SBOM 与回执。
- 必须保留的未关闭边界：目标机真实五路/逐路硬解/物理多屏/DPI/音频/两小时长稳、个人旧档案实际迁移、非空逐轨音频、OBS 合成录像/推流、LAN/Caddy 远端和部分分析叠层；候选不替代 R5/R7 或正式 v5.0 稳定验收。
- v4.5@24fd012 的15附件 prerelease 未变；v4.0 仍为 Latest；稳定 feed、main 和暂停的 Android/容器交付均未改变。
- 合成 CI、Linux fixture、GitHub-hosted Windows runner 和最终目标机/真实相机是不同证据层；本页不把候选通过写成目标机性能达标。
- 实际集成候选分支已合并 dev（merge 1ade2c5）；证据文档 PR #64 已合入 dev（merge 2258a37）。

## 阶段计数

| 阶段 | 已关闭/登记任务 | 当前状态 |
| --- | --- | --- |
| COORD 多 Agent 协作基础 | 11/11 | 完成 |
| R0 冻结基线与差距清单 | 4/4 | 完成 |
| PREVIEW v4.5 Windows x64 原生监看预览交付 | 4/4 | 完成 |
| R1 原生产品闭环与授权 | 2/2 | 完成 |
| R2 完整 Studio、监控墙和声音 | 3/5 | 未关闭 |
| R3 业务能力回接和按需组件 | 0/8 | 未关闭 |
| R4 旧数据迁移、更新与生命周期 | 2/6 | 未关闭 |
| R5 性能、体积与稳定性 | 0/2 | 未关闭 |
| R6 冻结完整 Release 候选 | 1/5 | 未关闭 |
| R7 集中实机验收与稳定交付 | 0/2 | 未关闭 |
| HOLD 暂停平台 | 0/1 | 暂停 |

## 接下来可认领

- `R2-002` P1 · 补齐多场景嵌套、编辑和不限五路布局。下一步：依据 STUDIO/LAYOUT 矩阵逐项接线，保留既有五路回归。
- `R2-004` P1 · 完成 Program 投影、多屏 DPI 和恢复。下一步：串行释放范围回到实际Windows管线和更新故障；之后认领继续固定场景媒体恢复与DPI目标验证
- `R3-001` P2 · 回接设备控制 PTZ、快照与对讲。下一步：复用已有 camera 服务协议，不旁路 camera scope。
- `R3-002` P2 · 回接输出、NVR、回放和证据。下一步：目标机多卷/掉盘/配额、seek/导出 hash 和大文件回放。
- `R3-003` P2 · 回接事件、检测、go2rtc 与网站来源可选组件。下一步：真实网站/直播、检测 provider/叠层最终像素、MQTT/HA 通知与重启恢复。
- `R3-004` P2 · 回接远端、离线同步、问题中心和诊断。下一步：逐项关闭 REMOTE/OFFLINE/OPS，远端兼容不等于恢复 Android 发版。
- `V51-006` P1 · 接通稳定打包身份与验收文件单一契约 / wire stable packaging identity with one acceptance-file contract。下一步：合入 #67/#68 后 rebase 本分支并转正式审查；真实 latest.yml 上传与集中验收回执仍待执行
- `V51-009` P0 · 接通原生产品真实 LAN/Web HTTPS 入口 / wire the real LAN HTTPS entry into the native product。下一步：#67 合入后 rebase 到 dev 并补原生窗口开关；随后随完整候选派发一次带该门禁的 Windows 运行

原始依据：[完整任务书](../windows-webobs-wall-release-plan-2026-11-11.md)、[功能矩阵](../windows-native-feature-parity.md)、[逐轮执行记录](../windows-obs-parity-execution.md)、[v4.5 范围](../release-notes-v4.5.md)。
