require('dotenv').config();

function parseArgList(value, fallback) {
  const source = value && value.trim() ? value.trim() : fallback;
  return source.split(/\s+/).filter(Boolean);
}

module.exports = {
  discordToken: process.env.DISCORD_BOT_TOKEN,
  allowedChannels: process.env.DISCORD_CHANNEL_ID
    ? process.env.DISCORD_CHANNEL_ID.split(',').map((x) => x.trim()).filter(Boolean)
    : null,
  defaultBackend: process.env.DEFAULT_BACKEND || 'gemini',
  defaultWorkdir: process.env.DEFAULT_WORKDIR || process.cwd(),
  codexCmd: process.env.CODEX_CMD || 'codex',
  codexArgs: parseArgList(process.env.CODEX_ARGS, 'exec --full-auto'),
  geminiCmd: process.env.GEMINI_CMD || 'gemini',
};
