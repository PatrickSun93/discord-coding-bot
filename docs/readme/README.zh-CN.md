# Discord Coding Bot

> 语言： [English](../../README.md) | **简体中文** | [Español](README.es.md)

一个用于将 Discord 消息路由到 **Codex** 和 **Gemini CLI** 等编码后端的机器人脚手架。

## 当前状态

这是一个带有渐进式 Discord 输出的简洁脚手架。

支持的后端切换：
- `codex`
- `gemini`

## 命令

- `!help`
- `!backend`
- `!backend codex`
- `!backend gemini`
- `!pwd`
- `!cd <path>`

所有非命令消息都会被转发到当前选定的后端。

## 配置

1. 复制环境变量文件：

```bash
cp .env.example .env
```

2. 填写以下配置：
- `DISCORD_BOT_TOKEN`
- 可选的 `DISCORD_CHANNEL_ID`
- `DEFAULT_BACKEND`
- `DEFAULT_WORKDIR`
- `CODEX_CMD`
- 可选的 `CODEX_ARGS`（默认值为 `exec --full-auto`）
- `GEMINI_CMD`

3. 安装依赖：

```bash
npm install
```

4. 运行：

```bash
npm start
```

## 说明

- 后端调用逻辑被抽象在 `src/backends/` 下。
- 渐进式 Discord 输出基于共享 CLI 流式逻辑和节流后的消息编辑实现。
- 长输出会在需要时拆分成多条 Discord 消息。
- 当前流式能力基于 stdout 分块输出，不是 token 级流式。
- 最终看起来是否“真的在流式输出”，取决于后端 CLI 如何输出 stdout。如果后端只在最后一次性输出，用户看到的仍然会接近最终一次性回复。
- Codex 默认使用 `codex exec --full-auto <prompt>`，适合非交互式调用。
- Codex 在启动前会检查当前工作目录是否位于 git 仓库内，因为 Codex 通常依赖受信任的仓库上下文。

## 多语言文档

- 根目录下的 `README.md` 是主版本。
- 翻译文件放在 `docs/readme/` 目录中。
- 当行为发生变化时，先更新英文 README，再同步翻译内容。

## 后续可做

- 后端特定参数处理
- 会话持久化
- 更好的 Codex CLI 集成
- 如有需要，增加 Claude Code 适配器
- 可选的 stderr / 状态流输出
