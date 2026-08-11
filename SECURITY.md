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

- 真实配置应保存在本地 `.env`。除 `.env.example` 外，`.env*`、`secrets/`、常见私钥格式、录像、构建目录和测试产物均不会进入 Git 或 Docker 构建上下文。
- 相比 `--rtsp-url` 命令行参数，优先通过受保护的环境文件提供 `WEBOBS_RTSP_URL`，因为进程列表可能暴露命令行参数。同时应限制主机、Docker daemon、环境文件和录像的访问权限。
- 应用会在输出 OBS 或配置日志前，隐藏 `rtsp://` 和 `rtsps://` URL 中的凭据；自动化测试会检查测试用户名和密码没有出现在日志里。
- 若真实凭据曾被提交或公开发布，应立即轮换。仅从最新提交删除并不安全，因为 Git 历史和缓存仍可能保留该凭据。
- 真实摄像头验收会把录像写入已忽略的 `recordings/`，并把二次脱敏日志写入已忽略的 `tests/artifacts/`。即使自动凭据检查通过，也不要公开上传这些产物。
- 每次公开提交前运行 `tests/run-public-audit.ps1` 或 `tests/run-public-audit.sh`。审计只检查 Git 索引而不会读取本地未跟踪配置；它会拒绝敏感/生成文件及高置信度凭据，只允许已知 RTSP 测试占位符，并验证 OBS submodule 固定提交。
- 随镜像提供的浏览器编辑器只使用同源静态资源、REST 和 WebSocket，不包含分析脚本、外部字体、CDN 或 source map；但浏览器资料、截图及粘贴的新地址仍应按敏感信息处理。

## Supported versions / 支持版本

Security fixes are currently provided for the latest commit on the default branch while the project is in M1 development. The M1 REST/WebSocket control plane has no authentication or TLS: the product Compose publishes it on host loopback only, validates local Host/Origin values, sends no CORS permission, and requires `If-Match` for mutations. Do not expose it on a LAN or the Internet. Authentication, authorization, TLS, and hardened remote deployment remain M6 work.

项目处于 M1 开发阶段，安全修复仅面向默认分支的最新提交。M1 REST/WebSocket 控制面尚无认证和 TLS；产品 Compose 仅发布到主机回环地址，并校验本地 Host/Origin、不授予 CORS、要求变更携带 `If-Match`。不得暴露到局域网或互联网；认证、授权、TLS 和远程部署加固仍属于 M6。
