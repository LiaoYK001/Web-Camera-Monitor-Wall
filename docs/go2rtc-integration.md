# go2rtc 协议转换 / go2rtc protocol bridge

## 何时使用 / When to use it

摄像机网页首页不是媒体地址。Canon VB-C60 使用 WV-HTTP；其 `/-wvhttp-01-/video.cgi?v=jpg:640x480` 是 MJPEG 视频入口，`/-wvhttp-01-/GetOneShot` 是快照。自动检测现在能识别该型号首页并验证同一设备的视频入口；其他普通网页会提示提供媒体地址。

当前账号 Web 监控的网关入口通过 MediaMTX 拉流，不能直接把 HTTP MJPEG 当成 RTSP。可以先用 go2rtc 调用 FFmpeg 转为 H.264，再把 RTSP 输出作为普通视频源添加。这样继续使用项目现有的账号权限、布局同步、监控播放器和 OBS 合成能力。

A camera landing page is not a media URL. Canon VB-C60 uses WV-HTTP: `/-wvhttp-01-/video.cgi?v=jpg:640x480` serves MJPEG, while `/-wvhttp-01-/GetOneShot` supplies a snapshot. Detection recognizes this model's landing page and validates its same-origin stream. Other HTML pages prompt for an actual media URL. The current account Web playback gateway cannot ingest HTTP MJPEG as RTSP. Use go2rtc with FFmpeg to convert it to H.264 RTSP, retaining the project's account permissions, layout synchronization, player and OBS composition.

## 配置 / Configuration

1. 在**后端所在系统**安装 go2rtc 与 FFmpeg。Windows 原生开发模式的后端运行在 WSL，因此转换器也放在同一 WSL 发行版最简单。已验证 go2rtc `v1.9.14`。
2. 复制 [配置示例](../deploy/go2rtc.example.yaml) 到仓库外的私有目录，替换媒体 URL。管理接口使用 `127.0.0.1:11984`，RTSP 使用 `127.0.0.1:18554`，避开现有 MediaMTX 的 `8554`。配置及日志可能包含设备地址/凭据，不要提交。
3. 启动 `go2rtc -config /private/go2rtc.yaml`。FFmpeg 会在有人观看时按需启动。
4. 在“设备与来源 → 添加 → 自动检测”输入 `rtsp://127.0.0.1:18554/legacy_camera`，保存并加入场景。此处 `127.0.0.1` 指**项目后端**，不是安卓平板或 Windows 浏览器；客户端继续访问原来的监控墙地址。
5. MJPEG → H.264 会消耗转换服务的 CPU；该示例只转换视频，不虚构音轨。退出 go2rtc 会使对应来源离线；它目前是独立可选服务，不由项目开发启动器自动管理。

Install go2rtc and FFmpeg on the backend host (the same WSL distribution for Windows native development). Copy the example outside the repository, replace its media URL and run `go2rtc -config /private/go2rtc.yaml`. Add `rtsp://127.0.0.1:18554/legacy_camera` through normal source detection. Loopback refers to the backend, not the viewing tablet/browser. Ports 11984 and 18554 avoid the existing MediaMTX service. Conversion starts on demand and consumes CPU; this example supplies video only. Keep private configuration and logs out of Git. This is an optional standalone service; the development launcher does not supervise it yet.

## 后续源码集成边界 / Future source integration

推荐保留清晰分工：go2rtc 负责设备协议适配与必要的格式转换，MediaMTX 负责现有媒体分发，OBS 负责合成/输出，项目服务端负责账号、凭据与权限。后续可添加 go2rtc 服务管理和服务端 API 适配器，按账号注册/清理流并代理诊断。管理 API 不直接暴露给客户端；如果纳入源码，使用独立、锁定版本的子模块，记录许可证与升级流程，避免直接复制零散源码。当前提交提供配置和接入说明，尚未实现上述自动管理，也未添加源码子模块。

Keep responsibilities explicit: go2rtc adapts device protocols and converts formats when needed; MediaMTX handles current distribution; OBS composes and outputs scenes; the application owns accounts, credentials and authorization. Future integration can supervise go2rtc and register/clean up streams through a server-side API adapter, with account-scoped diagnostics. Do not expose its management API directly to clients. If vendoring the source, use a separately pinned submodule with license and upgrade documentation. Automated lifecycle management and a source submodule are not implemented by this change.

## 参考 / References

- [Canon VB-C60 官方手册 / official manual](https://downloads.canon.com/cpr/software/nvideo/VB-C60_User_Manual.pdf)
- [go2rtc 官方仓库 / official repository](https://github.com/AlexxIT/go2rtc)
- [FFmpeg 输入与 MJPEG 转码 / FFmpeg and MJPEG conversion](https://github.com/AlexxIT/go2rtc/blob/v1.9.14/internal/ffmpeg/README.md)
- [RTSP 输出 / RTSP output](https://github.com/AlexxIT/go2rtc/blob/v1.9.14/internal/rtsp/README.md)
