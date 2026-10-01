# 完整 Windows 桌面客户端（阶段一）

`desktop/` 是 Electron 安装版，和 `clients/` 中的 Qt 客户端分别构建。Docker/Podman 仍使用现有镜像。Windows 安装版包含原生 C++ 后端、libobs/D3D11 与来源插件、Python 3.12、go2rtc、MediaMTX、FFmpeg、OpenSSL、Caddy 和 WebUI；日常运行无需 Docker、WSL、系统 Python 或系统 PATH。

## 默认行为

- 自动检查正式更新，启动时一次，此后每 6 小时检查；默认自动下载。
- 下载完成后用户选择“重启更新”才安装，退出应用不自动安装。
- 主窗口关闭进入托盘；投影与服务保留。“退出并停止服务”正常停服并收束 Windows Job Object 中的后代。
- 开机启动和局域网共享默认关闭。
- 桌面页面禁用 Service Worker/PWA 更新缓存；浏览器仍保留现有 PWA 流程。
- 声音、场景和弱网设置继续使用同一本机后端中的账号偏好。桌面窗口共用持久会话；局域网浏览器独立登录后使用同账号偏好。

## 构建完整安装包

开发构建机需要 VS 2022 的 MSVC x64、Windows SDK、CMake >= 3.28、Python、Node 24 和 pnpm 11.16.0。使用 PowerShell 7.2+ 的 VS x64 Developer PowerShell：

```powershell
./desktop/scripts/build-windows.ps1 -Version 3.4.0-dev.0
```

缓存与构建在仓库所在磁盘的 `desktop/.cache` 与 `build/desktop-windows`。固定依赖来自 `desktop/dependencies.lock.json`；vcpkg 固定提交和 baseline。上游 OBS 构建在副本中，原 submodule 不变。构建、C++/桌面测试、完整运行目录校验通过后，NSIS 完整安装包位于 `desktop/out`。

缺少签名凭据只能生成带 `DEVELOPMENT-UNSIGNED` 的开发测试包，不能连接正式更新源。正式候选：

```powershell
$env:CSC_LINK = '签名证书路径或维护者配置的凭据'
$env:CSC_KEY_PASSWORD = '通过私密环境设置，不写入仓库'
$env:WEBOBS_SIGNING_PUBLISHER = '证书中的正式发布者名称'
./desktop/scripts/build-windows.ps1 -Version 3.4.0 -Release
```

GitHub `Build full Windows desktop` 是手动候选构建，不发布 Release。也可在现有 `Web runtime public CI` 手动选择 `windows_desktop`，从 dev 分支执行无签名候选。编译机测试不等于 Windows 10/11 实际安装及摄像机验收。

## 服务、端口与数据

桌面主进程按 MediaMTX、go2rtc、账号与设备/事件/NVR 服务、备份服务、C++ 控制端的顺序启动，逐项健康检查。配置了归档才启动 S3 服务。分析与集群节点工具随包提供，仍受现有配置和授权控制。

主控制入口固定 `http://127.0.0.1:18080`，内部端口首次分配后保存在 `ports.json`；冲突报错，不结束其他应用。受认证的 `/api/v1/runtime/info` 返回平台与 go2rtc 建档地址，设备导入使用该地址。服务 URL 的环境映射在根目录 `runtime_support.py` 与 C++ `platform_runtime` 中保持一致。

配置、账号数据库、密钥、桌面设置与浏览器会话位于 `%LOCALAPPDATA%\WebOBS`。私密目录仅当前 Windows 用户访问，备份主密钥由 Electron safeStorage/Windows DPAPI 保护；客户端授权签名密钥也使用 DPAPI。运行期间备份进程使用私密 `run` 目录中的临时密钥，停服删除。录像默认位于用户 Videos 下的 WebOBS，可在设置中选择新目录；已有录像不会自动移动。

