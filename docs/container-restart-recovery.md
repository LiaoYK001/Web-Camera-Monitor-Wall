# 容器重启与异常退出恢复 / Container restart and crash recovery

## v3.5 的遗留 FIFO 故障 / Stale FIFO failure in v3.5

如果日志循环显示 `v2-M7 upgrade guard prepare: already-complete` 和 `mkfifo: ... /tmp/webobs-go2rtc-log.2: File exists`，阻断启动的是遗留日志管道。`already-complete` 只是已完成迁移检查的提示。旧入口按进程号分配路径；强制终止、Docker 的停止超时或宿主机掉电会跳过清理，而同一个容器下次通常复用进程号和可写层中的 `/tmp`。删除账号、数据库或配置卷无法正确修复这个问题。

The migration message is informational. v3.5 reuses a PID-derived go2rtc log FIFO in the container's persistent writable layer. SIGKILL or host power loss skips cleanup; the next start collides with the old FIFO and exits before login is available.

修复后的入口将所有服务 FIFO 与 Weston 临时运行目录放在 `mktemp` 分配的 `/dev/shm/webobs-runtime.<随机值>`：目录 `0700`，FIFO `0600`。默认 Docker/Podman 的私有 `/dev/shm` 是 tmpfs，停止容器即清空；独立随机目录也避免共享 IPC 环境中的旧路径冲突。硬件探测日志使用另行分配的私密 `/tmp` 文件，不占用共享内存。不读取、删除或沿符号链接访问旧 `/tmp/webobs-*-log.*`，不修改持久化 go2rtc YAML。

Each start now owns a unique private directory on the container's ephemeral shared-memory filesystem. Legacy FIFO paths, regular files and symlinks are ignored. Persistent user configuration is preserved.

启动失败、正常退出、启动期间收到停止信号均走统一清理。先给核心最多 10 秒封装输出，期间保留媒体网关与渲染器；随后给辅助服务最多 5 秒退出，并让日志过滤器读到 EOF。卡住的进程被终止并报告非正常退出，避免无限 `wait`。升级尚未提交且停服被强制中断时，保留 pending 标记，交由下一次安全启动检查快照并恢复，不与仍可能写入的后代进程争用数据。

Cleanup also runs on startup errors and cancellation. Shutdown has bounded waits, preserves the renderer while the core flushes, and reports forced termination. An uncommitted migration interrupted during shutdown is recovered by the next safe startup.

## 现有 v3.5 的轻量热修 / Apply the fix to an existing v3.5 deployment

以下步骤从已发布 v3.5 的固定 digest 构建**本地热修镜像**，仅替换产品入口，不重新编译或切换 WebUI/后端。原 v3.5 Release、镜像标签与 Windows 更新源保持不可变。新源码已修复不代表远端 `v3.5`/`latest` 已自动变更。

Build a local recovery image on the exact published v3.5 digest. It replaces only the supervisor entrypoint; it does not introduce development backend/UI changes or overwrite an immutable release.

1. 获取包含本修复的源码，保留现有 `.env`、secrets、录像与配置卷。先使用产品已有备份入口备份配置与数据库；容器无法启动时可在停止容器后备份其配置卷。不要运行 `down --volumes`。
2. 在仓库根目录构建（Docker 或 Podman 均可使用这份 Dockerfile）：

   ```sh
   docker build -f docker/Dockerfile.restart-hotfix -t webobs:v3.5-restart-hotfix .
   ```

3. 在原部署的私密 `.env` 中设置 `WEBOBS_IMAGE=webobs:v3.5-restart-hotfix`。使用**原来的 Compose project 名、工作目录和全部覆盖文件**执行以下命令；认证、HTTPS、GPU、端口、录像挂载与配置卷必须沿用原值。例如只使用基础 Compose 的部署：

   ```sh
   docker compose -f compose.yaml up -d --no-build --pull never webobs
   docker compose -f compose.yaml ps
   ```

   有 HTTPS 覆盖时，继续传入原来的 `-f compose.m6-auth.yaml -f compose.m6-production.yaml` 等参数。非 Compose 部署应在原管理工具中替换镜像并保留原挂载；不要照抄一个新的空配置容器。

4. 验证登录、账号偏好、Scenes、go2rtc 配置与视频播放，再用原 Compose 参数运行 `restart webobs` 并复查。保存热修源码提交和本地镜像 ID，之后升级到正式包含修复的版本。

Keep the same Compose project, overlays and volumes when recreating the container. `--no-build --pull never` selects the newly built local image. Verify the existing account, scenes and go2rtc streams after restart. No data reset is needed.

## 验证范围与运行设置 / Validation and operational settings

```sh
python3 tests/test_container_entrypoint.py
python3 tests/test_go2rtc_runtime.py
python3 tests/test_preupgrade_guard.py
python3 tests/container_restart_runtime.py --image webobs:v3.5-restart-hotfix
python3 tests/container_restart_runtime.py --image webobs:v3.5-restart-hotfix --composite
```

入口测试实际执行同一 shell 入口，使用隔离的合成子进程覆盖旧 FIFO/符号链接、权限、启动失败、启动取消、临时空间不可用、日志读进程滞留、重复停止信号与核心/服务不响应停止。镜像测试只创建随机命名的独立测试容器和临时卷，覆盖 3 次正常重启、3 次 `SIGKILL` 重启、辅助服务崩溃和保留原卷重建；每次检查原登录会话、重新登录、配置/录像摘要、SQLite `integrity_check`、私有临时目录和认证 MSE 视频。`--composite` 另外启动软件 OBS/Xvfb，覆盖遗留显示锁恢复；不代表硬件渲染器验收。

The image test checks the actual packaged product and synthetic FFmpeg media, including persistent accounts and files after repeated restarts. It does not modify existing containers or qualify physical cameras, real host/disk power cuts, or every Podman host.

2026-10-05 已在公开 v3.5 固定 digest 上构建热修，Direct-only 和软件 OBS/Xvfb 两种模式均完成上述重启、崩溃与保留原卷重建验证；入口 10 项回归、go2rtc 私密配置 3 项和升级快照 3 项通过。The published v3.5 base was tested in both Direct-only and software OBS modes, with synthetic media and the stated qualification limits.

保留 Compose 的 `stop_grace_period: 20s` 或更长，让正常停止有时间封装录像。部署需要宿主机重启后自动恢复时，在原服务覆盖中显式配置 `restart: unless-stopped`，同时确认 Docker/Podman 本身随系统启动。重启策略不能修复旧镜像的 FIFO 错误，因此先应用热修。不要把 `/dev/shm` 绑定到持久化配置卷；需有可写空间。

突然断电不能执行任何退出处理；本修复保证临时资源不会阻断下次启动，并验证进程级强制终止后的数据恢复。断电瞬间尚未落盘的配置或录像仍依赖文件系统、磁盘与应用的写入边界；定期备份、UPS 与实际掉电验收仍有各自用途，不承诺任意掉电无数据损失。

Keep a 20-second or longer stop grace period. Automatic restart after host boot requires an explicit restart policy and an enabled container engine. Process-kill testing establishes restart recovery, not guaranteed durability of writes interrupted by a physical power cut.
