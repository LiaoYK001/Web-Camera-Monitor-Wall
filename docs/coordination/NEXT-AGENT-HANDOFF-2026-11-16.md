# 下一位 Agent 接手续作 / Next agent handoff

> **已被2026-11-16晚间交接替代。** 请改读[V5-CURRENT-HANDOFF-2026-11-16.md](V5-CURRENT-HANDOFF-2026-11-16.md)和[完整成品任务书](V5-FULL-RELEASE-AGENT-TASKBOOK-2026-11-16.md)。本页以下“R1无人占用、分支仍为v5-integration”等是较早快照，现在R1-001已有负责人、PR58尚未合并，不能照旧认领。

2026-11-16。用户要求换 Agent 继续开发；本文件用于交接，不启动新开发或发布。

## 用户最新反馈与决定

- 用户刚确认：**“v4.5 测试下来可以，性能占用不错了。”** 将其保留为真实用户的正向可用性/性能定性反馈，继续现有 OBS 原生路线。
- 本轮没有 CPU/GPU/内存数值、流分辨率/帧率、OBS 同条件基线或逐路 NVDEC 记录；不要把反馈扩大为已证明 ≤ OBS、独显硬解或完整 v5 验收。既定目标机为 i9-13900HX / RTX4090 Laptop；最新反馈未重新列出配置。
- 后续**完整版本从 v5.0 开始**。v4.5 是已发布原生监看预览，保留既有 Tag/附件/独立数据，不改写旧发布。完整融合、旧数据保留、原生更新及性能目标继续开放。
- Agent 自行承担中间开发、联调和回归，用户集中测试最终完整候选。当前仍只推进 Windows x64；Android/容器等暂停交付不因 v5 编号自动恢复。

## 两个 checkout 的职责——先核对，避免从旧代码继续

| 位置 | 当前身份与用途 |
| --- | --- |
| `/home/czl/projects/monitor_wall_czl` | **唯一共享账本入口**；分支 `codex/windows-native-monitor`、源码基线 `24fd012`。有既有协作工具/文档未提交修改，必须保留，勿 reset/clean/stash、切分支或夹带提交。这里的旧源码不能冒充最新 v5。 |
| `/home/czl/projects/monitor_wall_v5` | **最新实际代码工作树**；`codex/windows-v5-integration`，干净，HEAD `e8e60e2b0d27e6ab0ac1d070e7cfa5cfcb9a53a5`，已合入 `origin/dev` 的 PR #57。 |

v5 本地分支相对 `origin/codex/windows-v5-integration` 可能显示 ahead1：只是已快进到 dev 的合并提交 e8e60e2，该提交已经在 origin/dev，**不是未推送功能**。新 Agent 必须重新 fetch/检查实际状态，不把此快照当实时远端状态。可在干净 v5 工作树基于 origin/dev 开自己的 `codex/*` 分支；勿切换有未提交协作工作的主 checkout。

统一账本原登记23项，开发后已补充版本、具体权限/布局和本次交接任务；任务数不是产品完成百分比。STATUS/TASKS/ROADMAP/DEVLOG/HANDOFF 由 state.json 生成，不能分别手改。实际更新使用主 checkout 的脚本和 `--root`，而不是在 v5 工作树另造一份账本。

## 已完成及证据

### v4.5 已发布，勿重复发布

- [Release v4.5](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v4.5)：prerelease，15附件，源码 `24fd012ea8ee130ffb9d42473c489d708c9326c3`。
- 最终 [Windows run43783406841](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43783406841)：便携/实际安装各40项，恢复9项，安装卸载保留数据通过。不要误用此前失败的43744978600作为最终状态。
- 安装 EXE70249426字节；安装逻辑200614374字节。早先本会话已校验15附件服务器摘要与匿名安装包下载。Latest 保持v4.0，未进入稳定 updater feed。
- PRE-003/PRE-004 已在账本关闭；现在又获得用户上述实机正向反馈，但不等于完整版本或量化性能目标完成。

### v5 开发代码已合入 dev

