# v5.0.0-rc.1 独立核查 / Independent review

日期：2026-11-17，Asia/Shanghai。任务AUDIT-001，Agent `codex-rc1-review-20261117`。用户要求核查另一Agent的交付报告；本轮不修改产品代码、安装/本人数据、公开Release、Tag或更新feed。

## 结论

**发行与主要回执属实，原生Program和业务接入有实际进展；“完整融合候选、只剩最终目标机验收”不符合既定完整产品完成条件。** 尚有明确未接线能力，以及本轮可重复复现的迁移/更新缺陷。应继续开发并出修复候选，不能把这些问题全部归为用户目标机待验。

## 1. 本轮独立核验的事实

- [公开Release](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/releases/tag/v5.0.0-rc.1)，ID447675294，prerelease=true、draft=false，13附件；Latest API返回v4.0。
- [Windows run43956468003](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/actions/runs/43956468003) success，head=`8828532c60648f52fae9bee222fa41b80beee7ab`。OBS/Qt编译、控制/服务暂存、实际入口、恢复I/O、实际NSIS、候选元数据步骤均成功。
- [PR63](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/63) MERGED，merge1ade2c5；[PR64](https://github.com/LiaoYK001/Web-Camera-Monitor-Wall/pull/64) MERGED，merge2258a37。
- **本轮独立匿名完整下载安装器并计算摘要**：212,117,618B，SHA-256 `3d16014dab7700e6bc4f73c5c0bfba5700382c78fb3f24041589b58a4e67016c`，SHA-512/base64 `GQaVEz2p2j6dvD4JT/sD/YtkjKIZ0VtTsA6n3hI2PorrdZS2+/xRDKzwh/JmRqMFCtw9yApJzJwoYL70LYfItA==`。与GitHub资产digest、verification和latest.yml一致。下载文件未运行。
- 下载11/13附件（安装器、feed、清单/来源/SBOM、SHA256SUMS及四类回执），逐个核对GitHub资产size/SHA256一致；未声称下载了其余2附件。
- 实际读取便携/安装回执：各passed=true、52 checks、35 captures，source都为8828532。恢复passed=true、9 checks；NSISpassed=true，setup摘要和安装footprint与用户报告一致：794,551,075 logical / 806,587,720 allocation B，6,972files。
- 回执同时明确`hardwareDecodeVerified=false`、`fullFeatureMigrationQualified=false`。不能把检查项数量等价于全功能资格。
- 审查代码树 `/home/czl/projects/monitor_wall_czl/.worktrees/v5-w2`，`codex/v5-release-evidence@93870f2`，干净。相对8828532仅4份文档差异，运行时代码相同。另两个共享工作树原有改动均保留。

## 2. P1：v4.5工作区迁移读取和写入路径均不匹配实际产品

位置：`native-host/scripts/migrate_legacy.py:89–107,173–175,208–210`；对照`product_supervisor.py:484`、外置frontend补丁和`product_window.cpp:917`。

原生UI用`obs_module_config_path("workspace-<userId>.json")`，实际保存目录是：

```text
NativePreview/native-profile/obs-studio/plugin_config/webobs-native-host/workspace-<id>.json
```

迁移器却只`iterdir()`扫描`NativePreview/native-profile`的第一层，无法发现真实工作区；同时把扫描到的测试工作区放进staging/native-profile，最终移到`Native/config/native-profile`。新宿主从`Native/native-profile`下的OBS插件配置读取，不会使用该目标。

本轮临时目录复现：按真实嵌套路径创建schema2工作区和合成accounts数据库，调用`migrate(... include_preview_workspaces=True)`，**返回status=migrated、previewWorkspacesCopied=0，目标工作区数量0**；旧文件仍存在。用户导入显示成功但布局/选择不会恢复。

现有测试把夹具放到错误的第一层，并断言错误目标目录，所以测试绿色未捕获缺陷。修复需要按真实模块配置路径搬迁、核验账号绑定与两个profile根目录边界，并通过新宿主实际登录后恢复；不能只改测试预期或要求用户重新手填。

## 3. P1：缓存安装包在执行前没有重验size/SHA-512

位置：`native-host/scripts/native_updater.py:224–255`。

当`update-receipt.json`与缓存EXE同时存在时，`install()`只比较回执里的version/sha512和manifest字符串，之后直接执行缓存EXE。没有重新核对文件本身的大小/摘要。之前下载通过校验后发生损坏或替换的缓存仍能走到执行点。

本轮隔离复现：预期8194B的合成包与正确回执，缓存文件替换成15B `CORRUPTED-CACHE`；调用install(confirm=True)，**仍到达安装命令，返回installed**。执行器、停机探测和备份均用mock隔离，**没有执行任何EXE**。仅证明产品安装决策会放行错误字节，不声称在Windows上运行过损坏文件。

修复需在实际执行前对最终缓存文件重新计算size/SHA-512，拒绝不匹配并可恢复重下；回执不是文件完整性证据。覆盖“已成功下载→缓存变动→再次安装”的负向集成流程。不要把需要用户确认误认为已经保证字节正确。

## 4. P2：预发布版本比较使用字符串排序

位置：`native-host/scripts/native_updater.py:45–53`。

实际调用结果：

```text
is_newer('5.0.0-rc.2',  '5.0.0-rc.10') = False
is_newer('5.0.0-rc.10', '5.0.0-rc.2')  = True
```

会漏掉较新的rc.10，或将rc.2当成更新。按数字标识和预发布顺序比较，保留正式版本优先于同基线预发布的语义；补rc.9/10、多段与同版/回退测试。

## 5. “rc.1→rc.2覆盖升级通过”的准确范围

`desktop/scripts/test-native-product-install.ps1:112–141`确实生成并执行了另一个NSIS安装器，也检查注册表版本与profile指纹。**这个安装器复用同一`$runtime`作为payload，只改NSIS的VERSION参数，并直接Start-Process；没有走native_updater的check/download/install链。**

因此可证明“覆盖安装与数据字节保留”，不能证明：

- 真实新版本payload/manifest/OBS或组件ABI升级后的启动；
- 产品快捷方式检查更新、确认、摘要校验、下载、备份、执行和失败恢复的端到端闭环；
- 旧稳定版→新原生的数据与身份迁移。

该事实不否定NSIS已执行，但对完整升级链的结论必须收窄。尤其不能用这项测试排除上述缓存校验缺陷。

## 6. 仍需Agent开发/自动化的项目，不应推给目标机

当前功能矩阵仍明确写：

- AUDIO：非空逐轨、音频UI/电平与输出混音未完成。
- OUTPUT：原生合成录像/推流未接线。
- REMOTE、OFFLINE：原生远端输出适配与离线状态映射未接线。
- OVERLAY：原生叠层来源和数据连接未接线；OPS：支持包与完整故障入口仍未完成。
- STUDIO：完整嵌套编辑、复杂冲突等仍开放；生命周期：托盘/后台长任务与完整消费者仍待补齐。

这些包含实质代码/接线工作，不是“有真实4090才能知道”。迁移/更新缺陷、截断/断网/备份恢复、合成媒体两小时长稳也可由Agent/Windows CI继续完成。此次Windows run从构建到完成约55分钟，不能据其success声称已做两小时长稳。

真正集中留给用户的是本人旧档案、真实相机/音频/PTZ设备、物理多屏/DPI、4090逐路解码及OBS同机成本。最终验收应基于功能已完成的冻结候选。

## 7. 性能、体积与来源准备

- 安装logical约794.6MB（757.7MiB），allocation约806.6MB；setup约212.1MB。相对旧大包有改善，但不是与159MB OBS同口径的≤证明；完整CPU/GPU/内存性能也未提供同机对照。
- footprint主要组：bin431,197,520B，python/Lib149,112,582B，bin/64bit82,991,616B；最大文件包括AVCodec118.9MB、Node92.8MB、MediaMTX53.9MB、Caddy49.5MB、另一OBS AVCodec37.9MB。原生媒体和可选工具运行时版本不同，不能仅按同名DLL盲删；应做实际可选组件/依赖去重并保持离线完整可用。
- 完整services/components在包内，不代表其所有UI流程或外部站点实播通过。yt-dlp/Streamlink自检不是外部网站媒体播放证明；NVR原码流录制不是OBS合成输出证明。
- source-manifest明确`reviewed=false`，自述不是已复审对应源码包；13附件没有完整第三方对应源码归档。正式发行前仍要按项目要求补全匹配源码、依赖/许可证与SBOM复审，不能以来源URL清单替代。

## 8. 本轮执行与建议顺序

本轮实际执行：公开GitHubAPI/PR/run查询；匿名资产下载和hash核验；候选源码静态对照；现有`test_migrate_legacy.py`与`test_native_updater.py`通过；上述临时目录反例全部复现。没有Windows交互桌面，本轮没有重跑NSIS、真实相机或目标机性能。

临时证据目录由`/tmp/webobs-rc1-review-path`记录，包含下载回执、`independent-installer-hash.json`和`independent-reproductions.json`；不是永久交付依赖，关键结果已在本文脱敏保存。

下一开发顺序：先修迁移路径与安装前校验/版本比较 → 做真实新payload的更新与数据迁移回归 → 补R2/R3明确未接线功能和后台任务 → Agent承担故障/两小时合成长稳 → 发布新的完整候选 → 最后集中目标机验收。保留既有rc.1不可变身份，不覆盖其字节或以修改报告代替修复。

English: the public assets, hashes and scoped Windows receipts are genuine. The complete-product claim remains premature: preview workspace migration misses the actual plugin path, cached installers are executed without rehashing, prerelease versions compare lexically, and the upgrade gate repackages the same payload rather than exercising the updater end to end. Continue implementation and automated regression before final field acceptance.
