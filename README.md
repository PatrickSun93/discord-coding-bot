# Discord Coding Bot

A fresh Discord bot scaffold for routing messages to coding backends like **Codex** and **Gemini CLI**.

## Current status

This is a clean-start scaffold with progressive Discord streaming.

Supported backend switches:
- `codex`
- `gemini`

## Commands

- `!help`
- `!backend`
- `!backend codex`
- `!backend gemini`
- `!pwd`
- `!cd <path>`

Any non-command message is forwarded to the selected backend.

## Setup

1. Copy env file:

```bash
cp .env.example .env
```

2. Fill in:
- `DISCORD_BOT_TOKEN`
- optional `DISCORD_CHANNEL_ID`
- `DEFAULT_BACKEND`
- `DEFAULT_WORKDIR`
- `CODEX_CMD`
- optional `CODEX_ARGS` (defaults to `exec --full-auto`)
- `GEMINI_CMD`

3. Install:

```bash
npm install
```

4. Run:

```bash
npm start
```

## Notes

- Backend invocation is abstracted under `src/backends/`.
- Progressive Discord output is driven by shared CLI streaming logic and throttled message edits.
- Long responses are split across multiple Discord messages when needed.
- Current streaming is stdout-chunk based, not token streaming.
- Whether output feels truly streamed depends on how the backend CLI emits stdout. If a backend only emits a final response, the user will still only see a final answer.
- Codex now defaults to `codex exec --full-auto <prompt>` for a more practical non-interactive invocation.
- Codex also checks that the selected working directory is inside a git repository before launching, because Codex commonly expects a trusted repo context.

## Next sensible steps

- backend-specific argument handling
- session persistence
- better Codex CLI integration
- Claude Code adapter if needed
- optional stderr/status streaming
