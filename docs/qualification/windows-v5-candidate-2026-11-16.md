# v5.0 完整候选资格回执（进行中）

状态：完整候选构建/安装门禁运行中，未冻结、未发布。
Status: complete candidate build/install gates are running; not frozen or published.

## 固定身份

- 源码：`codex/v5-integration` 最终 head（以下运行回执写入后更新）。
- 版本：`5.0.0-rc.1`。
- v4.5：`v4.5@24fd012` 与 Release 附件不改。
- 稳定 feed：关闭；候选只能以 prerelease 交付。

## 已执行的本机检查

| 检查 | 结果 |
| --- | --- |
| core CTest（W1 分支） | 9/9 |
| `product_http_runtime.py` 双模式 | PASS，含 Program 回执 |
| `pnpm typecheck` / `pnpm build` | PASS |
| complete supervisor / legacy migration / native updater / release policy / update manifest | PASS |
| go2rtc runtime / events / cluster | 6/6、8/8、42/42 |

## Windows 完整候选

- Run: 待填。
- 安装包/`latest.yml`/SHA-256/SHA-512/size: 待填。
- 便携产品 UI/像素、完整业务服务、NSIS 安装、同机 rc 覆盖升级、卸载保留：待填。
- 失败阶段与修复：Windows 路径断言、`std::string::isEmpty`、迁移测试 SQLite 句柄已修复后重跑。

## 未通过/未测项

- 目标机真实五路、旧数据本人档案、物理多屏/DPI/音频设备、逐路硬解、OBS 同条件三对六轮性能。
- LAN/Caddy 远端、MediaMTX 合成输出、检测 provider、OBS 录制/推流业务输出。
- 公共更新 feed 的实际 rc→rc 下载安装；本候选可验证检查/校验逻辑，但 feed 绑定在发布流程中完成。
- 未签名安装包。

## 证据更新规则

只有 Windows run 成功、安装包与 `latest.yml` 字节核验一致、Release 匿名下载核验通过后，才把状态改为“完整候选，待目标机最终验收”；在目标机通过前不得称 v5.0 稳定版或性能达标。
