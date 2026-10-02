# v3.5 release notes / v3.5 发布说明

v3.5 启用未签名 Windows x64 正式安装包的完整 GitHub Release 自动更新。维护者暂不采用代码签名；稳定包使用 `3.5.0` 和 `UNSIGNED` 文件名，附带 `latest.yml`、blockmap、摘要、依赖清单、运行清单、SBOM、许可证与对应源码。

- 默认启动后检查更新，此后每 6 小时检查，自动下载；设置中可关闭自动检查或下载，支持手动检查与下载。
- 下载后显示版本、发布说明与“重启更新”；用户明确确认才安装，退出应用不会自动安装。
- 保留安装包大小/SHA-512 校验、磁盘空间检查、未保存草稿/导出拦截、录像与推流停止确认、正常停服、一致性快照与恢复路径。
- 只有显式可选签名构建需要发布者签名；未签名正式包不会被签名门禁阻止。开发 `-dev.*` 包仍不进入正式更新源。
- 修复跨盘升级：安装器在已有安装所在盘创建仅所有者与 SYSTEM 可访问的临时目录，避免 D 盘安装与 C 盘 TEMP 之间的原子移动失败；不改变系统环境变量或用户数据目录。
- go2rtc 保留完整 Monaco 压缩资源与 Workers，移除页面不用的开发源码树，缩短安装路径并减小安装包。
- 已安装 v3.4 `3.4.0-dev.0 DEVELOPMENT-UNSIGNED` 的用户需手动安装 v3.5 一次，此后可通过内置更新获得后续正式版本。v3.4 标签与附件保持不变。

本轮主要更改桌面更新与发布策略，沿用 v3.4 的 go2rtc、Scenes、多投影、账号声音和可关闭的自动播放优化。Windows 10/11 干净系统、真实摄像机和 LAN 跨设备验收仍需分别记录，不能由本机测试代替。实际完成的构建、安装与更新检查在发布时记录。

The Windows x64 stable NSIS distribution is unsigned by maintainer choice and supports the complete GitHub updater. Package size/SHA-512 checks, explicit installation, workload guards, graceful shutdown, snapshots and recovery remain enabled. Signing is optional. Existing v3.4 development installations require one manual upgrade; subsequent stable versions use in-app updates. Clean-system and real-camera qualification remain separate.

## 实际发布与验证（2026-10-02）

- [v3.5 Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v3.5) 已发布，14 个附件的远端摘要与本机产物一致；源码提交固定为 `e7b6a2ad5f87b37ea933b8fd9e5d7a885e12cb03`。
- [Windows x64 EXE](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/download/v3.5/WebOBS-3.5.0-windows-x64-UNSIGNED.exe)：409856882 字节，SHA-256 `1b275c8ff40d3dd2b49c558eedf9bd88ac5cecd6f9f4fe2542bc5ccdb28d2101`；公开 `latest.yml` 与完整 EXE 的 SHA-512/大小一致。
- GHCR `ghcr.io/liaoyk001/web-camera-monitor-wall:v3.5` 与 `latest` 均已匿名核验，digest 为 `sha256:7d55187025db3850d9c9aa839bcdc05d9cd4a217683cbca2f66ed4e2052236c4`，含 linux/amd64 镜像及 provenance/SBOM。
- 24 项桌面测试、真实 Electron IPC/协议检查通过；最终 ASAR 使用干净 PATH 验证账号、认证 go2rtc 与 owner-crash Job 收束。Windows 11 实际 NSIS 首次安装、中文路径、默认卸载保留数据通过。
- 两版真实 NSIS 安装包 `3.4.99 → 3.5.0` 使用私密本机更新源验证检测/下载、显式安装、正常停服与快照、升级后健康检查、账号/偏好/数据保留；`3.4.99` 仅为本机测试包，未公开发布。
- 真实 GitHub provider 在无 GitHub Token 的情况下从公开 v3.5 检测并下载完整 409 MB 安装包，SHA-512/SHA-256 均通过；此次公开下载检查没有执行安装。后续公开 GitHub 两版安装、干净 Windows 10/11、真实摄像机与 LAN 跨设备仍需分别验收。
- 最终 Linux 单镜像通过 C++/服务测试，以及认证/RBAC/Origin、完整 go2rtc 页面和本地 Monaco、真实浏览器 MSE 视频帧、HTTP/WebSocket/RTSP 测试流、重启配置保留与正常关停检查。
