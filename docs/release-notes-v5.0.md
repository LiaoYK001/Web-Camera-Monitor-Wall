# v5.0 完整 Windows 融合版开发草案 / Complete Windows integration draft

状态：开发中，未冻结、未发布。用户明确要求后续完整版本从 v5.0 开始。
Status: in development, neither frozen nor released. Complete releases start at v5.0 by explicit user decision.

v4.5 保留为已发布的原生监看预览版，不修改其安装包、标签或资格记录。v5.0 继续采用单一固定 OBS/Qt 媒体宿主，接回现有产品功能；普通本地监看不强制额外网关、转码或第二套 libobs。

## 必须完成 / Required gates

- 全入口账号/摄像机权限、真实 Studio/Preview/Program/TAKE、布局与多投影。
- 音轨、监听与电平；设备控制；录像、NVR、回放与证据；事件、检测、网站来源及远端功能的实际产品接线。
- 旧版和预览版数据映射、备份恢复、原生更新及安装/卸载/崩溃生命周期。
- 完整功能和按需组件的 CPU/GPU/内存/体积归因，稳定性与目标机真实五路 OBS 同条件对照。
- 同源码构建、真实安装自动化、源码/依赖/许可证和最终集中实机验收。

Authentication, Studio/TAKE, media/audio/business integration, migration, native updates, lifecycle, full-cost qualification and final physical-device acceptance remain required. Internal builds, isolated modules, synthetic CI and successful packaging do not qualify a complete release.

当前 Windows x64 范围不因编号变为 v5.0 自动扩大；Android/容器等暂停交付需后续明确决定。Stable publication and feed changes require the versioned release process and passed gates, not this draft.

## 开发进展 / Development progress

- 快捷监看从固定五路扩为有界1–64路，默认五路；选择目录共享，保留按账号保存/恢复和观看前授权。
- 本机网格/Qt/实际libobs引用及协议回归通过；Windows内部版本5.0.0-dev.1的便携/实际安装1/4/7路动态画面与恢复门禁已通过。

Variable quick-wall selection is wired and locally tested; actual Windows final pixels/installation pass for source4291556. This is not a complete-release qualification.

原生宿主模式的普通设备配置目录统一要求 `device.manage`，不再只依赖v4.5预览标志。观看账号继续从原生过滤接口取得获准目录；预览与非预览实际HTTP均验证403及原生授权目录，非原生旧接口兼容仍保留。本轮内部Windows整轮已通过，完整R1审计仍开放。
Native-host management catalogs consistently require device.manage across preview/internal modes. Native viewers retain their scoped catalog, and legacy non-native compatibility is tested separately. This internal Windows run passes; complete all-entry authorization qualification remains open.

本轮资格 / Current scoped qualification: source`4291556`, Windows[43816563388](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43816563388)，便携/实际安装各43项、恢复9项通过。详见[脱敏回执摘要](qualification/windows-v5-quick-wall-2026-11-16.json)。这不是完整v5.0候选或发布授权，内部安装器保持publicationForbidden。 / The43/43/9 internal result does not qualify a complete release or public installer.
