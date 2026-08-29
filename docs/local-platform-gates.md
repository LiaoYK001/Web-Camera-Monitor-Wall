# Local Windows and WSL2 release gates / 本机 Windows 与 WSL2 发布门禁

v2.0 no longer dispatches repository code to the two GitHub self-hosted runners. Keep those runners offline. GitHub-hosted Actions perform only public, secret-free audit/typecheck/build work. Platform, private-media and OCI publication steps run interactively on the maintainer's current Windows host and its WSL2 Linux distribution.

v2.0 不再向两台 GitHub self-hosted Runner 调度仓库代码，可保持它们离线。GitHub-hosted Actions 只执行公开、无 Secret 的审计、类型检查和构建；平台、私有媒体及 OCI 发布步骤在维护者当前 Windows 主机和其 WSL2 Linux 发行版中交互执行。

## Trust boundary / 信任边界

- `gate/`, certificates, endpoints, credentials, recordings, browser profiles and raw results remain Git-ignored and must not be uploaded as Actions artifacts / `gate/`、证书、端点、凭据、录像、浏览器 Profile 和原始结果保持 Git 忽略，不得上传为 Actions Artifact。
- Copy `gate/` outside the checkout before using it. `scripts/run-private-pwa-gate.py` rejects an in-workspace command / 使用前把 `gate/` 复制到检出目录之外；`scripts/run-private-pwa-gate.py` 会拒绝工作树内命令。
- A passing private gate writes only a redacted receipt containing platform, Git revision, completion time and measured check names / 私有门禁通过后只写入含平台、Git revision、完成时间及测量项名称的脱敏收据。
- Receipts expire after 48 hours and must both match the exact release commit / 收据 48 小时失效，且两份都必须精确绑定发布提交。

## Windows host / Windows 宿主机

```powershell
# Baseline (no private fixtures)
.\scripts\test-web-runtime-windows.ps1

# Full release gate after C:\webobs-gates is configured per gate/DEPLOY.md
.\scripts\test-web-runtime-windows.ps1 -ReleaseGate `
  -PrivateGateCommand C:\webobs-gates\run-gate.cmd
```

The full command creates `build/private-gates/windows.json` only after all required Chrome/Edge protocol, offline/update and resource-release checks pass. Long-duration load tests are optional qualification evidence and are not part of the v2.2 publication contract.

完整命令只会在所有 Chrome/Edge 协议、离线/升级与资源释放必测项通过后生成 `build/private-gates/windows.json`。长时间负载测试属于可选资格证据，不进入 v2.2 发布契约。

## WSL2 Linux / WSL2 Linux

Install a normal WSL2 distribution on the D drive (the maintainer gate uses Fedora Linux 44) with Node 22.23 or newer, pnpm 11, Python 3 and Chromium. Docker Desktop integration is not required for this gate: the Windows host owns Linux-container builds, while Fedora owns Linux shell and Chromium behavior. The Docker Desktop internal `docker-desktop` distribution is infrastructure and does not count as the Linux test environment.

把正常的 WSL2 发行版安装到 D 盘（维护者门禁使用 Fedora Linux 44），并安装 Node 22.23 或更新版本、pnpm 11、Python 3 与 Chromium。该门禁不要求 Docker Desktop WSL integration：Windows 宿主负责 Linux 容器构建，Fedora 负责 Linux shell 与 Chromium 行为。Docker Desktop 内部的 `docker-desktop` 发行版只是基础设施，不能作为 Linux 测试环境。

```bash
# Baseline
./scripts/test-web-runtime-wsl2.sh

# Full release gate after /opt/webobs-gates is configured per gate/DEPLOY.md
./scripts/test-web-runtime-wsl2.sh --release-gate \
  --private-gate-command /opt/webobs-gates/run-gate.sh
```

The full command creates `build/private-gates/linux-wsl2-chromium.json` only after every required Linux media check passes.

完整命令只会在所有 Linux 媒体必测项通过后生成 `build/private-gates/linux-wsl2-chromium.json`。

## Local OCI publication / 本地 OCI 发布

After both receipts exist for the clean current revision and are less than 48 hours old:

当两份收据均对应当前干净提交且生成时间不超过 48 小时后：

```powershell
python scripts\verify-local-gate-receipts.py
.\scripts\release-image-local.ps1 `
  -Image ghcr.io/owner/web-camera-monitor-wall -Version v2.0
```

Both release scripts check the clean tree, public audit and both receipts before Buildx can push. They do not read or publish the private fixture output. `release-image-local.sh` remains available on Linux hosts that provide a native Docker/Buildx engine.

两个发布脚本都会在 Buildx 推送前检查干净工作树、公开审计和两份收据；它们不会读取或发布私有夹具原始输出。具备原生 Docker/Buildx 的 Linux 主机仍可使用 `release-image-local.sh`。
