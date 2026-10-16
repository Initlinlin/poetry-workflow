# 诗歌自动化 Skill · poetry-workflow

将诗歌网站中的「完整阅读 → 意象与语言分析 → 创作蓝图 → 原创/融合 → 修订 → Markdown 存档」整理为可复用的 AI 助手 Skill。

这是独立 Skill 仓库，可直接上传 GitHub。它不包含网页前端、服务器账号、个人诗集或模型密钥。分析与创作由加载本 Skill 的 AI 助手执行；Python 辅助脚本不调用模型，也不会自动假造阅读结果。

## 安装到 Codex

将本仓库复制或克隆到 Codex 的技能目录，目录名保留 `poetry-workflow`：

```bash
git clone <你自己的GitHub仓库URL> ~/.codex/skills/poetry-workflow
```

Windows 用户复制到用户目录下的 `.codex/skills/poetry-workflow/`。不要覆盖已有同名 Skill；新会话或重新加载后使用。

## 使用

```text
请使用 $poetry-workflow 完整阅读我选择的这些诗歌，
提炼它们的语言和思维方式，围绕“城市夜归”写一首原创融合诗，
约 25—40 行，把作品和阅读记录存到我指定的 Markdown 诗库。
```

也支持单诗赏析、从意象原创、原稿修订、诗歌标题建议、古典体裁检查及 Markdown 诗库整理。单诗任务无需强制批量流程。

需要文件输入时提供实际路径和输出目录；原网站浏览器中的内容不会自动读取或同步。用户资料保存在独立工作目录，不放进 Skill 仓库。

## 文件与自动化

- `SKILL.md`：助手的工作流入口。
- `agents/openai.yaml`：Codex 展示与调用信息。
- `scripts/poetry_workflow.py`：全量读取、无损分块、阅读登记、覆盖校验、另存作品与阅读记录。
- `scripts/book_extract.py`：TXT、MD、EPUB、DOCX、文字版 PDF 的本地文本提取。
- `references/`：创作方法、提取边界、诗库存档约定。
- `tests/`：合成资料测试，不含用户作品。

Python 3.9+；TXT、MD、EPUB、DOCX 不需要第三方依赖。PDF 可在所用环境中安装可选依赖 `pypdf`。扫描 PDF 需要另行 OCR；提取的局限会明确提示，不声称图片被完整阅读。

查看命令与运行测试：

```bash
python3 scripts/poetry_workflow.py --help
python3 -m unittest discover -s tests -v
```

`prepare` 生成 `manifest.json`、全部提取快照和片段；助手真实阅读并逐块 `record`，完成后写 `blueprint.md`，通过 `check` 后再 `save`。分块完整性不等于语义质量，应同时检查实际阅读笔记和最终作品。

## 上传 GitHub

只上传本目录，不上传诗歌网站整个项目。已附 `.gitignore` 和 GitHub Actions 检查；运行记录、诗库、导出文件、环境配置及服务器资料均不属于发布内容。

在 GitHub 创建空仓库后，可从本目录初始化并推送；仓库地址由你决定。Skill 包生成不代表已经创建或推送 GitHub 仓库。
