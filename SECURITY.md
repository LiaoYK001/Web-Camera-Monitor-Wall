# Security Policy

## Reporting a vulnerability / 漏洞报告

Please avoid opening a public issue for a suspected vulnerability. Use the repository's private vulnerability reporting option under **Security → Advisories → Report a vulnerability** when available. If that option is unavailable, contact the maintainer privately through the contact method listed on the maintainer's GitHub profile. Include reproduction steps and affected versions, but never include live camera credentials, private RTSP URLs, recordings, or unredacted logs.

请勿为疑似安全漏洞直接创建公开 Issue。仓库支持时，请使用 **Security → Advisories → Report a vulnerability** 私密报告；若该入口不可用，请通过维护者 GitHub 个人资料中列出的联系方式私下联系。报告可包含复现步骤和受影响版本，但不得包含真实摄像头凭据、私有 RTSP 地址、录像或未脱敏日志。

## Credential handling / 凭据处理

- Keep real configuration in a local `.env` file. Files matching `.env*`, `secrets/`, `backups/`, common private-key formats, recordings, build directories, and test artifacts are excluded from Git and the Docker build context; `.env.example` is the only exception.
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
- Authentication rejection, scene mutation, source outage, restart request, and recovery events are emitted as one-line JSON after URL redaction. Authentication audit fields identify only the backend TCP peer (normally the trusted reverse proxy), never the username or Authorization value. Treat retained logs as sensitive operational data even though credentials and source URLs are omitted.
- Base Compose bounds Docker `json-file` logs to three 10 MiB files. Keep `WEBOBS_LOG_MAX_SIZE` and `WEBOBS_LOG_MAX_FILES` finite, include rotated files in host backup/access policy, and do not rely on application redaction as permission to publish logs.
- Never pass runtime credentials as image build arguments or publish them in registry metadata. Prefer immutable GHCR digests, verify provenance when available, and keep the exact corresponding GPL source commit and recursive submodule state available for every distributed image.

- 真实配置应保存在本地 `.env`。除 `.env.example` 外，`.env*`、`secrets/`、`backups/`、常见私钥格式、录像、构建目录和测试产物均不会进入 Git 或 Docker 构建上下文。
- 相比 `--rtsp-url` 命令行参数，优先通过受保护的环境文件提供 `WEBOBS_RTSP_URL`，因为进程列表可能暴露命令行参数。同时应限制主机、Docker daemon、环境文件和录像的访问权限。
- 应用会在输出 OBS 或配置日志前，隐藏 `rtsp://` 和 `rtsps://` URL 中的凭据；自动化测试会检查测试用户名和密码没有出现在日志里。
- 若真实凭据曾被提交或公开发布，应立即轮换。仅从最新提交删除并不安全，因为 Git 历史和缓存仍可能保留该凭据。
- 真实摄像头验收会把录像写入已忽略的 `recordings/`，并把二次脱敏日志写入已忽略的 `tests/artifacts/`。即使自动凭据检查通过，也不要公开上传这些产物。
- 每次公开提交前运行 `tests/run-public-audit.ps1` 或 `tests/run-public-audit.sh`。审计只检查 Git 索引而不会读取本地未跟踪配置；它会拒绝敏感/生成文件及高置信度凭据，只允许已知 RTSP 测试占位符，并验证 OBS submodule 固定提交。
- 随镜像提供的浏览器编辑器只使用同源静态资源、REST 和 WebSocket，不包含分析脚本、外部字体、CDN 或 source map；但浏览器资料、截图及粘贴的新地址仍应按敏感信息处理。
- 服务端浏览器源默认拒绝。只通过 `WEBOBS_BROWSER_ALLOWED_ORIGINS` 批准精确且可信的 Origin；私网或本地目标还需单独设置 `WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS=true`。获准网页仍可加载子资源，因此允许列表是管理员信任边界，不是完整内容沙箱。
- 浏览器源 URL 禁止 userinfo；API 和产品日志会隐藏查询与片段值。临时 CEF profile 权限为 `0700`，启动前和正常退出后都会删除。不得把长期仪表盘令牌写入已提交场景或公开诊断。
- M6 凭据只接受绝对路径的用户名/密码文件对。应使用 `compose.m6-auth.yaml` 的 secret 挂载，把源文件放在已忽略的 `secrets/` 目录并限制主机访问；不得把凭据值直接写入 Compose、`.env.example`、命令行、日志或 Issue。
- HTTP Basic 不会加密凭据。任何远程访问都必须使用 M6 production 覆盖在同一产品容器内由 Caddy 终止受信 HTTPS，只允许其外部 HTTPS Origin，阻止客户端直连后端端口，并保证公开存活/就绪响应不含配置细节。
- 认证拒绝、场景变更、来源断流、重启请求和恢复会在 URL 脱敏后写为单行 JSON。认证审计字段只标识后端 TCP 对端（通常是受信反向代理），绝不记录用户名或 Authorization 值。即使省略了凭据与来源 URL，保留日志仍应视为敏感运维数据。
- 基础 Compose 默认把 Docker `json-file` 日志限制为三份、每份 10 MiB。`WEBOBS_LOG_MAX_SIZE` 与 `WEBOBS_LOG_MAX_FILES` 必须保持有限，并应把轮转文件纳入主机备份和访问策略；应用脱敏不代表日志可以公开发布。
- 不得把运行时凭据作为镜像构建参数或发布到 registry 元数据。应优先部署不可变 GHCR digest，在可用时验证 provenance，并为每个已分发镜像保留精确对应的 GPL 源码提交与递归 submodule 状态。

## Supported versions / 支持版本

Security fixes are currently provided for the latest commit on the default branch. M0–M8 implementation is complete and M9 is in development. M6 provides file-backed authentication, trusted HTTPS/TURN deployment, strict Origin/Host authorization, bounded failed-authentication rate limiting, source recovery, structured audit, bounded logs, and detail-free probes. M8 routes its loopback-only NVR process through the same control boundary and redacts all source endpoints. Authentication remains disabled in base loopback Compose. Do not expose that base backend directly to a LAN or the Internet; use the documented production overlay and least-privilege network policy.

安全修复仅面向默认分支的最新提交；M0–M8 实现已完成，M9 正在开发。M6 已提供文件型认证、受信 HTTPS/TURN 部署、严格 Origin/Host 授权、有限认证失败限流、来源恢复、结构化审计、有界日志及无细节探针。M8 的仅回环 NVR 进程通过同一控制边界提供，全部来源端点均脱敏。基础回环 Compose 仍默认不启用认证；不得将其后端直接暴露到局域网或互联网，应使用已记录的 production 覆盖和最小权限网络策略。
