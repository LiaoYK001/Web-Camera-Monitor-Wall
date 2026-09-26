# Windows + WSL2 开发说明

统一开发流程已迁移到 [Windows / Linux 跨平台开发指南](development.md)。

- Windows 首次：`./scripts/dev.ps1 -Setup`；日常：`./scripts/dev.ps1`。
- Linux 首次：`bash scripts/dev.sh --setup`；日常：`bash scripts/dev.sh`。
- 默认使用原生后端和 Vite，不要求 Docker 引擎或镜像。
- 旧的 `dev.ps1 -Build` 改为显式 `dev.ps1 -Mode container -Build`。
- 首次访问在登录页创建管理员账号。原生数据库位于 WSL 用户的 `~/.cache/webobs-dev/<仓库路径摘要>/data`，不会自动迁移原容器数据卷中的账号和设备。
- 从 `scripts` 目录运行 `./dev.ps1` 同样有效。

详细依赖、运行模式、停止操作、日志、端口与账号排错、完整镜像构建及 Docker/Podman 跨机器测试步骤均见新指南。
