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

For the active `v3-M1 / v3.0` and `v3-M2 / v3.1` development lines, run the corresponding private analytics gates from the local Windows host and WSL2 distribution. The gates create revision-bound receipts only after browser protocol, zero-server-media, model integrity and Worker resource checks have actually completed. No self-hosted runner is used by these local commands.

当前 `v3-M1 / v3.0` 与 `v3-M2 / v3.1` 开发线需要在本机 Windows 与 WSL2 分别执行分析门禁。只有协议、零服务端媒体、模型完整性和 Worker 资源释放等检查真实完成后，才会生成绑定当前 revision 的收据；该流程不使用 self-hosted Runner。

The repository does not fabricate v3 receipts. Use the private gate harness kept
outside the checkout together with the public adapter below. The private command
must perform the actual browser/media checks and write only this bounded result
to `WEBOBS_PRIVATE_GATE_RESULT`:

```json
{"contract":"webobs-v3-m1-gate-v1","milestone":"v3-M1","platform":"windows","checks":{"windowsMotionScene":true}}
```

The adapter validates the exact check set, binds a redacted receipt to the current
revision, and discards the raw private result/log:

```powershell
$env:WEBOBS_PRIVATE_V3_GATE_COMMAND = 'D:\webobs-private-gates\run-v3-gate.cmd'
.\scripts\test-web-runtime-windows.ps1 -V3Milestone v3-M1 -PrivateV3GateCommand $env:WEBOBS_PRIVATE_V3_GATE_COMMAND
.\scripts\test-web-runtime-windows.ps1 -V3Milestone v3-M2 -PrivateV3GateCommand $env:WEBOBS_PRIVATE_V3_GATE_COMMAND
```

```bash
export WEBOBS_PRIVATE_V3_GATE_COMMAND=/opt/webobs-gates/run-v3-gate.sh
./scripts/test-web-runtime-wsl2.sh --v3-milestone v3-M1 --private-v3-gate-command "$WEBOBS_PRIVATE_V3_GATE_COMMAND"
./scripts/test-web-runtime-wsl2.sh --v3-milestone v3-M2 --private-v3-gate-command "$WEBOBS_PRIVATE_V3_GATE_COMMAND"
```

The M2 model and historical-regression checks may run on either trusted local
host, using `--platform model` and `--platform regression`. The adapter emits
`build/private-gates/v3-m1-*.json` or `v3-m2-*.json`; the release verifiers then
require every exact receipt for the target version. Missing, stale, partial or
differently revisioned receipts fail closed. Keep the private command, browser
profiles, credentials, endpoints, recordings and raw results outside the
checkout.

仓库不会伪造 v3 收据。请把真实浏览器/媒体夹具放在检出目录之外，并通过上面的公开适配器运行。私有命令必须执行实际检查，只向 `WEBOBS_PRIVATE_GATE_RESULT` 写入有界结果；适配器会校验精确检查集合、绑定当前 Git revision，并丢弃原始日志与结果。`model` 和 `regression` 收据可在任一可信本机执行。凭据、端点、浏览器 Profile、录像及原始证据始终留在仓库之外。

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

Stable v3.1 publication requires both platform receipts for the clean current revision and they must be less than 48 hours old:

正式 v3.1 发布要求两份收据均对应当前干净提交且生成时间不超过 48 小时：

```powershell
python scripts\verify-local-gate-receipts.py
.\scripts\release-image-local.ps1 `
  -Image ghcr.io/owner/web-camera-monitor-wall -Version v3.1
```

For the v3.0 user-test preview, receipts are intentionally not required, but the
preview flag is mandatory and the command must run from a `dev` HEAD that exactly
matches `origin/dev`:

```powershell
.\scripts\release-image-local.ps1 `
  -Image ghcr.io/owner/web-camera-monitor-wall -Version v3.0 -Prerelease
```

The preview creates a GitHub `pre-release`, promotes only `v3.0` and `sha-*`, and
never changes `latest`. Both release scripts still check the clean tree and public
audit; they do not read or publish private fixture output. `release-image-local.sh`
remains available on Linux hosts that provide a native Docker/Buildx engine.

正式版发布脚本会在 Buildx 推送前检查干净工作树、公开审计和两份收据；预览
脚本只跳过私有收据并保留同样的公开审计边界。脚本不会读取或发布私有夹具原始
输出。具备原生 Docker/Buildx 的 Linux 主机仍可使用 `release-image-local.sh`。
