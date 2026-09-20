# 反馈5 持续执行检查点 / Feedback 5 progress checkpoint

更新 / Updated: 2026-09-20（证据复核第 5 轮 / evidence-review round 5）

## 当前代码 / Current code

- 提交 `f7f039d` 之上：本轮完成**原始 1920×1080 Composite 1800 秒正式验收（13/13 PASS）**，报告新增 4.2.2。
- 三种 1800 秒长稳现已全部执行：原始 Composite 13/13、受控五路 12/12、真实五路 8/9。

## 本轮完成 / Completed this round

**原始 Composite 1800 秒**（`tests/artifacts/browser-soak/2026-09-20T14-16-38-047Z-composite`）：**十三项判据全部通过**——有效观测 1800.1 s、解码 **30.00/30 fps（1.000）**、首帧 7446 ms、最大帧间隔 415 ms、呈现 29.08 fps、`program-and-inputs` 五路输入全程 healthy 且 0 个不健康采样。服务端同步采样（`tests/artifacts/soak/2026-09-20T14-16-32-052Z-composite-1080p-fixed-f7f039d`，绑定提交 `f7f039d`）30 分钟每采样 `routes=1 visible=5 healthy=5 publish=publishing`，自身判定 PASS。

## 下一条具体动作 / Next concrete steps

1. **真实来源单路故障注入**（唯一剩余项）：用本地 TCP 测试代理把一路真实相机包起来，运行中暂停/恢复该代理，其余四路不得受影响，恢复 ≤15 s；注入窗口用 `WEBOBS_SOAK_EXCUSED_WINDOWS` 与正常重启分开判定。
2. 把 back_3 / front_3 的来源限制整理为设备参数建议供用户决定（不擅自修改相机配置）。

## 六项状态 / Status

| 项目 | 状态 | 证据 |
|---|---|---|
| F5-01 画面填充 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-02 干净画面 | 已实现并自动化验证 | 聚焦套件 22/22 |
| F5-03 硬件加速 | 渲染 D3D12 已验证；NVENC 吞吐低于 x264 已回退；NVENC/VA-API 转码分支 slice 行为未验证 | 报告第 2、4.4.2 节 |
| F5-04 本地合成 | **原始 1920×1080 规格 1800 秒 13/13 PASS** | 报告 4.2.2 |
| F5-05 音频管理 | 批次 A/B/C 已提交并有单测；音频回归三项全绿；视频位移与客户端侧相对偏移实测通过 | 报告第 5 节 |
| F5-06 播放稳定 | 受控五路 12/12、原始 Composite 13/13、真实五路 8/9（仅 back_3 首帧 23.9 s）；**故障注入待执行** | 报告 4.2.2、4.3.7、4.3.8 |

## 环境与阻塞 / Environment and blockers

- 开发栈、fixture、Vite 均已停止，端口全关；用户数据已还原校验（`cameras.db` `ac028d59…`、`scene.json` `87fcca32…`、studio 5 来源 5 项）。
- 复现要点：Direct/Hybrid 长稳用 Direct-only 栈，Composite 长稳用 `--composite` 栈；两次运行后 `cameras.db`/`scene.json` 都会被运行中的栈重写（内容语义相同），必须按备份还原并用 sha256 校验。
