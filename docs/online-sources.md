# 网站与直播源 / Website and live sources

本功能在 v4 开发分支集成。完整容器和 Windows x64 运行包内置 **yt-dlp 2026.8.19、Streamlink 8.6.1、Node 24.19.0、yt-dlp-ejs 和 curl-cffi**，并使用产品已有 FFmpeg。旧 v3.5 安装包没有这些新增工具，需要升级到包含此变更的完整版本；这里不代表已经发布新安装包。

The v4 development integration bundles yt-dlp, Streamlink, Node, yt-dlp-ejs and curl-cffi with the existing FFmpeg in the complete container and Windows x64 runtime. Older installers need a complete product upgrade. This document does not announce a new release.

## 三端及更新策略 / Three clients and release cadence

- **Docker/Podman 容器**：解析器和 Node 在独立 Python 3.12 运行环境中，按需解析、转发，不依赖主机 PATH/pip。
- **Windows x64 完整客户端**：同样工具进入 NSIS 运行包、文件摘要清单、许可证和 SBOM。`webobs-online-source.exe` 通过固定入口和 Job Object 持有 Python、JavaScript 解析器及 FFmpeg。
- **Android 独立客户端**：在相同 go2rtc 页面创建、导入和播放网站源；解析发生在所连接的容器或 Windows 后端。APK 不运行本机 OBS/go2rtc/FFmpeg，不需要安装 yt-dlp。

Containers and Windows x64 bundle the media tools; Android manages sources on its backend. From v4, the primary targets use `vA.B` feature releases and `vA.B.C` bug/security patches; see [patch delivery](patch-releases-v4.md). Future native Linux x86/ARM, Windows ARM and Windows 32-bit are normally qualified at major `vA.0` milestones, not every feature/patch release. This policy is not an existing platform qualification claim.

三主端从 v4 起采用功能版与修复补丁；解析器安全更新可按 `vA.B.C` 及时交付，仍需更新锁定摘要、对应源码、许可证/SBOM 和实际解析/播放回归。Android 使用更新后的后端解析器，不把第三方可执行命令下发到 APK。

## 接入步骤 / Adding a source

