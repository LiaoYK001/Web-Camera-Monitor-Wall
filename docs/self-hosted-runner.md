# Fedora Self-hosted Runner 与 GHCR 发布

本指南用于把 OBS/CEF 完整镜像构建放到维护者控制的 Fedora x86_64 主机。仓库的轻量公开源码审计仍运行在 GitHub-hosted runner；只有受信版本 Tag 或维护者手动触发的 release job 会进入标签为 `webobs-builder` 的 Self-hosted Runner。

## 安全边界

Self-hosted Runner 会执行仓库代码，因此它不是普通生产服务器。建议使用独立 VM 或专用构建机、独立无特权用户和独立 Docker/Podman 存储，不要在该主机保存摄像机凭据、生产 TLS 私钥、生产录像或可访问生产 VLAN 的长期令牌。

- 不为 Fork Pull Request、未知分支或可被外部贡献者修改的工作流开放该 Runner。
- 使用受保护 Tag/Environment，并把修改 `.github/workflows/**` 设为必须由维护者审查。
- Runner 只取得发布 job 所需的短期 `GITHUB_TOKEN`；不配置长期 PAT 为全局环境变量。
- 不给 Runner 交互式登录用户不必要的 `sudo` 权限。当前 cache 轮换需要对 `/var/cache/webobs-buildkit*` 的限定权限；也可预先把目录所有者改为 Runner 用户后移除 `sudo`。
- 每次发布从干净 Git checkout 开始；发布脚本拒绝脏工作树。

## 1. 准备 Fedora 主机

安装 Git、Git LFS、Docker Engine + Buildx（或提供 Docker 兼容 socket 的受控构建环境）、GitHub CLI，并预留至少 8 GB RAM 与 20 GB 磁盘。创建专用用户和持久缓存：

```bash
sudo useradd --create-home --shell /bin/bash webobs-runner
sudo install -d -o webobs-runner -g webobs-runner -m 0750 /var/cache/webobs-buildkit
sudo loginctl enable-linger webobs-runner
```

如果使用 Docker socket，把该用户加入 `docker` 组等价于授予主机 root 级控制能力。必须把这台机器视为专用且受信的构建边界；更严格的部署应使用隔离 VM 和发布后销毁的短期 Runner。

## 2. 注册 Runner

在 GitHub 仓库打开 `Settings → Actions → Runners → New self-hosted runner`，选择 Linux x64，并只执行页面当次生成的下载、校验和注册命令。注册时增加自定义标签：

```text
self-hosted
linux
x64
webobs-builder
```

注册令牌是短期 secret，不写入 shell history、仓库或配置管理日志。按照 GitHub 页面生成的 `svc.sh` 指令把 Runner 安装为 `webobs-runner` 用户的服务，随后确认它在仓库页面显示 `Idle`。

仓库 release job 的选择器是：

```yaml
runs-on: [self-hosted, linux, x64, webobs-builder]
```

## 3. 保护发布入口

工作流仅响应 `v*` Tag 和 `workflow_dispatch`。仍建议同时配置：

1. 版本 Tag 保护规则，例如 `v*` 仅允许维护者创建或删除。
2. `CODEOWNERS`/分支保护，要求 `.github/workflows/**`、`docker/**`、`scripts/release-*` 经维护者审查。
3. 仓库 Actions 权限默认只读；仅 release job 显式取得 `packages: write`、`attestations: write`、`id-token: write` 和发布源码附件所需的 `contents: write`。
4. 禁止 Fork PR 直接使用 Self-hosted Runner；Pull Request 只运行 GitHub-hosted 的轻量审计。

## 4. 缓存与发布

首次发布会完整构建 OBS/CEF。后续构建复用 `/var/cache/webobs-buildkit`；工作流先写入 `-next`，构建成功后才轮换，避免失败构建破坏当前缓存。

创建受保护 Tag 后：

```bash
git tag -s v0.2.0 -m 'v0.2.0'
git push origin v0.2.0
```

工作流会执行递归 checkout、公开仓库审计、测试/镜像构建、SBOM、provenance、GitHub attestation、GHCR push，并上传与 GPL-2.0-or-later 对应的完整递归源码包。标签规范为：

```text
latest            当前正式 Tag 构建
dev               手动开发发布
sha-xxxxxxxxxxxx  精确 Git 提交
vX.Y.Z            正式版本
@sha256:...       生产部署锁定
```

## 5. Actions 故障时本地发布

本地脚本只接受小写 GHCR 路径和 `dev`/`vX.Y.Z` 版本，拒绝脏工作树，并先执行 executable-bit 与公开仓库审计：

```bash
docker login ghcr.io
./scripts/release-image-local.sh \
  ghcr.io/liaoyk001/web-camera-monitor-wall \
  v0.2.0
```

令牌只通过 `docker login --password-stdin` 或操作系统凭据存储提供，不能作为脚本参数、Docker build argument 或 `.env` 值。发布完成后，以 digest 部署并使用 `gh attestation verify` 验证来源；详见 [GHCR 指南](ghcr.md)。

## 6. 运维检查

定期升级 Runner 二进制、Docker/Buildx 与主机补丁，监控缓存磁盘占用，并检查 Runner 服务日志。若怀疑工作流或 Runner 被攻破，立即停止服务、从 GitHub 删除注册、撤销令牌、隔离主机，并把已发布 digest 当作不可信重新构建。
