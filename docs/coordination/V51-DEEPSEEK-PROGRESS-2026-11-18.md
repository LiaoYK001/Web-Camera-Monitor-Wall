# v5.1 接续进度与缺口 · DeepSeek 会话 2026-11-18

Agent ID：`deepseek-v51-20261118-01`。统一账本：仓库根 `python3 scripts/agent-sync.py …`（本文件写作时 revision 152）。
本文件是会话接续说明，不替代生成的 `STATUS/TASKS/HANDOFF/ROADMAP/LOG` 视图，也不改变任何发布授权：稳定 feed 仍未开放，Android/容器仍暂停，v4.5 与 v5.0.0-rc.1 附件保持不可变。

## 1. 当前分支、PR 与 CI（全部为实际状态）

| 分支 / 工作树 | HEAD | PR | 实际状态 |
| --- | --- | --- | --- |
| `codex/v51-r2-003`（`.worktrees/v51-audio`） | `98e1e99` | #66 base `dev` | rc.25 run [44236342016](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44236342016)：step 13 实际产品窗口流程与 step 14 预认证恢复隔离 **success**；NSIS 安装验收、更新元数据、上传、体积预算步骤仍在执行 |
| `codex/v51-r3-output`（`.worktrees/v51`） | `ae4fce7` | #67 base `codex/v51-r2-003` | rc.26 run [44240683072](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/44240683072) 进行中：Direct-only 复原、节目音轨输出、总线对照、录像/推流解码、托盘/备份/支持包 |
| `codex/v51-release-identity`（`.worktrees/v51-release`） | `f176fba` | #68 base `dev` | 稳定身份与 Tag 映射；`test_stable_release_identity.py` PASS、`test_build_contract.py` 44/44；PR 检查多数 SUCCESS，尚未合并 |
| `codex/v51-publish-chain`（`.worktrees/v51-publish`） | `a0a6ae6` | #69 base `dev`（**Draft**） | 候选发布 Tag 统一 + `--final` 验收与 `main` 可达性 + `stage.py`/`update_manifest.py` 稳定模式；本机发布链测试 6 项 PASS；依赖 #67（提供 `publish_candidate.py`）与 #68 |
| `codex/v51-r4-backup-consistency`（`.worktrees/v51-backup`） | `56e25e7` | #70 base `codex/v51-r3-output` | 双目录恢复成对交换 + 中断收敛 + 更新器错误码；本机 `tests/test_encrypted_backup.py` 10 tests OK、`test_native_updater.py` PASS；CI 仍在跑 |

内部构建编号已用到 rc.26；下一个未占用编号 **rc.27**。

## 2. 本轮已完成并有证据的工作

