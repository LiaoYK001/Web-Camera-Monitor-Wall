# Contributing / 贡献指南

感谢为 Web Camera Monitor Wall 做出贡献。功能开发请以 `dev` 为目标分支；`main` 用于稳定版本集成。分支与发布规则见 [版本和分支策略](docs/versioning-and-branches.md)，本地启动方式见 [开发指南](docs/development.md)。

Thank you for contributing to Web Camera Monitor Wall. Target `dev` for feature work; `main` is the stable release branch. See the [version and branch policy](docs/versioning-and-branches.md) and [development guide](docs/development.md).

## 提交信息 / Commit messages

**每条人工编写的 commit 标题必须同时包含中文和 English，且两种语言要表达同一项改动。**推荐格式：

**Every human-written commit subject must contain both Chinese and English, describing the same change.** Use this format:

```text
<type>(<scope>): <中文摘要> / <English summary>
```

`type` 可用 `feat`、`fix`、`refactor`、`docs`、`test`、`chore`；`scope` 用受影响的模块名。标题应说明具体改动。若需要正文，请分别用 `中文：` 和 `English:` 解释原因、影响和验证结果。合并或 squash 时，最终 commit 标题也要符合双语要求。

Use a relevant type such as `feat`, `fix`, `refactor`, `docs`, `test`, or `chore`, and name the affected module as the scope. State the concrete change. When a body is needed, use separate `中文：` and `English:` paragraphs for the reason, impact, and verification. The final commit created by a merge or squash must also be bilingual.

```text
fix(dev-lan): 修复局域网视频播放 / Fix LAN video playback

中文：为远端浏览器提供可达的 WebRTC 媒体入口，并验证本机与局域网端口。
English: Expose a reachable WebRTC media endpoint for remote browsers and verify local and LAN ports.
```

## PR 与发布描述 / PR and release descriptions

**PR 标题、PR 描述和人工编写的发布描述也必须同时提供中文与 English。**两种语言应包含相同的关键信息，尤其是改动内容、测试结果、已知限制和需要审查的风险。不要仅把标题翻译成双语而让正文只保留一种语言。

**PR titles, PR descriptions, and human-written release descriptions must also be bilingual.** Cover the same key facts in both languages: changes, test results, known limitations, and review risks. A bilingual title alone is not enough when the description has only one language.

可按下面的简短结构撰写 PR 描述 / A concise PR description can use this structure:

```markdown
## 中文
- 改动：……
- 验证：……（未运行的测试请明确说明）
- 限制与风险：……

## English
- Changes: ...
- Verification: ... (state which tests were not run)
- Limitations and risks: ...
```

## 提交前 / Before submitting

- 运行与改动相关的测试并检查 `git diff --check`；如实记录没有运行或无法验证的项目。 / Run relevant tests and `git diff --check`; state any checks that were not run or could not be verified.
- 不提交账号密码、令牌、真实摄像机地址、录像或私有测试产物。 / Do not commit passwords, tokens, real camera endpoints, recordings, or private test artifacts.
- 文档或接口行为发生变化时，同步更新对应说明；不要把尚未验证的功能写成已通过验收。 / Update affected documentation when behavior or APIs change, and do not present unverified behavior as accepted.