OBS 使用 D3D11，外部 FFmpeg 与 OBS 插件能力分别实测。CUDA 设备与驱动通过 Windows CUDA API 检测，NVENC/QSV 编解码以限时样本探测为准；没有通过探测的硬件不会报告为就绪。部分 Linux 专用指标在 Windows 显示不可读取。

## 投影、局域网与备份恢复

Scene 右键菜单可打开不同固定 Scene 的独立投影，选择显示器与全屏，Esc 退出全屏。关闭主窗口不会关闭投影。同 Scene、模式和显示器组合复用其窗口。

系统设置中的 Windows 客户端区提供更新开关、托盘、开机启动、录像目录、局域网设置与服务重启。共享开启后，Caddy 只监听私有 IPv4 地址，生成内部 CA。UI 列出 HTTPS 地址、根证书路径与当前用户信任步骤，并列出管理员可自行执行的 Private 防火墙命令。上游管理端口保持 loopback，所有管理请求经过产品认证代理。共享和录像目录设置在重启服务后生效。

“创建完整配置备份”暂时正常停服，创建一致性快照和加密 `.wobk` 备份，然后恢复运行。录像媒体不复制进配置备份。Docker/WSL 数据通过“从备份恢复”明确选择 `.wobk` 及原始 32 字节密钥导入，先保存当前数据快照，不自动搬移部署。含绝对路径的外部来源、存储卷和 Secret 引用需在恢复后改为本机路径；它们不会被猜测或静默重写。

更新安装检查草稿、前端导出和后端证据导出；存在未保存/未完成工作时暂停。录像/媒体仍运行时用户明确选择停止任务并更新。更新前正常停服、创建配置和 NVR 目录数据库快照，记录版本与快照映射。启动失败显示诊断和恢复入口：先安装对应旧版本，再恢复匹配快照。首次手动安装没有缓存旧包时，从相应 Release 下载已签名包；之后更新保留已安装版本的安装包。损坏快照不会激活。

## 正式发布与验收

产品标签 `vX.Y` 对应客户端 `X.Y.0`，`vX.Y.Z` 对应 `X.Y.Z`。容器与 Windows 共用已审计的产品 Release。候选附件包含安装包、blockmap、`latest.yml`（仅正式包）、SHA-256 摘要、运行文件清单、CycloneDX SBOM 与许可证归档。Electron updater 校验 SHA-512 与 Authenticode 发布者，准备安装时再次校验；客户端不包含 GitHub Token。

Windows 10、11 各自记录实际安装、媒体、LAN 与两版更新结果。`desktop/qualification.example.json` 只是格式示例，不能作为通过证明；完整检查名见 `desktop/scripts/qualification.mjs`。维护者还需收集匹配第三方二进制的完整对应源码（包括 FFmpeg 及其启用的 GPL 组件），提供已审核 `SOURCE-MANIFEST.json`，其字段为 `revision`、`version`、`reviewed: true`、`files: [{name, sha256}]`。

```powershell
./desktop/scripts/publish-release.ps1 -Tag v3.4 `
  -ArtifactDirectory 'D:/release/webobs-windows' `
  -QualificationReceipts 'D:/private/windows-qualification.json' `
  -CorrespondingThirdPartySourceDirectory 'D:/release/matching-third-party-sources'
```

发布器验证实际安装包摘要、签名、版本与源码身份，复用 `scripts/create-source-bundle.sh` 和 `scripts/upload-release-assets-immutable.sh`；缺少证据、签名或对应源码时拒绝正式上传。维护者发布机需要 Git Bash/gh；Token 仅用于附件上传。不要把开发包的元数据上传到正式更新源。

## 当前验证边界

源码包含 Windows 原生移植、Electron 生命周期、完整依赖打包与更新/恢复实现。可在本机运行桌面逻辑测试、快照/转码参数测试、Web 构建及 Linux 回归；实际 Windows 编译、NSIS 安装、真实摄像机播放、Windows 10/11 和两个签名安装版本的更新故障测试必须分别记录。没有完成这些实际检查前，不宣称阶段一达到生产验收。
