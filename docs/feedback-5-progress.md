# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-19（持续执行第 10 轮 / continuous-execution round 10）

## 当前代码 / Current code

- 上一提交 `a886c4a`。本轮待提交：`web/tests/direct-latency-probe.mjs`（新增探针）、报告与检查点。
- 用户场景保持原始 5 路相机（sha256 `87fcca32…`）。
- 未跟踪文件保持原样。

## 本轮结论：Direct/Hybrid 首帧已定位到服务端串行等待 / Direct/Hybrid first frame traced to a serialized server wait

120 秒探针（真实五路相机）显示五块瓦片在 **507 ms 同时**进入 connecting，却以约 **11 秒**固定间隔依次 live：12.8 / 23.6 / 32.8 / 44.6 / 52.8 秒。HTTP 计时显示五个 `POST /api/v2/media-plans/<id>/whep` 在 30 毫秒内同时发出、耗时却是 14.99 / 25.13 / 32.89 / 45.41 / 54.40 秒。

**根因**：`ControlServer` 只有一个 io_context 线程（`core/src/control_server.cpp:3890`）；`create_direct()`（754）与 `create_client_plan()`（781）都在全局 `route_operation_mutex_` 保护下执行完整的 `ensure_playback_route()`，而后者等待按需 MediaMTX 路由就绪（`runOnDemandStartTimeout` = 10 秒）。单线程 + 全局锁把 N 路来源串成 N×约 11 秒。

**下一轮修复方向**：不要跨“等待路由就绪”持全局路由锁（改按来源加锁）；不要让该等待阻塞唯一的 io_context 线程（移到工作线程，或先返回 WHEP 会话）。改完用 `node web/tests/direct-latency-probe.mjs` 复测。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264，已按实测默认回退 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | **原始规格 30 分钟验收通过** | `tests/artifacts/soak/2026-09-19T12-53-07-152Z-composite-1080p-x264-3d281e4/` |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；端到端音频驱动部分通过 | 报告第 5 节 |
| F5-06 播放稳定 | 合成模式四项门槛全过；Direct/Hybrid 首帧已定位到服务端串行等待（未修） | `tests/artifacts/browser-soak/2026-09-19T12-53-10-550Z-composite/`、报告 4.3.1 |

## 下一条具体动作 / Next concrete steps

1. 按上述方向修复 Direct/Hybrid 首帧串行等待，并用探针复测（目标：五路并发建立，首帧回到个位数秒）。
2. 用健康来源复测 Direct/Hybrid 的最大帧间隔。
3. “零来源重启”判据：用健康来源复测确认产品在来源健康时零重启。
4. 受控单路断开/恢复注入。
5. 修正 `tests/audio-regression.mjs` 的启动空档与负偏移 PTS 测量。

## 环境与阻塞 / Environment and blockers

- 后台作业不跨轮次存活；长稳被中断时用 `tests/soak-derive.mjs` 从增量证据重建结论。
- 探针需要已配对浏览器；未配对时它会先走产品自身的配对流程。
- 真实相机首帧本身较慢（合成模式就绪也需 20 秒以上），修复后应区分“服务端等待”与“来源首帧”。
