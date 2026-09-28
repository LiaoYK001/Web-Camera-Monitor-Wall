# 可选：本机私有门禁 / Optional: local private gates

> **这些门禁默认不参与发布。** 发布流程见 [发布流程](release-flow.md)——从 v3.3 起，稳定的发布路径只运行自动、无 Secret 的检查，平台与容器验证由发布者人工完成。
> **These gates are NOT part of the release path.** See [release flow](release-flow.md): since v3.3 the stable publication path runs automatic, secret-free checks only, and platform/container verification is a manual step owned by the releaser.

本文件保留原有的**可选**私有夹具用法，供需要更严格本地证据时使用（例如发布前的额外自查、或分析与媒体链路的回归）。它们不再被 `scripts/release-image-local.sh` 调用，也不再有任何 48 小时时效或「缺一不可」的要求。

## Trust boundary / 信任边界

- `gate/`、证书、端点、凭据、录像、浏览器 Profile 和原始结果保持 Git 忽略，**不得**上传为 Actions Artifact。
- 使用前把 `gate/` 复制到**检出目录之外**；`scripts/run-private-pwa-gate.py` 会拒绝工作树内的命令。
- 私有门禁只写一份**脱敏收据**（平台、Git revision、完成时间、测量项名称），原始日志与结果始终丢弃。

## Windows / WSL2 用法（可选）

```powershell
# 无私有夹具的基线
.\scripts\test-web-runtime-windows.ps1

# 配置了 C:\webobs-gates 之后跑完整私有门禁
.\scripts\test-web-runtime-windows.ps1 -ReleaseGate `
  -PrivateGateCommand C:\webobs-gates\run-gate.cmd
```

```bash
./scripts/test-web-runtime-wsl2.sh

./scripts/test-web-runtime-wsl2.sh --release-gate \
  --private-gate-command /opt/webobs-gates/run-gate.sh
```

v3-M1 / v3-M2 的分析门禁同样可选：

```powershell
$env:WEBOBS_PRIVATE_V3_GATE_COMMAND = 'D:\webobs-private-gates\run-v3-gate.cmd'
.\scripts\test-web-runtime-windows.ps1 -V3Milestone v3-M2 -PrivateV3GateCommand $env:WEBOBS_PRIVATE_V3_GATE_COMMAND
```

```bash
export WEBOBS_PRIVATE_V3_GATE_COMMAND=/opt/webobs-gates/run-v3-gate.sh
./scripts/test-web-runtime-wsl2.sh --v3-milestone v3-M2 --private-v3-gate-command "$WEBOBS_PRIVATE_V3_GATE_COMMAND"
```

收据写入 `build/private-gates/`（Git 忽略）。若你选择运行它们，可用下列脚本自行核对：

```bash
python scripts/verify-local-gate-receipts.py        # windows + linux-wsl2-chromium
python scripts/verify-v3-m1-gate-receipts.py        # v3-M1 四份
python scripts/verify-v3-m2-gate-receipts.py        # v3-M2 四份
python scripts/verify-m7-gate-receipts.py           # v2.3 / m7
```

这些脚本保留是为了让可选的私有证据仍可**自检**；它们不参与发布，也不会阻塞任何人。

## CI 分工 / CI split

GitHub-hosted Actions 只做公开、无 Secret 的审计、类型检查与构建；OCI 发布在维护者本机执行（见 [发布流程](release-flow.md)）。self-hosted runner 保持离线。
