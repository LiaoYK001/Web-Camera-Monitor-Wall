# 当前交接 / Current handoff

> 自动生成，勿手改；唯一数据源为 [state.json](state.json)。
> 快照版本 253 · 2026-11-19T20:32:44+08:00（UTC+08）

[总览](STATUS.md) · [路线图](ROADMAP.md) · [任务](TASKS.md) · [日志](DEVLOG.md) · [交接](HANDOFF.md) · [协作规则](PLAYBOOK.md)

新 Agent 先检查 `git status --short --branch`，阅读根目录 AGENTS.md 和 PLAYBOOK.md；认领后才改动任务范围。其他 Agent 的未提交修改不能删除、重置或覆盖。

## 进行中、阻塞与已暂停

- **R7-001 · 阻塞**；负责人：未认领；阻塞：完整 v5 候选已发布，但目标机真实五路/逐路硬解、物理多屏/DPI、音频设备、两小时长稳和 OBS 同条件性能尚无设备证据。；下一步：准备目标机集中验收：安装候选、迁移本人旧数据、真实五路/多屏/音频/长稳及 OBS A-B。
- **HOLD-001 · 暂停**；负责人：未认领；阻塞：既有用户决定暂停 Android/容器候选同步与发布；扩展原生平台按主要版本节点安排。；下一步：保持暂停；不作为当前 Windows 预览发布阻塞项。
- **V51-005 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后 rebase 到 dev（publish_candidate.py 为 add/add，保留 #69 的超集实现），再复跑发布链测试；发布链先验证到待发布状态，不自动发布
- **V51-007 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：#67 合入 dev 后把 #70 base 改为 dev 并派发带 backup_restore_windows 门禁的 Windows 运行。
- **V51-008 · 进行中**；负责人：qwen38-next-v51-20261119-01；阻塞：无；下一步：读 rc.61（run 44524750280 @ 937129b）回执：先看 native-program-take 的 layerAttribution/feedDecodeProbe/renderProbe 判定冻结在哪一层，再确认 program-track-controls 与 NSIS 安装态在同一个 run 全绿；三者同轮通过才按 #67→#70→#71→#74→#75→#76 双语合入 dev，并冻结候选（soak 120 + scripts/v51-ci-gate.py --freeze + publish_candidate.py --verify-only→--confirm）。/ Read the rc.61 receipt: name the frozen layer from layerAttribution/feedDecodeProbe/renderProbe at native-program-take, then require per-track gain and the NSIS install to pass in the same run before merging the stack and freezing the candidate.
- **V51-010 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：随完整候选（含 #71）派发带 native-product-lan.json 的 Windows 运行；真实第二台设备验收仍待用户目标机
- **V51-011 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：等 #67 合入 dev 后把 f0eb858 迁到 codex/v51-r5-soak 并转 dev 开 PR，随后随完整候选派发 soak_minutes=120 的运行
- **V51-012 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：候选 run 结束后填入实际摘要并开 docs PR / fill real receipts after the candidate run and open the docs PR
- **V51-013 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：rc.52 绿并合并 #67/#70/#71/#74 进 dev 后，用一次带 #75 的完整候选运行验证设备操作阶段，再双语合并 #75。
- **V51-014 · 进行中**；负责人：deepseek-v51-20261118-01；阻塞：无；下一步：本机语法与 Linux 契约复跑后，随下一次完整候选在 Windows 安装态产出 native-product-legacy-import.json；用户本人旧档案迁移留待目标机。

## 最近一次同步

rc.60（run 44474401536 @ 3c9d6f6）38 项通过后失败于 native-program-take 的 pixels-program-after-take-captured（Frozen final pixels on slot 1），NSIS 安装被跳过，逐轨增益修复未到达 Windows 断言。先核清旧证据不能归因的原因：SerialWatch 读的 product-state.json 只按 2000 ms 心跳发布，inputs[].maxStallMs（2250）与 renderFramesMaxStallMs 实为发布间隔，8 个采样 serial 完全相同（35/18/10/37/38）只说明读到同一快照，而 serial 只证明帧被交给 source、不证明 OBS 画出它。本轮在同一短窗口对齐三层且不放宽像素/帧断言（提交 a1af1b9）：OBS 补丁在 get_frame() 记录帧时间戳、内容摘要与 os_gettime_ns 到达毫秒，webobs_get_video_progress 升 schema 2；product_scene 接受 schema 1/2、拒绝 3；快照新增 frameTs/frameHash/frameAgeMs（-1=无遥测）；WEBOBS_PRODUCT_RENDER_PROBE=1 时宿主按 OBS 截图 helper 模式把预览 Scene 与 Program 通道画进 ≤960x540、每 slot ≤160 ms 的离屏纹理并按同一 3x2 网格发布逐格摘要环；SerialWatch 记录 publishedAtMs/发布次数/最大发布间隔，stallMs 改名 stallWindowMs，逐输入给出窗口内 distinct frameHash/frameTs；失败时按本次 order 反查相机输出 layerAttribution，并用 ffmpeg 解码该相机回环 4 秒逐帧摘要；OBS 日志新增有界标记 WebOBS async video backlog（async 队列 ≥30 整队丢弃且清掉 cur_async_frame）与 WebOBS async timestamp jump。修掉两处会在 MSVC 失败的写法：source->name→source->context.name、不存在的 os_time_msec()→os_gettime_ns()/1000000。本机 git apply --check 与 patch -p1 通过，容器内 -fsyntax-only 全绿，native-host Python 测试全绿。已按新基线 rebase 并推送 #70 d772808、#71 cd3dd2f、#74 42bc704、#75 705fa08、#76 937129b，并派发 rc.61（run 44524750280，soak_minutes=0）。按用户指示：不合并、不跑两小时长稳；TAKE、逐轨增益与完整 NSIS 须在同一轮通过才推进合并与冻结候选。探针开启的同机 CPU/GPU 窗口需在正式对比回执中披露，不当作 OBS 等价证据。

以任务中的验收条件决定完成；没有 Windows/硬件/发布证据时保持对应事项开放。