1. 管理员打开 **go2rtc 管理 → 添加网站与直播源**。需要 `settings.manage`；所有配置、播放和 API 仍经 `/api/v1/go2rtc/` 的产品认证代理。
2. 默认 **自动识别**：RTSP/RTSPS/RTMP 和常见 HLS/MP4 媒体链接直接接入，其他 HTTP(S) 网页交给 **yt-dlp**。也可明确选择 yt-dlp、Streamlink 或直接媒体地址。YouTube 直播网页优先使用自动识别或 yt-dlp，不能当作直接媒体链接；RTSP 摄像机可使用含认证信息的地址，凭据仅进入管理员私密配置。填写新的命名流。支持范围取决于上游 [yt-dlp 网站列表](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) 和 [Streamlink 插件](https://streamlink.github.io/plugins.html)，不承诺所有网页、登录/地域限制或 DRM 视频都可用。
3. 默认优先 **720p / 自动**；已识别 H264/AAC 优先直通，不兼容或未知编码在播放时用 FFmpeg 转换。可以选择直通或始终 H264。清晰度选择是偏好，站点可用轨道决定实际结果；Streamlink 无合适标注轨道时回退最佳轨道，并在需要转换时限制输出高度。
4. 点击 **保存命名流并重启 go2rtc**。上游 `/api/streams` 有意禁止新增 `exec`，因此产品通过管理员配置合并 API 保存固定模板，再重启并等待命名流可见。已有桥接播放/录像输入会短暂中断。先检查运行流和已保存配置中的重名；上游没有原子新增/配置修订接口，多位管理员同时编辑应协调操作。合并保留其他配置值，但上游可能重排 YAML 或移除注释。
5. 在官方流管理中测试播放；然后在下方 **检测并添加设备** 建档。在 Studio 选择该设备加入场景。Android、Windows 和浏览器共享同一后端设备目录。

Automatic selection sends RTSP/RTSPS/RTMP and common HLS/MP4 media URLs directly to go2rtc, and HTTP(S) webpages to yt-dlp. Explicit yt-dlp, Streamlink and direct modes remain available. YouTube live pages require a website extractor; authenticated RTSP addresses stay in private administrator configuration. Save a new name, test playback in the official UI, import the flow into the device registry, then select it in Studio. Saving merges the fixed source into administrator configuration and restarts go2rtc, briefly interrupting existing bridge consumers. The form checks active and stored names, but upstream provides no atomic create/revision API; coordinate concurrent administrator changes. YAML formatting/comments may be rewritten by upstream.

## 按需解析与编码 / On-demand resolution and codecs

配置保存原始网页地址的 base64url 编码，不保存易过期的解析结果；**base64 不是加密**，该配置和日志仍属私密管理数据。每次消费者连接/重连都会重新解析当前媒体地址。解析器使用固定参数向量，不经 shell；不接受网页提供的本机文件、任意命令或插件目录。输出仅可发布到当前 go2rtc 的回环 RTSP 端口。

yt-dlp 使用随包 Node/EJS，不在运行时下载远程 JavaScript 组件或自更新。解析器版本随整包升级。Linux 解析进程最终 `exec` 为 FFmpeg，go2rtc 直接持有它；Windows 固定工具的嵌套 Job Object 负责清理整棵进程树。Direct-only 不要求 OBS，也不持续转码。点播从开头按正常速率播放，未提供点播拖动或播放列表批量导入。

The private configuration stores an encoded original page URL, not an expiring resolved media URL. Base64 is not encryption. Resolution happens for each consumer connection; fixed arguments never pass through a shell. The bundled JS runtime does not fetch remote EJS components or self-update. Linux replaces the resolver with its FFmpeg relay; Windows owns descendants in a Job Object. OBS and continuous transcoding are not required. VOD plays from the beginning at normal rate; playlist imports and VOD seeking are outside this integration.

## 登录网站与 Cookie / Website login and cookies

由管理员自行准备 **Netscape 格式** Cookie 文件；页面只接受配置名，不上传、读取或显示文件内容：

| 后端 / Backend | 私密目录 / Private directory |
| --- | --- |
| 容器 / Container | `/config/webobs/go2rtc/cookies/<name>.txt`，目录 `0700`、文件 `0600` |
| Windows x64 | `%LOCALAPPDATA%\WebOBS\config\go2rtc\cookies\<name>.txt`，继承当前用户私密 ACL |

名称只允许 1–64 个字母、数字、下划线或短横线。文件最大 1 MiB，拒绝符号链接和路径穿越；Cookie 随私密 go2rtc 配置卷/Windows 数据目录及现有配置备份保存。Cookie 过期需替换。**产品登录 Cookie/Authorization 不会传给视频网站**；显式选择的网站 Cookie 用于解析登录页面和获取签名媒体地址。转发接受 User-Agent/Referer/Origin/Accept，不透传原始媒体 Cookie/Authorization：当前容器 FFmpeg 会在重定向时继承自定义请求头，不能保证每次跳转的凭据隔离。必须依赖媒体 Cookie/Authorization 的来源暂不支持，返回 `media_credentials_unsupported`。不要提交 Cookie、真实网页凭据、配置或原始日志。

Administrators supply a private Netscape cookie file for authenticated extraction and signed media URLs. Files are bounded and cannot be symlinks or arbitrary paths. The product login is never forwarded to websites. Raw media Cookie/Authorization forwarding is unavailable because the container FFmpeg inherits custom headers across redirects; such sources fail with `media_credentials_unsupported`. Website cookies remain in the private configuration/backup boundary and must be refreshed when expired.

## 诊断、构建与验证 / Diagnostics, building and validation

实际公开 YouTube 直播、冷导入、轨道解码、Studio 与重启保留的结果和复验命令见 [v4 接入验收](online-source-validation-v4.md)。Public live-source results and the full native UI recheck are recorded separately from synthetic fixtures.

- `website_resolution_failed`：检查网页、后端网络、Cookie 和解析器版本；确认视频未结束且具备访问权限。
- `live_resolution_failed` / `live_unavailable`：确认直播在线，尝试 yt-dlp 或直接媒体地址。需要 Streamlink 特有分段处理/复用的插件可能无法导出单个媒体 URL。
- `cookies_unavailable` / `cookies_permissions`：核对私密目录、配置名、格式和权限。
- `runtime_missing`：安装完整容器/NSIS；开发模式不会因系统偶然安装了工具而宣称完整支持。
- `media_credentials_unsupported`：此来源要求媒体请求直接附带 Cookie/Authorization，当前入口不透传这些凭据；使用可解析出签名媒体地址的来源。Raw media credentials are unsupported; use signed media URLs.
- 转发失败：检查网络和编码兼容性，尝试 H264。FFmpeg 原始 stderr 可能包含临时 URL/请求头，因此固定入口不公开它；管理员可查看 go2rtc 的连接与启动状态。

后端已配置的 `HTTP_PROXY`/`HTTPS_PROXY`（含小写形式）会按媒体输入协议传给 FFmpeg；`NO_PROXY` 和回环来源绕过代理。转发支持 HTTP CONNECT 代理，SOCKS/PAC 或 TLS 代理 URL 不在此入口支持范围内；不支持时返回不含代理凭据的 `proxy_unsupported`。代理是后端出站网络配置，不会存入流模板或发送给网页。FFmpeg 的 HTTP 代理选项见[官方协议文档](https://ffmpeg.org/ffmpeg-protocols.html#http)。

Configured backend HTTP/HTTPS proxies are selected per media input, respecting NO_PROXY and loopback bypass. The relay accepts HTTP CONNECT proxies; unsupported proxy types produce a fixed error without credentials. Proxy settings stay on the backend and are not saved in source templates or exposed to pages.

HTTP 媒体连接的短暂网络错误及 429/503 使用有界递增重试；正常点播结束不会无限重播。测试另实际断开首次媒体请求，确认真实解析器/转发/解码恢复。Transient HTTP network failures and 429/503 responses use bounded backoff; normal VOD EOF does not loop indefinitely. A real initial media disconnect is covered by the runtime fixture.

HTTPS/RTMPS 网站媒体转发显式开启 TLS 证书与 URL 主机名验证；普通 HTTP 媒体仍可使用。转发不携带原始网站 Cookie/Authorization，HTTPS 播放列表不接受明文分段；协议白名单不能限制 FFmpeg 内部 HTTP 重定向，所以不能据此宣称全部跳转都使用 TLS。容器使用系统 CA，管理员可通过后端 `SSL_CERT_FILE` 指定已有绝对路径 CA 文件；Windows FFmpeg 使用 Schannel 的系统/当前用户信任库。不要关闭证书验证。代理使用私有 CA 时，应配置后端信任；无效 CA 路径返回固定 `tls_trust_unavailable`。TLS 测试确认不受信任对端收到 HTTP 请求前已被拒绝；容器还验证显式可信 CA 可解码及主机名不匹配被拒绝，Windows 测试不向用户信任库安装临时 CA。

HTTPS/RTMPS inputs verify certificates and URL hostnames. Plain HTTP media remains available, and raw media credentials are never forwarded. HTTPS playlists refuse plaintext segments, but a protocol whitelist does not control FFmpeg's internal HTTP redirects; it does not guarantee TLS on every hop. Containers use system CAs (or an existing absolute backend `SSL_CERT_FILE`); Windows FFmpeg uses Schannel system/current-user trust. Configure backend trust for private proxy CAs; do not disable verification. `tests/online_source_tls.py` exercises actual TLS rejection before HTTP, plus trusted decoding and hostname rejection on Linux. Its Windows fixture does not modify the user's certificate store.

依赖锁位于 `go2rtc/online-source-dependencies.lock.json`，包含 Windows/Linux x64 轮子和 Node 的 SHA-256、大小（轮子）、许可证与对应 Python 源码归档身份。`scripts/install-online-source-runtime.py` 拒绝校验失败、路径穿越、符号链接与过大归档。容器 `online-source-runtime` 阶段和 Windows `stage-runtime.py` 共用该安装器。整包发布继续要求现有对应源码审查和不可变附件流程，不能仅因存在源地址就认为所有第三方源码已审查。

```sh
python tests/test_online_source.py
docker build -f docker/Dockerfile --target online-source-runtime -t webobs:online-source-tools .
docker run --rm --entrypoint /opt/webobs/online-source/python/bin/python3 \
  -v "$PWD/tests/online_source_media.py:/tmp/online_source_media.py:ro" \
  <complete-product-image> -B /tmp/online_source_media.py
node tests/online_source_runtime.cjs --image <complete-product-image>
```

前端：`pnpm typecheck`、`pnpm build` 及 `online-sources.spec.ts`。Windows 原生门禁增加无开发 PATH 的工具自检、真实本地网页/HLS → RTSP 解码、重连和消费者退出验证。Android 使用 `android/tests/test_emulator.py --serial <明确设备> --image <含解析器的完整产品镜像> --online-sources`，通过实际已安装 APK 验证同一表单、认证 MSE 解码与设备导入，保留设备数据。

Validation uses real locked extractors, FFmpeg and go2rtc against local synthetic MP4/HLS, plus authenticated browser/installed-APK workflows. It is not qualification of external websites, physical cameras, ARM devices, hardware audio or clean Windows installations. Record the exact source and candidate gates before announcing release readiness.
