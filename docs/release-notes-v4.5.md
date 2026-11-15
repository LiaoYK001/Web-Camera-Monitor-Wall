# v4.5 原生监看预览版 / Native monitor preview

**Windows x64 · 未签名 · GitHub Pre-release · 不进入 Latest 或稳定更新源。**

用户 2026-11-16 选择先使用原生监看版。本次不代表完整融合、旧数据迁移或 OBS 性能目标完成；Android、容器和稳定更新源保持原状。

The user requested a usable native-monitor preview before complete migration. This unsigned Windows-only prerelease does not change Latest, stable feeds, Android or containers. Full migration and OBS parity remain unqualified.

## 下载后 / Getting started

运行 `WebOBS-Wall-4.5.0-windows-x64-PREVIEW-UNSIGNED.exe`，从开始菜单 **WebOBS Wall v4.5 Preview** 启动；或完整解压 ZIP，运行 `bin/webobs-wall.exe`。先核对 `SHA256SUMS.txt`，按附件 `START-HERE.md` 创建预览版账号、手动添加 RTSP/Profile、刷新选择五路并保存布局。

Use the installer/Start-menu entry or extract the ZIP and run `bin/webobs-wall.exe`. Follow `START-HERE.md` to create a preview account and manually add camera Profiles.

## 可用范围 / Included

- 单一 OBS 32.1.2 原生 Qt 媒体宿主；普通本地 RTSP 不启动浏览器播放、FFmpeg CLI 转码、MediaMTX 或 go2rtc。
- 账号和逐摄像机/Profile 权限、持续核验、五路选择和兼容来源共享。
- 受支持的已保存相机场景、布局保存/认证后恢复、两个固定 Scene 投影及全屏。
- 输入推进/停滞、实际渲染设备、OBS 原有宿主统计、固定本机控制地址和退出/崩溃回收。

One native OBS/Qt host provides authenticated camera/Profile monitoring, source sharing, saved camera scenes/layouts, fixed projectors, input/renderer diagnostics and supervised lifecycle.

## 数据与缺项 / Data and limitations

预览版独立使用 `%LOCALAPPDATA%\WebOBS\NativePreview`，与旧版、原生原型和内部集成版分开；不导入或覆盖旧账号、设备、布局、录像。卸载保留预览版数据。后续换包先退出并卸载预览版，再安装新包；没有自动更新或合格的就地升级路径。

完整 TAKE/过渡/Program 输出、多轨音频、电平、录像/NVR/回放、PTZ/对讲完整流程、检测/事件、网站来源和远端分发尚未提供。部分管理菜单来自现有 WebUI，不代表相应后台服务已接入。

Data is isolated and retained on uninstall; legacy data is not imported or overwritten. Replacement requires exit/uninstall/reinstall. Full Studio outputs, multi-track audio, NVR, device-control workflows, analytics/events, online sources, remote distribution and native updates remain unavailable.

## 验证 / Qualification

前置 dev.96（run 43730700943）便携/实际安装各 38 项及恢复 I/O 九项通过。v4.5 使用自身版本、安装项、默认隔离目录和预览标识重新构建验收；最终源提交、安装字节、逐项结果和哈希见附件 `v4.5-qualification.json`、`SHA256SUMS.txt`。

Windows CI 以合成五路 H.265 检验最终窗口帧、来源共享、断流、撤权、多投影、重启、进程回收及安装卸载。不是物理 Windows 10/11、真实相机、独显硬解、多显示器、长稳或目标 13900HX/RTX 4090 Laptop 的 OBS 同机对照。渲染器显示 NVIDIA 不证明逐路 NVDEC；当前安装大小仅对应预览范围。

The final preview is rebuilt/requalified with its actual identity and isolated default data path. Receipts correlate source and installer bytes. Synthetic CI does not qualify real cameras, per-source hardware decoding, physical target-device OBS parity, long stability or complete-product footprint.

源码附件含 WebOBS、固定 OBS/go2rtc 子模块及外置补丁；匹配第三方源码、构建清单和许可证随 Release 提供。反馈勿上传摄像机 URL、口令、完整私密日志或真实画面。
