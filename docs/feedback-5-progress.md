# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-20（证据复核轮，goal 2 第 1 轮 / evidence-review round 1）

## 当前代码 / Current code

- 上一提交 `ca76554`。本轮先修验收判定器：新增 `tests/soak-verdict.mjs`（纯判定模块）、`tests/test-soak-verdict.mjs`（20 条回归），重写 `web/tests/local-runtime/browser-soak.spec.ts`（观察器先于启动安装、按 video 代次累计、进行中无帧年龄、显式预期来源与目标、固定收尾顺序）与 `tests/soak-derive.mjs`（同一套规则 + 无法追溯验证标记）。
- 报告新增第 0 节（总体结论）与 1.1 节（判定器修复），并把 4.2.1 / 4.3.6 的历史“全部通过”改写为复核后的 INCOMPLETE。

## 本轮完成：判定器修复与反例验证 / Oracle fixed and proven by counter-examples

- `node --test tests/test-soak-verdict.mjs` → **20/20 通过**：正常 25 fps、最后 20 秒断流、中途替换 video 元素、五路缺一路、1790 秒提前结束、缺 target、代次归零、超 3 秒后恢复、故障窗口内停顿被豁免、最终快照前拆卸判 INCOMPLETE、解码未知不得判过、派生路径（完整/中断/旧格式/短记录）四种输入。
- 端到端（真实产品页面 + 健康合成源）：120 秒 smoke → **SMOKE_PASS**（decoded 25.00–25.01 fps、presented 24.86–24.99、首帧 5.7–7.0 秒、进行中无帧年龄 11–48 ms）；运行中停掉一路合成源 → **SMOKE_FAIL**，`frame-stall` 与帧率判据同时失败（该路 51.4 秒无帧）。
- 端到端反例还暴露了我自己判定逻辑的一个漏洞：**只有进行中的尾部断流、没有已结束的长停顿记录时，`frame-stall` 曾误判为通过**。已修正（`unexpectedStalls > 0 || trailingStallWithoutRecovery`）并补了回归用例。
- 用修复后的判定器重新派生历史长稳：`2026-09-19T12-53-10-550Z-composite` 与 `2026-09-20T11-01-11-166Z-direct` 均为 **INCOMPLETE**（无 final 标记、无进行中无帧年龄、无代次计数；Direct 运行最后 15.04 秒零帧推进，有效观测仅约 1782.4 秒）。可确认的只有受控来源下的 presented 帧率与首帧。

## 下一条具体动作 / Next concrete steps

1. 控制面串行激活：定位 `ControlServer` 单 io_context 线程与全局路由锁造成的逐路排队，把同步上游媒体 I/O 与探测移出该线程（有界工作池 + 回投 executor），按来源在途合并、细粒度锁、锁内不做网络等待、超时/取消、关闭时安全舍弃在途任务；补并发回归（五路健康、一路超时、同来源重复 activate、授权撤销、客户端断开、关闭服务）。
2. 真实来源证据：低竞争、明确 RTSP 传输下测输入帧率/关键帧间隔/损坏与恢复，并与经网关后的结果对比。
3. 编码修复适用范围：增加 HEVC→H264 Hybrid 路径验证，确认相机走的确实是修复覆盖的链路；NVENC/VA-API 仅在可用时做短对照。
4. 固定新 SHA 后按顺序重跑：受控五路 1800 秒、真实五路 1800 秒、原始 Composite 1800 秒、真实来源单路故障注入。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264，已按实测默认回退；NVENC/VA-API 转码分支的 slice 行为未验证 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | 受控/原始规格的 presented 与首帧达标；正式 30 分钟按修复后判定器为 **INCOMPLETE** | 报告 4.2、4.2.1 复核修正 |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归三项全绿；视频位移与客户端侧相对偏移均实测通过 | 报告第 5 节 |
| F5-06 播放稳定 | **受控来源性能验证通过；原始部署最终验收尚待关闭**——历史两次长稳按修复后判定器均为 INCOMPLETE；真实相机首帧 31.7–74.4 秒、停顿 3.07–6.70 秒未关闭 | 报告 0、1.1、4.3.6、4.5 |

## 环境与阻塞 / Environment and blockers

- 开发栈与 Vite 当前在运行（本轮 smoke 验证用），合成源为 720p25（不带 `-tune zerolatency`），`cameras.db` 已备份后临时指向合成源。
- 用户数据必须在收尾时还原并校验：`cameras.db` sha256 `ac028d59…`、`scene.json` sha256 `87fcca32…`、`studio.json` 5 来源 5 项。
