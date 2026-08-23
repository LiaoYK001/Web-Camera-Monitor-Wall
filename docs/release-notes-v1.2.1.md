# v1.2.1 release notes / 发布说明

`v1.2.1` is the supported final v1 release. It contains the same v1-M1 through v1-M11 product scope and qualification evidence as v1.2, plus a runtime portability fix.

`v1.2.1` 是受支持的最终 v1 版本，包含与 v1.2 相同的 v1-M1 至 v1-M11 产品范围和资格证据，并增加运行时可移植性修复。

## Why v1.2.1 was required / 为什么需要 v1.2.1

The first `v1.2` image was built from a Windows worktree where two Python files had CRLF line endings. Docker's build-time tests invoked them through `python3`, so the code tests passed, but the runtime entrypoint initially executed their shebangs directly. Linux interpreted the first line as `python3\r`, and Camera Registry readiness failed during the post-publish container smoke test.

首个 `v1.2` 镜像来自 Windows 工作树，其中两个 Python 文件使用 CRLF。Docker 构建测试通过 `python3` 显式运行这些文件，因此代码测试通过；但运行入口最初直接执行 shebang，Linux 将首行解释为 `python3\r`，发布后的容器烟测因 Camera Registry 无法就绪而失败。

The immutable Git tag `v1.2` was not moved. Its image must not be deployed. `v1.2.1` adds all three defenses:

不可变 Git Tag `v1.2` 未被移动，其镜像不得部署。`v1.2.1` 增加三层防护：

- Git enforces LF for every `*.py` and `*.sh` file.
- The image normalizes copied Python launchers and verifies every shebang during the build.
- The entrypoint invokes internal Python services explicitly through `python3`.

- Git 对所有 `*.py` 与 `*.sh` 强制 LF。
- 镜像构建时规范化复制的 Python 启动文件并验证每个 shebang。
- 入口通过 `python3` 显式启动内部 Python 服务。

The final-image smoke test must start Camera Registry, the event service, MediaMTX and the Gateway Direct-only core, then exit cleanly. `latest` points to v1.2.1 after this gate passes.

最终镜像烟测必须启动 Camera Registry、事件服务、MediaMTX 与 Gateway Direct-only 核心并正常退出；该门禁通过后，`latest` 指向 v1.2.1。