1. **多轨 Program 音频（R2-003）**：完整运行态来源 ID `fixture-alt.fixture-alt-source` 精确匹配；等待拆成「TAKE 已生效 / 指定混音源出现 / 该源非静音信号」三段并写 `programAudioFailure`；夹具与回环 RTSP 双轨用可区分音调（440/880 Hz）解码比对；`mixers==2`、`volume 0.75`、TAKE 前无混音源、清场与注销后释放混音进程。rc.25 的实际 Windows 产品流程与恢复隔离步骤已通过（见上表）。
2. **Program 输出与节目音轨（R3-002 输出部分）**：`ProductSceneGraph::audio_output_tracks()` 读取实际混音掩码，`ProductProgramOutput::start_recording/start_streaming(error, audio_tracks)` 按轨创建 AAC（每轨一个 encoder，ordinal 递增）、WHIP 取最低有效轨；无节目音频只录视频。此前以零基 mixer `0` 创建 encoder 会导致「电平有信号、录像静音」的缺陷已修正。该部分证据依赖 rc.26 回执，尚未记为通过。
3. **webobsd 回到 Direct-only**：`WEBOBS_COMPOSITE_ENABLED=false`，消除 rc.24 的 `RuntimeError: control exited during startup`；Composite 代理仍未接入真实运行态，属于 R3-004 未完成项。
4. **v5.1 稳定发布身份**：`release_policy.tag_for_version()`（`5.1.0 → v5.1`、补丁三位、`-rc.N` 保留、dev 无 Tag）、`STABLE_PROFILE`、`configure_stable()`、`read_acceptance()`/`apply_acceptance()` 单一验收契约；`docs/release-flow.md` 新增 §4.1、`docs/versioning-and-branches.md` 新增 Tag 映射小节与 v4.5/v5.0.0-rc.1/v5.1 行。
5. **候选/正式发布脚本接线**：`publish_candidate.py` 不再拼 `"v"+version`；`--final` 需要仓库外验收 JSON（绑定 version/repository/sourceRevision、四项验收为 true、有界回执）并通过 `compare/<sha>...main` 只接受 `ahead/identical`；候选继续 `--prerelease` 且不声明稳定通道。
6. **双目录加密备份一致性**：有界恢复日志（原子写、`0600`、≤4096 字节）+ `recover_interrupted()` 依文件系统事实收敛为「旧的成对」或「新的成对」，失败路径清理暂存与日志，回滚目录名加随机后缀，含 `webobs-native-profile` 的存档必须成对恢复；更新器新增两个有界错误码映射。

## 3. 明确未完成或未实测（不得写成通过）

- rc.25 的 NSIS 安装验收、候选更新元数据、上传与体积预算步骤结果待读；rc.26 全部结果待读。
- 逐轨静音/增益/偏移的正反对照、录像只读目录/空间不足/停止失败/进程中断、WHIP 断线与端口冲突：尚未做产物级正反对照。
- R2-002 场景编辑/嵌套、R2-004 投影位置恢复、R3-001 设备操作、R3-002 NVR/回放/证据与 Program 录像可播、R3-003 事件/检测/网站源、R3-004 远端/离线/诊断（Composite 代理仍缺真实运行态接入）、R4-001/002 真实档案迁移与生命周期 Windows 实测：均未实现或未验收。
- R5-001 两小时长稳与安装体积增量、RTX 4090 同机 OBS 对照：需要目标机或 Windows 长跑，未开始。
- 物理多屏/DPI/睡眠唤醒、真实相机、签名更新、正式 Tag/Release、稳定 feed：均未验证；本轮不发布任何附件。

## 4. 下一条动作（按顺序）

```bash
# 1) 读 rc.25 剩余步骤与回执
gh run view 44236342016 --repo LiaoYK001/Web-Camera-Monitor-Wall --json status,conclusion,jobs \
  --jq '.status,.conclusion,(.jobs[0].steps[]|[.name,.status,.conclusion]|@tsv)'
gh run view 44236342016 --repo LiaoYK001/Web-Camera-Monitor-Wall --log-failed   # 若有失败

# 2) rc.25 全绿后把 #66 合入 dev（中英双语合并信息），再把 #67 改基到 dev
gh pr merge 66 --repo LiaoYK001/Web-Camera-Monitor-Wall --merge \
  --subject "merge: 合入v5.1多轨音频门禁 / merge v5.1 multi-track audio gates" \
  --body-file <双语说明>
gh pr edit 67 --repo LiaoYK001/Web-Camera-Monitor-Wall --base dev

# 3) 读 rc.26；通过后合入 #67，随后 rebase #69 与 #70 到 dev
gh run view 44240683072 --repo LiaoYK001/Web-Camera-Monitor-Wall --json status,conclusion,jobs

# 4) 冻结候选：同一 SHA 的完整回执 + 安装包摘要/latest.yml/安装记录，交给用户集中验收
cd /home/czl/projects/monitor_wall_czl && python3 scripts/agent-sync.py check && git diff --check
```

合并顺序：#66 → #68 → #67 → #70 → #69（#69 需要 #67 的 `publish_candidate.py` 与 #68 的 `tag_for_version`，合入前 rebase）。
