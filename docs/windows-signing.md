# Windows 安装包代码签名

Windows `.exe`/NSIS 安装包使用 Authenticode 代码签名，发布者名称来自经过验证的证书身份。局域网 HTTPS 使用独立的 TLS 证书，两项分别管理。

## 是否需要向微软申请

有两种公开受信任签名路线：

1. 向受信任证书机构（CA）申请代码签名证书，完成个人或组织身份审核，再使用其支持的硬件令牌、HSM 或云签名服务签署主程序和安装器。申请前向供应商确认是否支持你的地区、个人/组织身份以及 GitHub Actions 或自托管构建机。
2. 使用微软 **Azure Artifact Signing**（原 Azure Trusted Signing）：建立 Azure 账户、身份验证及 Public Trust 证书配置，再让构建机调用云签名。

微软 Public Trust 目前只接受美国、加拿大的个人开发者；组织有另外的支持地区名单，当前名单没有中国大陆。使用中国大陆身份时，应先评估支持该身份的 CA。Private Trust 或自签证书用于受控测试，不能代替未来显式签名发行所验证的公开受信任发布者。当前未签名正式发行不需要申请证书。

官方依据：[微软签名说明](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)、[Artifact Signing 地区与身份要求](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)。

代码签名验证发布者和文件完整性。SmartScreen 还会积累文件的下载信誉，因此签名后也可能出现提示；不要为了保证“立即无提示”而承诺购买某种证书。[微软 FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq#what-can-i-expect-when-i-see-smartscreen-prompts-for-signed-files)

## 当前项目已接入的凭据

`desktop/builder.config.cjs` 与本机构建脚本的可选签名入口是 `CSC_LINK`、`CSC_KEY_PASSWORD` 和 `WEBOBS_SIGNING_PUBLISHER`，仅显式 `-Release -Sign` 使用。供应商提供可用于此入口的 PFX 时，证书必须包含可用私钥，且发布者必须与证书的实际身份一致。当前 GitHub 候选工作流默认生成未签名包，不读取以下签名凭据。

未来接入 CI 签名时，可在 GitHub 仓库的 `windows-desktop-build` Environment 配置下表，并修改工作流把这些值映射到上述构建变量、显式传入 `-Sign`。只配置 Secret 不会让当前工作流自动签名：

| 名称 | 类型 | 内容 |
| --- | --- | --- |
| `WEBOBS_WINDOWS_CSC_LINK` | Secret | electron-builder 可使用的私密证书引用或 PFX Base64 |
| `WEBOBS_WINDOWS_CSC_KEY_PASSWORD` | Secret | 证书密码 |
| `WEBOBS_WINDOWS_SIGNING_PUBLISHER` | Variable | 证书中的真实发布者名称 |

证书供应商若要求非导出硬件私钥、HSM 或云签名，需按其方式接入签名适配器及构建身份；当前 PFX 入口不代表这些适配器已经配置。不要把非导出私钥转成文件来绕过供应商要求。Azure 路线需要另外接入 `azureSignOptions`/SignTool 和受限云身份，不能把云证书当作 PFX Secret。

私钥、PFX、密码和访问 Token 只放在私密凭据存储中，不发送到聊天、不提交 Git、不附加到 Release。GitHub Token 用于发布附件，与代码签名证书分别配置。

未来可选的本地签名候选构建：

```powershell
# 在私密环境中事先设置上述三个构建变量。
./desktop/scripts/build-windows.ps1 -Version 3.5.0 -Release -Sign
Get-AuthenticodeSignature -LiteralPath 'desktop/out/3.5.0/WebOBS-3.5.0-windows-x64.exe'
```

显式 `-Sign` 构建检查 `Status=Valid`、发布者名称、SHA 摘要及签名时间戳，并验证主程序与安装器；保留捆绑依赖原有签名和运行文件摘要。签名包发生任何变化后都需重新签名和生成更新摘要，不覆盖已经发布的不可变版本。默认 `-Release` 不要求签名。

当前维护者选择暂不签名：正式稳定 NSIS 包标记 `UNSIGNED`，发布 `latest.yml`，启用完整自动更新，以 GitHub HTTPS 与完整安装包 SHA-512/大小校验为验证方式。用户确认、正常停服与一致性备份继续保留。`-dev.*` 开发测试包仍保留 `DEVELOPMENT-UNSIGNED` 标记并关闭正式更新源。本文的证书步骤是未来可选方案，签名构建需显式追加 `-Sign`；Windows 媒体与更新验证边界见 [桌面发布流程](windows-desktop.md)。
