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
- 本机网格/Qt/实际libobs引用及协议回归通过；真实Windows安装态1/4/7路动态画面与恢复门禁待执行。

Variable quick-wall selection is wired and locally tested; actual Windows final pixels/installation remain pending. This is not a complete-release qualification.
