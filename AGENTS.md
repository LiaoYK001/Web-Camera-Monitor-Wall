# Repository guidance

## Architecture

- `web/`: React/TypeScript/Vite local-first PWA, account workspace and monitor wall.
- `core/`: C++20 control server, authentication/Origin/RBAC checks and optional libobs scene composition.
- `camera/`, `events/`, `nvr/`, `cluster/`, `v2/`, `analytics/`, `archive/`, `backup/`: loopback Python services owned by the product supervisor.
- `go2rtc/go2rtc/`: complete upstream go2rtc submodule pinned to v1.9.14 (`b5948cfb25404cc5cb37b166ecaa2dca20b11d4b`). Protocol adaptation and optional FFmpeg conversion happen here; MediaMTX remains the existing distribution gateway; OBS composes scenes.
- `obs/obs-studio/`: pinned upstream OBS submodule. Do not edit upstream checkouts to implement product behavior. Keep integration patches/build helpers outside them.
- `docker/Dockerfile`, `docker/entrypoint.sh`, `compose*.yaml`: one product image, service supervision and deployment. `scripts/dev.mjs` + `scripts/dev-native.py` provide local development.
- `desktop/`: full native Windows x64 Electron product, Job Object ownership, complete NSIS runtime and explicit GitHub update installation. Keep it separate from `clients/` Qt products. Dependency and distribution contracts are described in `docs/windows-desktop.md`.
- `android/`: independent Java/WebView Android client for existing product backends; keep it separate from Qt. Build/signing and emulator validation are described in `docs/android-client.md`. APKs require a local signature; preserve the development key outside Git and never claim a development APK is a stable release.

## Working rules

- Primary delivery targets are the Docker/Podman container, native Windows x64 desktop and independent Android client. They follow regular `vA.B` product releases. Native Linux x86/ARM, Windows ARM and Windows 32-bit are future expansion targets, normally built, qualified and published at major `vA.0` milestones such as v5.0/v6.0/v7.0 rather than every minor release. Source support is not platform qualification.
- 当前主要交付端为容器、Windows x64 与独立 Android 客户端，随常规 `vA.B` 更新。Linux 原生 x86/ARM、Windows ARM 与 Windows 32 位为后续拓展端，一般在 v5.0/v6.0/v7.0 等 `vA.0` 大版本节点集中构建、验证和发布，不跟随每次小版本更新；源码支持不等于完成平台验收。

- Write commit messages, PR titles/descriptions and merge messages in both Chinese and English. Use a concise bilingual subject such as `fix: 修复更新检查 / fix update checking`; include both languages in any substantive body. Override GitHub's English-only default merge message when merging.
- 提交信息、PR 标题/说明及合并信息必须包含中英文双语。标题简洁，正文有实质说明时也提供双语；合并时显式设置双语信息，不沿用 GitHub 的纯英文默认标题。
- Inspect related code and documentation before changing behavior. Keep unrelated working-tree edits.
- Preserve Direct-only operation: enabling go2rtc does not require OBS composition or continuous transcoding.
- All go2rtc UI/API/media requests use `/api/v1/go2rtc/`, the product authentication gate and `settings.manage`. Its complete configuration and diagnostics belong to administrators and can contain credentials.
- Keep service/API/RTSP listeners on loopback by default; do not expose upstream management ports in base Compose. Keep secrets, camera URLs, logs, recordings and runtime configuration out of Git and public outputs.
- Keep request buffers bounded, reject nonmatching Origin and unsafe paths, and strip product credentials when proxying upstream.
- Persist go2rtc configuration with the existing private configuration volume. Preserve user configuration on restart and upgrade.
- Update integration/deployment docs when lifecycle, packaging, ports or configuration change. Record upstream commit and licenses in source bundles.
- Stable Windows NSIS releases are unsigned by default and include verified `latest.yml`; signing is optional via explicit `-Sign`. Keep SHA-512/size validation, user-confirmed installation, backups and normal service shutdown. Development `-dev.*` packages remain outside the stable feed.
- Use `rg` for searches; exclude upstream source/build dependencies when exploring product code. No automatic delegation is required.

## Validation

- Website sources: `go2rtc/online_source.py` is the fixed on-demand yt-dlp/Streamlink relay; pin all artifacts in `go2rtc/online-source-dependencies.lock.json`. Keep website cookies in the private go2rtc configuration directory, never forward product credentials, and never enable arbitrary renderer commands. Android uses backend extractors. Run `tests/test_online_source.py`, real `tests/online_source_media.py` and authenticated `tests/online_source_runtime.cjs`; external-site support lists are not qualification evidence. See `docs/online-sources.md`.

- Frontend: `cd web; pnpm typecheck; pnpm build`; focused Playwright tests use `pnpm exec playwright test -c playwright.local.config.ts --project=chromium <spec>` (pnpm script `--` can prevent spec filtering).
- go2rtc assets: `cd web; pnpm go2rtc:ui` assembles the complete upstream UI with locally packaged third-party dependencies.
- C++: CMake/CTest in Linux/WSL or Docker; Windows uses MSVC x64 and the pinned OBS/vcpkg builds via `desktop/scripts/build-windows.ps1`. Windows source support does not imply completed installation/media qualification.
- Desktop: `cd desktop; pnpm test; pnpm test:electron`; `python desktop/tests/test_native_runtime.py` includes snapshot/transcoder tests and a Job lifecycle test only when a real Windows runtime is built. `pnpm test:runtime` requires that real runtime and exercises fresh account setup, authenticated go2rtc and service restart in an isolated profile; `pnpm test:main` exercises the actual entry, two fixed Scene projectors, shared login, tray hide and normal exit. After packaging, `pnpm test:package` launches the fused ASAR with a clean PATH, checks first login/go2rtc and owner-crash cleanup. These are not camera or clean-install qualification. Keep automatic install-on-quit disabled. Never attach an unsigned development package to the stable updater feed.
- Run `tests/test_go2rtc_runtime.py` for private configuration/lifecycle contracts and the dedicated proxy integration test for HTTP/WebSocket streaming.
- `cd desktop; pnpm test:install` validates the actual NSIS install/uninstall in an isolated Unicode path and retains data on default uninstall. It refuses an existing WebOBS installation or shortcuts; it does not qualify clean Windows systems, cameras or signed updates.
- Distinguish browser fixtures and synthetic protocol tests from real camera qualification. Report any full-image or device checks that could not run.
- Android: `android/scripts/build-android.ps1` runs JUnit, lint, APK build and signature verification. `android/tests/test_emulator.py --serial <explicit-device> ...` exercises the actual installed debug APK through ADB against an isolated complete product image. It does not qualify physical cameras/ARM devices or APK automatic updates; do not clear existing device data.
