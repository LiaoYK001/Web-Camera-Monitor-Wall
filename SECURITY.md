# Security Policy

## Reporting a vulnerability / 漏洞报告

Please avoid opening a public issue for a suspected vulnerability. Use the repository's private vulnerability reporting option under **Security → Advisories → Report a vulnerability** when available. If that option is unavailable, contact the maintainer privately through the contact method listed on the maintainer's GitHub profile. Include reproduction steps and affected versions, but never include live camera credentials, private RTSP URLs, recordings, or unredacted logs.

请勿为疑似安全漏洞直接创建公开 Issue。仓库支持时，请使用 **Security → Advisories → Report a vulnerability** 私密报告；若该入口不可用，请通过维护者 GitHub 个人资料中列出的联系方式私下联系。报告可包含复现步骤和受影响版本，但不得包含真实摄像头凭据、私有 RTSP 地址、录像或未脱敏日志。

## Credential handling / 凭据处理

- Keep real configuration in a local `.env` file. Files matching `.env*`, `secrets/`, common private-key formats, recordings, build directories, and test artifacts are excluded from Git and the Docker build context; `.env.example` is the only exception.
- Prefer `WEBOBS_RTSP_URL` through a protected environment file over the `--rtsp-url` command-line option, because command-line arguments can be visible in process listings. Restrict access to the host, Docker daemon, environment file, and generated recordings.
- The application redacts credentials embedded in `rtsp://` and `rtsps://` URLs before emitting OBS or configuration logs. Automated tests fail if the test username or password appears in captured logs.
- If a real credential is ever committed or posted publicly, rotate it immediately. Removing it from the latest commit is not sufficient because Git history and caches may retain it.
- Real-camera acceptance writes recordings under ignored `recordings/` and a second-pass sanitized log under ignored `tests/artifacts/`. Do not upload either artifact publicly, even when the automated credential check passes.
- Run `tests/run-public-audit.ps1` or `tests/run-public-audit.sh` before every public commit. The audit inspects the Git index rather than untracked local configuration, rejects sensitive/generated paths and high-confidence credential material, allowlists only known RTSP fixtures, and verifies the pinned OBS submodule.
- The bundled browser editor uses only same-origin static assets, REST, and WebSocket connections. It has no analytics, external font, CDN, or source-map dependency; treat browser profiles, screenshots, and pasted replacement URLs as sensitive nonetheless.
- Server-rendered browser sources are denied by default. Approve exact trusted origins through `WEBOBS_BROWSER_ALLOWED_ORIGINS`; private/local destinations require the separate `WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS=true` opt-in. An approved page can load subresources, so the allowlist is an administrator trust boundary rather than a complete content sandbox.
- Browser source URLs reject userinfo. API and product logs hide query/fragment values; the ephemeral CEF profile is mode `0700` and is deleted before startup and after graceful shutdown. Do not put long-lived dashboard tokens in committed scene fixtures or public diagnostics.
- M6 credentials are accepted only as an absolute username/password file pair. Use the `compose.m6-auth.yaml` secret mounts, keep source files under the ignored `secrets/` directory with host access restricted, and never place credential values directly in Compose, `.env.example`, command lines, logs, or issue reports.
- HTTP Basic does not encrypt credentials. For any remote access, terminate HTTPS at a trusted reverse proxy, allowlist only its externally visible HTTPS origin, block direct access to the backend port, and keep liveness/readiness payloads free of configuration details. Native TLS and a reviewed Internet-facing deployment remain unfinished M6 work.

- 真实配置应保存在本地 `.env`。除 `.env.example` 外，`.env*`、`secrets/`、常见私钥格式、录像、构建目录和测试产物均不会进入 Git 或 Docker 构建上下文。
- 相比 `--rtsp-url` 命令行参数，优先通过受保护的环境文件提供 `WEBOBS_RTSP_URL`，因为进程列表可能暴露命令行参数。同时应限制主机、Docker daemon、环境文件和录像的访问权限。
- 应用会在输出 OBS 或配置日志前，隐藏 `rtsp://` 和 `rtsps://` URL 中的凭据；自动化测试会检查测试用户名和密码没有出现在日志里。
- 若真实凭据曾被提交或公开发布，应立即轮换。仅从最新提交删除并不安全，因为 Git 历史和缓存仍可能保留该凭据。
- 真实摄像头验收会把录像写入已忽略的 `recordings/`，并把二次脱敏日志写入已忽略的 `tests/artifacts/`。即使自动凭据检查通过，也不要公开上传这些产物。
- 每次公开提交前运行 `tests/run-public-audit.ps1` 或 `tests/run-public-audit.sh`。审计只检查 Git 索引而不会读取本地未跟踪配置；它会拒绝敏感/生成文件及高置信度凭据，只允许已知 RTSP 测试占位符，并验证 OBS submodule 固定提交。
- 随镜像提供的浏览器编辑器只使用同源静态资源、REST 和 WebSocket，不包含分析脚本、外部字体、CDN 或 source map；但浏览器资料、截图及粘贴的新地址仍应按敏感信息处理。
- 服务端浏览器源默认拒绝。只通过 `WEBOBS_BROWSER_ALLOWED_ORIGINS` 批准精确且可信的 Origin；私网或本地目标还需单独设置 `WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS=true`。获准网页仍可加载子资源，因此允许列表是管理员信任边界，不是完整内容沙箱。
- 浏览器源 URL 禁止 userinfo；API 和产品日志会隐藏查询与片段值。临时 CEF profile 权限为 `0700`，启动前和正常退出后都会删除。不得把长期仪表盘令牌写入已提交场景或公开诊断。
- M6 凭据只接受绝对路径的用户名/密码文件对。应使用 `compose.m6-auth.yaml` 的 secret 挂载，把源文件放在已忽略的 `secrets/` 目录并限制主机访问；不得把凭据值直接写入 Compose、`.env.example`、命令行、日志或 Issue。
- HTTP Basic 不会加密凭据。任何远程访问都必须由受信反向代理终止 HTTPS，只允许其外部 HTTPS Origin，阻止客户端直连后端端口，并保证公开存活/就绪响应不含配置细节。原生 TLS 和经过评审的互联网部署仍是未完成的 M6 工作。

## Supported versions / 支持版本

Security fixes are currently provided for the latest commit on the default branch. M5 is complete and M6 is in development. The opening M6 slice provides optional file-backed single-operator Basic authentication across UI, REST, WebSocket, WHEP, and metrics; explicit HTTPS Origin/Host authorization; bounded per-client failed-authentication rate limiting; and public detail-free liveness/readiness probes. Authentication is disabled in base loopback Compose, TLS/TURN and role-based authorization are not implemented, and the milestone has not passed its production security gate. Do not expose the backend directly to a LAN or the Internet.

安全修复仅面向默认分支的最新提交；M5 已完成，M6 正在开发。M6 起步切片为 UI、REST、WebSocket、WHEP 与指标提供可选的文件型单操作员 Basic 认证，同时加入明确的 HTTPS Origin/Host 授权、逐客户端有限认证失败限流，以及不暴露配置细节的公开存活/就绪探针。基础回环 Compose 默认不启用认证，TLS/TURN 与角色授权尚未实现，里程碑也尚未通过生产安全门禁。不得把后端直接暴露到局域网或互联网。
