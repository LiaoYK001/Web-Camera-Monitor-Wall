# v3.5 release notes / v3.5 发布说明

v3.5 启用未签名 Windows x64 正式安装包的完整 GitHub Release 自动更新。维护者暂不采用代码签名；稳定包使用 `3.5.0` 和 `UNSIGNED` 文件名，附带 `latest.yml`、blockmap、摘要、依赖清单、运行清单、SBOM、许可证与对应源码。

- 默认启动后检查更新，此后每 6 小时检查，自动下载；设置中可关闭自动检查或下载，支持手动检查与下载。
- 下载后显示版本、发布说明与“重启更新”；用户明确确认才安装，退出应用不会自动安装。
- 保留安装包大小/SHA-512 校验、磁盘空间检查、未保存草稿/导出拦截、录像与推流停止确认、正常停服、一致性快照与恢复路径。
- 只有显式可选签名构建需要发布者签名；未签名正式包不会被签名门禁阻止。开发 `-dev.*` 包仍不进入正式更新源。
- 已安装 v3.4 `3.4.0-dev.0 DEVELOPMENT-UNSIGNED` 的用户需手动安装 v3.5 一次，此后可通过内置更新获得后续正式版本。v3.4 标签与附件保持不变。

本轮主要更改桌面更新与发布策略，沿用 v3.4 的 go2rtc、Scenes、多投影、账号声音和可关闭的自动播放优化。Windows 10/11 干净系统、真实摄像机和 LAN 跨设备验收仍需分别记录，不能由本机测试代替。实际完成的构建、安装与更新检查在发布时记录。

The Windows x64 stable NSIS distribution is unsigned by maintainer choice and supports the complete GitHub updater. Package size/SHA-512 checks, explicit installation, workload guards, graceful shutdown, snapshots and recovery remain enabled. Signing is optional. Existing v3.4 development installations require one manual upgrade; subsequent stable versions use in-app updates. Clean-system and real-camera qualification remain separate.