[PR #57](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/57) 已合并，dev提交 e8e60e2；没有发布 v5.0。本轮还查询到合并后 Web runtime public CI `43823811195` 已 completed/success、head=e8e60e2；这是常规回归，不把它说成重新构建了安装包。

1. **R2-005 已关闭**：原生快捷监看由写死5路改为有界1–64格，默认5格和旧五路布局兼容；共享一个目录模型；修改路数只改草稿，应用时重新授权/比较相机版本；交集输入复用；按账号保存并认证后恢复。Windows实际验证1/4/7格；64仅为接口/网格及真实libobs inert引用边界，不是64个真实解码器/摄像机证明。完整R2-001/002等未关闭。
2. **R1-002 已关闭**：普通配置目录的 device.manage gate 由“仅预览flag”改为所有原生宿主模式。viewer仍走scoped native目录。实际HTTP先在旧core复现非预览放行，再在新core验证内部/预览403、native有权目录与非原生旧路径200兼容。完整R1-001未关闭。
3. 本机：Qt6.11.2头/GCC16语法；API CTest8/8；44构建契约；像素24项（2个平台跳过）；真实固定libobs inert图1→7→64→1保持一输入且释放平衡；双模式真实HTTP；公开源码审计均通过。inert不是媒体/硬解资格。
4. 最终 [Windows run43816563388](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43816563388)：内部 `5.0.0-dev.1`，**43便携 / 43真实安装 / 9恢复**，NSIS Unicode/快捷方式/卸载保留通过。内部模式没有v4.5预览专属目录项，不误写成44。
5. **真正构建验证的源码是429155676834047d5be5b3fbc1b900abf660f831**；后续38f99b5只增加/更新3份docs，dev合并后运行时代码仍相同。不能把文档合并SHA冒充重新构建的安装器源码。
6. 内部安装器 publicationForbidden=true、fullFeatureMigrationQualified=false；不得拿它公开发布或上稳定源。

可长期定位的产品证据（在v5工作树/已合入dev）：

- `docs/qualification/windows-v5-quick-wall-2026-11-16.json`：源码、运行、检查项、原始回执SHA256及范围。
- `docs/windows-native-feature-parity.md`：24项功能矩阵与本轮证据。
- `docs/release-notes-v5.0.md`：**开发草案，非完整发布说明**。
- 原始临时回执：`/tmp/webobs-v5-dev1-receipts`；日志 `/tmp/webobs-v5-*.log` 只是辅助，不依赖其永久存在，也不复制私密完整日志进Git。

主要改动文件：`native-host/src/product_window.cpp`、`layout.hpp`；`core/src/control_server.cpp`；`native-host/tests/product_http_runtime.py`、`product_windows.py`、`product-ui.ps1`、`pixel-pattern.cjs`、`layout_test.cpp`、`product_scene_libobs_test.cpp` 与CMake测试注册。

## 下一步从 R1-001 认领，不重新做 v4.5

本会话结束时没有正在占用的开发任务。下一位使用**新的客户端/会话唯一 Agent ID**，不要复用本会话ID：

```bash
cd /home/czl/projects/monitor_wall_v5
git status --short --branch
git fetch origin dev
# 先读主checkout的AGENTS/STATUS/TASKS/HANDOFF/DECISIONS/PLAYBOOK。
# 将下列Agent ID换成本客户端唯一值，再认领：
python3 /home/czl/projects/monitor_wall_czl/scripts/agent-sync.py \
  --root /home/czl/projects/monitor_wall_czl claim R1-001 \
  --agent next-v5-REPLACE-WITH-UNIQUE-SESSION-ID \
  --note '从v5工作树接手全入口认证与执行审计；已核对共享账本和实际源码'
```

下一实质工作是全入口认证/恢复/执行审计，再进入真实Studio/TAKE：

- 盘点原生菜单、来源编辑、自动恢复、键盘快捷键、普通HTTP/WebSocket与输出入口，继承现有userId/authEpoch/撤权/在途请求修复，新增实际回归。
- 已只读定位关键缺口：`ObsSceneRuntime::prepare` 在 Direct-only 下只记 `disabled_prepared`；`StudioController::take` 仍经 `program_.replace` 改控制文档；`product_window.cpp` 目前主要设置本地Studio Preview，Program保持独立空图。**不能把旧控制API的成功或新增TAKE按钮当成原生Program已切换。**
- 完整接线需要把文档revision、身份/相机版本前置条件、宿主线程执行与成功回执/失败恢复串起来；现有未接线apply/authorization库也不等于执行栅栏。继续单一OBS媒体所有者，不在core启动第二套libobs。
- R2后续还有完整编辑/嵌套/多轨声音/Program投影；R3业务/NVR/事件/设备控制/远端；R4旧数据迁移/原生updater；R5完整成本与同机OBS对照。不能仅因旧WebUI页面或Python文件存在就标“已回接”。
- 模型/ORT当前仍在包内：v4.5模型+ORT约55.2MB，未实现真实按需安装前须全部计入；不能靠丢功能或要求用户另备服务器减包。

## 验证与发行约束

原生产品开发构建可沿现有内部Windows流程，下一候选建议递增为 `5.0.0-dev.2`，`native_host=true`、`product_mode=true`、`native_preview=false`。旧工程门禁名 `v4-M1-dev` 仍是现有管线参数，不代表把完整版本退回v4；不要无依据全局替换历史版本。中间回归由Agent跑，不要求用户逐包试。

本地现成构建在v5工作树 `build/native-api`、`build/core`，引用主checkout的固定OBS源码/`build/native-perf-obs`。先检查CMakeCache再复用。可运行 `ctest --test-dir build/native-api --output-on-failure`、实际libobs目标及双模式HTTP；媒体/安装资格仍要同源码Windows，源支持不等于目标机资格。

日常只进dev，双语提交/PR；main只走指定完整版本的审核发布PR。OBS/go2rtc上游checkout不实现产品改动。保持loopback、私密配置、正常退出和进程所有权；不记录真实摄像机URL/密码。原生更新器需重做确认安装、摘要/size、正常停机与备份恢复，不能假定electron-updater仍在。

## 交接完成标准

先认领再编辑，测试/阻塞/交接更新同一state；结束时运行共享脚本 `check` 与相关 `git diff --check`。不要自动提交主checkout现存的协作改动。用户的正向反馈作为继续原生路线的依据，完整v5与 ≤ OBS 的最终量化目标仍待完成。

English: use the clean v5 worktree at dev e8e60e2, the shared ledger in monitor_wall_czl, and a fresh unique agent ID. Claim R1-001, preserve the dirty coordination checkout, continue real native Studio/authentication integration, and retain explicit CI versus physical-device boundaries. v4.5 has positive user feedback; it is not a quantitative OBS-parity or complete-v5 qualification.
