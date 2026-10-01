# Repository guidance

## Architecture

- `web/`: React/TypeScript/Vite local-first PWA, account workspace and monitor wall.
- `core/`: C++20 control server, authentication/Origin/RBAC checks and optional libobs scene composition.
- `camera/`, `events/`, `nvr/`, `cluster/`, `v2/`, `analytics/`, `archive/`, `backup/`: loopback Python services owned by the product supervisor.
- `go2rtc/go2rtc/`: complete upstream go2rtc submodule pinned to v1.9.14 (`b5948cfb25404cc5cb37b166ecaa2dca20b11d4b`). Protocol adaptation and optional FFmpeg conversion happen here; MediaMTX remains the existing distribution gateway; OBS composes scenes.
- `obs/obs-studio/`: pinned upstream OBS submodule. Do not edit upstream checkouts to implement product behavior. Keep integration patches/build helpers outside them.
- `docker/Dockerfile`, `docker/entrypoint.sh`, `compose*.yaml`: one product image, service supervision and deployment. `scripts/dev.mjs` + `scripts/dev-native.py` provide local development.

## Working rules

- Inspect related code and documentation before changing behavior. Keep unrelated working-tree edits.
- Preserve Direct-only operation: enabling go2rtc does not require OBS composition or continuous transcoding.
- All go2rtc UI/API/media requests use `/api/v1/go2rtc/`, the product authentication gate and `settings.manage`. Its complete configuration and diagnostics belong to administrators and can contain credentials.
- Keep service/API/RTSP listeners on loopback by default; do not expose upstream management ports in base Compose. Keep secrets, camera URLs, logs, recordings and runtime configuration out of Git and public outputs.
- Keep request buffers bounded, reject nonmatching Origin and unsafe paths, and strip product credentials when proxying upstream.
- Persist go2rtc configuration with the existing private configuration volume. Preserve user configuration on restart and upgrade.
- Update integration/deployment docs when lifecycle, packaging, ports or configuration change. Record upstream commit and licenses in source bundles.
- Use `rg` for searches; exclude upstream source/build dependencies when exploring product code. No automatic delegation is required.

## Validation

- Frontend: `cd web; pnpm typecheck; pnpm build`; focused Playwright tests use `pnpm exec playwright test -c playwright.local.config.ts --project=chromium <spec>` (pnpm script `--` can prevent spec filtering).
- go2rtc assets: `cd web; pnpm go2rtc:ui` assembles the complete upstream UI with locally packaged third-party dependencies.
- C++: CMake builds and CTest inside the Linux/WSL or Docker build environment. The production core is Linux, not Windows C++.
- Run `tests/test_go2rtc_runtime.py` for private configuration/lifecycle contracts and the dedicated proxy integration test for HTTP/WebSocket streaming.
- Distinguish browser fixtures and synthetic protocol tests from real camera qualification. Report any full-image or device checks that could not run.
