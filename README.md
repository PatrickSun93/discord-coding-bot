# Discord Coding Bot

A fresh Discord bot scaffold for routing messages to coding backends like **Codex** and **Gemini CLI**.

## Current status

This is a clean-start scaffold.

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

- This scaffold is intentionally simple.
- Backend invocation is abstracted under `src/backends/`.
- Next steps should be:
  - proper streaming output
  - session persistence
  - backend-specific argument handling
  - better Codex CLI integration
  - Claude Code adapter if needed
