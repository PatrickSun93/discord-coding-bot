require('dotenv').config();

module.exports = {
  discordToken: process.env.DISCORD_BOT_TOKEN,
  allowedChannels: process.env.DISCORD_CHANNEL_ID
    ? process.env.DISCORD_CHANNEL_ID.split(',').map((x) => x.trim()).filter(Boolean)
    : null,
  defaultBackend: process.env.DEFAULT_BACKEND || 'gemini',
  defaultWorkdir: process.env.DEFAULT_WORKDIR || process.cwd(),
  codexCmd: process.env.CODEX_CMD || 'codex',
  geminiCmd: process.env.GEMINI_CMD || 'gemini',
};
