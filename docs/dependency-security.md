# 依赖安全与审计门禁 / Dependency security and audit gate

本文记录 2026-10-06 v4 收口轮次中两个构建期依赖告警的处理方式、可复现证据与未完成边界。发布纪律见[版本与分支](versioning-and-branches.md)；这不是发布授权，也不代表已安装产品验收。

## 1. 门禁 / The gate

公开 CI（[web-runtime-ci.yaml](<../.github/workflows/web-runtime-ci.yaml>)）分别在 `web/` 与 `desktop/` 工作区执行 `pnpm audit --audit-level=low`。历史 CI 绿色或 Dependabot 暂无开放告警都不能替代当前源码的重新审计；两个工作区必须各自通过。

~~~powershell
# 在 web/ 与 desktop/ 目录分别执行（PATH 上的 pnpm 代理可能不可用，使用仓库固定版本）
& "$env:APPDATA/npm/pnpm.cmd" audit --audit-level=low
~~~

2026-10-06 两个工作区均为 `No known vulnerabilities found`（退出码 0）。

## 2. web：source-map-js / web: source-map-js

- 告警：[GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)，经 Vite → PostCSS 进入构建链。
- 处理：`web/pnpm-workspace.yaml` 以 `source-map-js@^1.2.1: 1.2.2` 覆盖全部 **1.x** 消费者，锁文件已解析为 1.2.2；没有跨到不兼容的 2.x API。
- 依据：上游修复提交 `cf7658058ceeaa8619d5ae0ec90be6905209d016`（1.2.2）。
- 回归：`web/tests/dependency-security.test.mjs` 通过 Vite 的解析路径（而非测试专用依赖）加载真实的`source-map-js`，断言版本为 1.2.2，并覆盖索引映射的超大/非法 offset 拒绝、合法边界与嵌套节、以及真实 PostCSS 生成的普通映射往返：

~~~powershell
# 在 web/ 目录执行
node --test tests/dependency-security.test.mjs
~~~

## 3. desktop：sprintf-js / desktop: sprintf-js

- 路径：`electron-builder` → `@electron/get` → `global-agent` → `roarr` → `sprintf-js`。
- 现状：**上游没有可用的已修复版本**。registry 中 `sprintf-js` 最新发布仍为 1.1.3；`1.1.4` 返回 E404，公开 advisory 元数据的 `first_patched_version` 为空。因此**不伪造补丁版本，也不做无意义的全局覆盖**。
- 处理：`desktop/pnpm-workspace.yaml` 只把 `@electron/get@3.1.0` 这一条路径下的 `global-agent` 提升到 `4.1.3`。上游 4.1（`dd073b2d3c36a5742d6dfd001468a2ee6f50343c`）移除了整个 `roarr` 依赖，受影响的 `sprintf-js` 不再进入依赖树；`bootstrap()` 仍以 CommonJS 形式导出，下载器调用点不变。
- **必须同时应用的补丁**：4.x 把“是否转发 TLS 选项”的守卫从 `this.protocol === 'https:'` 改成了 `configuration.secureEndpoint`。该属性只在 Node 自带 `https.Agent.createConnection` 内被置真，而这个类完全替换了 `addRequest`/`createConnection`，所以守卫恒假，代理路径会静默丢弃 `ca`/`rejectUnauthorized`/`servername`。实测：同一请求选项下 3.0.0 成功、4.1.3 返回 `DEPTH_ZERO_SELF_SIGNED_CERT`，`NODE_EXTRA_CA_CERTS` 也无法挽救。这会让使用企业代理 + 自签/私有 CA 的构建直接失败，因此不能只写覆盖。
  处理方式：`desktop/patches/global-agent@4.1.3.patch`（经 `pnpm patch-commit` 生成，锁文件记录 `patch_hash=9542a4f3…`）恢复协议守卫，并把真实目标 `host` 传入 TLS 选项用于证书/主机名校验；`servername` 对 IP 目标保持未设置（符合 RFC 6066，不再发送 IP SNI）。上游发布修复后应删除该补丁与覆盖。
- 边界：这是**跨主版本的作用域覆盖 + 一处已记录补丁**，因此必须验证真实下载路径而不是只看审计输出。`desktop/tests/build-proxy.test.mjs` 启动本机 HTTP 与自签 TLS 夹具，覆盖直连、HTTP 代理、`NO_PROXY`、受信与不受信证书、主机名不匹配，并断言代理凭据不会泄漏到源站：

~~~powershell
# 在 desktop/ 目录执行
node --test tests/build-proxy.test.mjs
~~~

- 未完成：完整 `electron-builder` 打包与真实 GitHub 下载属于候选构建门禁，本机没有 `desktop/runtime/manifest.json` 时不在此轮结论内；夹具只证明下载器的直连/代理/TLS 行为，不代表真实公网下载或已安装产品验收。若上游发布真正的修复版本，应改回普通版本升级并删除该作用域覆盖与补丁。

## 4. 诚实边界 / Honest limits

- 审计通过只说明当前锁文件在当日公开数据下没有已知告警，不等于依赖不存在未知缺陷，也不等于已完成 SBOM/许可证或完整打包验收。
- 本环境的 registry 主机不可直接抓取，因此 §3 的“无可用修复版本”来自修復轮次记录与 advisory 元数据；若上游状态变化，以重新审计结果为准。
- Android 侧依赖（Gradle/JUnit/lint）与容器镜像基础层不在 `pnpm audit` 范围内，需要各自的候选构建与审计证据。
