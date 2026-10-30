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

## 2026-10-30 Windows 性能候选续接 / Windows performance candidate follow-up

本轮公开 CI 在旧锁文件上因新通告失败，性能候选需同时完成门禁修复。Electron 在同一 44.x 主版本更新到 44.9.1，Vite 更新到 8.1.6，DOMPurify 更新到 3.4.17；fast-uri/serialize-javascript/undici 6.x/7.x 分别固定到 3.1.9/7.1.3/6.29.1/7.30.1。Monaco 的内嵌 DOMPurify 仍必须经过完整工厂替换，不能只改顶层 package.json；资源回归与镜像探针期望同步到 3.4.17。

The stale locks failed the public audit gate. Electron/Vite/DOMPurify receive same-major fixes, and affected transitive dependencies receive pinned patched versions. The actual Monaco sanitizer factory and its probes are updated as well; a top-level package override alone cannot patch the embedded copy.

依据：[Electron 通告](https://github.com/advisories/GHSA-jr5w-w6x2-84p9)、[DOMPurify 通告](https://github.com/advisories/GHSA-cg2g-xh64-v4q7)、[Vite 通告](https://github.com/advisories/GHSA-587h-7wmj-h5pm)、[Undici 通告](https://github.com/advisories/GHSA-xjj6-f33q-929c)。Sources: the linked upstream advisories specify the affected and fixed versions.

`deepmerge` 4.3.1 的 [GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) 尚无已发布修复版。它只经 Workbox 的 `@rollup/plugin-node-resolve@16.0.3` 进入此工作区，而该消费者在 CJS/ESM 中只调用一次 `deepMerge({}, defaults)`，输入是自身固定的纯数据默认选项。采用限定版本的源码补丁，将这处调用改为 Node 24 的 `structuredClone(defaults)`，保留现有递归冻结；同时移除该消费者不再使用的 deepmerge 依赖。没有伪造上游版本或忽略 advisory，未来升级消费者时须重新审查并去掉补丁。

There is no published fixed deepmerge release. A version-scoped node-resolve patch replaces its sole constant-defaults clone with native structuredClone in both distributions and removes the now-unused dependency using pnpm's scoped removal override. Recursive freezing remains. This is neither an advisory suppression nor a fabricated upstream release. Reassess/remove the patch when upgrading the consumer.

`dependency-security.test.mjs` 通过 Workbox 的真实解析路径同时加载 CJS/ESM 构建，检查默认数组和冻结，并实际使用 Rollup 构建临时包的导入；普通 PWA 生产构建也验证了真实 Workbox 消费链。两个工作区 `pnpm audit --audit-level=low` 当前均通过。Electron 的真实沙盒/下载器/代理/TLS/更新回退及 Windows 全量候选仍分别验证，不用审计结果替代。

The dependency regression loads both actual Workbox resolver builds, checks defaults/freezing and bundles a temporary package through real Rollup. Both low-threshold workspace audits pass. Native Electron, downloader/proxy/TLS/update contracts and complete Windows packaging retain their separate gates.
