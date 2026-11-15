# WebOBS Wall v4.5 原生监看预览版 / Native monitor preview

Windows x64，未签名预览版。原生监看优先，尚不是全部 WebOBS 功能的融合正式版。不提供自动更新，不进入稳定更新源，不替换旧 WebOBS 或原版 OBS。

Windows x64 unsigned preview. This delivers native monitoring, not the complete feature migration. No automatic updates or stable updater feed. Existing WebOBS and stock OBS installations stay separate.

## 第一次使用 / First start

1. 安装 `WebOBS-Wall-4.5.0-windows-x64-PREVIEW-UNSIGNED.exe`，从开始菜单 **WebOBS Wall v4.5 Preview** 启动。免安装 ZIP 请先完整解压，再运行 `bin/webobs-wall.exe`，不要直接运行 `obs64.exe`。
2. 首次填写用户名和密码，点击“创建首个管理员账号”。这是本预览版自己的账号；旧版账号和配置不会自动导入。
3. 点击“打开设备与系统管理”，在本机浏览器登录刚创建的管理员账号。手动添加 RTSP 摄像机并配置 Profile；URL、密码只填在自己的电脑，不要发到公开反馈里。设备配置目录仅向管理员开放，普通观看账号在原生窗口中只看到获准的摄像机。
4. 返回原生窗口，点击“刷新设备目录”，选择五个 Profile，点击“开始原生监看”。同一路重复选择会复用兼容来源。
5. 点击“保存布局”。关闭重开后需要登录，登录后恢复保存的摄像机选择/已保存场景。固定场景投影可打开两个；投影窗口 F11/双击切全屏，Esc 返回。

Install and launch the Start-menu preview entry, or fully extract the ZIP and run `bin/webobs-wall.exe`. Create a new preview administrator, open device management, sign in and manually add RTSP camera Profiles. Refresh/select five Profiles in the native window, start monitoring and save. Reopening requires authentication. Two fixed Scene projectors support fullscreen.

## 数据与后续更换版本 / Data and later replacement

- 配置和账号：`%LOCALAPPDATA%\WebOBS\NativePreview`。ZIP 版也使用此目录，并非随 U 盘移动的配置。
- 与旧版 WebOBS、原生原型和内部集成版的数据隔离。卸载保留本目录；旧版安装、账号、录像与配置不会被删除或迁移。
- 本版拒绝覆盖已安装的同一预览版。后续换包时先正常退出，在 Windows 中卸载预览版，再安装新包；不要手动删除上述数据目录。当前不承诺向完整融合版自动迁移。

Preview data lives in the separate LocalAppData directory above, including for the ZIP. Uninstall retains it and unknown files. Existing legacy data is neither imported nor removed. Replacement currently requires exit, uninstall and reinstall; preserve the data directory. Automatic migration to a future complete product is not yet qualified.

## 当前范围与限制 / Scope and limits

可用范围：原生账号/权限、手动 RTSP/Profile 设备目录、五路选择、已保存且受支持的相机场景、布局保存恢复、两固定 Scene 投影、视频输入进度、OBS 原有宿主统计和实际渲染设备显示。普通本地监看不启动 FFmpeg 命令行转码、MediaMTX 或 go2rtc。

尚未提供完整 TAKE/过渡/Program 输出、多轨音频与电平、录像/NVR/回放、PTZ/对讲完整流程、检测/事件叠层、网站来源、远端分发、旧版数据导入和原生自动更新。管理网页仍包含部分未来功能页面，它们在此包中不代表对应服务可用。保存的场景内容或设备配置改变后，当前保守行为可能要求重新登录/连接。

Basic RTSP/Profile monitoring and supported camera scenes are available. Full Studio TAKE/Program outputs, multi-track audio, NVR/recording, device-control workflows, analytics/events, online sources, remote distribution, legacy migration and native updates remain unavailable. Some management pages belong to the existing WebUI but their services are not included here.

Windows CI 使用五路合成 H.265 验证最终画面、断流、权限、重启及安装卸载；不代表真实相机、所有 H.265 格式、独显硬解、多显示器或目标机性能合格。硬件解码由 OBS/FFmpeg 与驱动能力决定；“实际渲染设备”为 NVIDIA 不等于已证明每路使用 NVDEC。尚未证明完整开销不高于 OBS，也未达到完整功能版的最终体积验收。

CI uses synthetic five-stream H.265 fixtures. Real-camera, hardware-decode, target-device OBS parity and full-feature footprint qualification remain open. A reported NVIDIA renderer does not prove per-source NVDEC.

校验下载附件的 `SHA256SUMS.txt`。反馈请提供版本、匿名摄像机编号、分辨率/帧率、显卡及问题步骤；不公开密码、摄像机地址、完整私密日志或真实画面。
