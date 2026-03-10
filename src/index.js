const fs = require('fs');
const path = require('path');
const {
  Client,
  GatewayIntentBits,
  Events,
  Partials,
} = require('discord.js');
const env = require('./config/env');
const { userCwds, userBackends, enqueueForUser } = require('./core/state');
const { DiscordReplyStreamer } = require('./core/discordStreamer');
const { callBackend } = require('./backends');

if (!env.discordToken) {
  console.error('Missing DISCORD_BOT_TOKEN in environment');
  process.exit(1);
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.DirectMessages,
  ],
  partials: [Partials.Channel, Partials.Message],
});

client.once(Events.ClientReady, (c) => {
  console.log(`Logged in as ${c.user.tag}`);
  console.log(`Default backend: ${env.defaultBackend}`);
  console.log(`Default workdir: ${env.defaultWorkdir}`);
});

function getCurrentCwd(userId) {
  return userCwds.get(userId) || env.defaultWorkdir;
}

function getCurrentBackend(userId) {
  return userBackends.get(userId) || env.defaultBackend;
}

client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot) return;

  const isDM = !message.guild;
  const isMentioned = !isDM && message.mentions.has(client.user, { ignoreEveryone: true });
  const isAllowedChannel = !isDM && env.allowedChannels && env.allowedChannels.includes(message.channel.id);
  if (!isDM && !isMentioned && !isAllowedChannel) return;

  let userMessage = message.content.trim();
  if (isMentioned) userMessage = userMessage.replace(/<@!?\d+>/g, '').trim();

  if (!userMessage) {
    await message.reply('You mentioned me but gave no task.');
    return;
  }

  if (userMessage === '!help') {
    await message.reply([
      '**Commands**',
      '`!backend` - show current backend',
      '`!backend codex` - switch to codex backend',
      '`!backend gemini` - switch to gemini backend',
      '`!pwd` - show working directory',
      '`!cd <path>` - change working directory',
      '`!help` - show help',
      '',
      'Everything else is sent to the current backend.'
    ].join('\n'));
    return;
  }

  if (userMessage === '!backend') {
    await message.reply(`Current backend: \`${getCurrentBackend(message.author.id)}\``);
    return;
  }

  if (userMessage.startsWith('!backend ')) {
    const backend = userMessage.slice('!backend '.length).trim();
    if (!['codex', 'gemini'].includes(backend)) {
      await message.reply('Supported backends: `codex`, `gemini`');
      return;
    }
    userBackends.set(message.author.id, backend);
    await message.reply(`Backend set to: \`${backend}\``);
    return;
  }

  if (userMessage === '!pwd') {
    await message.reply(`Current working directory: \`${getCurrentCwd(message.author.id)}\``);
    return;
  }

  if (userMessage.startsWith('!cd ')) {
    const dir = userMessage.slice(4).trim();
    const resolved = path.resolve(dir);
    if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
      await message.reply(`Directory not found: \`${resolved}\``);
      return;
    }
    userCwds.set(message.author.id, resolved);
    await message.reply(`Working directory set to: \`${resolved}\``);
    return;
  }

  enqueueForUser(message.author.id, async () => {
    const cwd = getCurrentCwd(message.author.id);
    const backend = getCurrentBackend(message.author.id);
    const streamer = new DiscordReplyStreamer(message, {
      prefix: `Running on backend \`${backend}\` in \`${cwd}\` ...\n\n`,
    });

    try {
      const output = await callBackend({
        backend,
        prompt: userMessage,
        cwd,
        onChunk: (chunk) => streamer.append(chunk),
      });
      await streamer.finalize(output);
    } catch (err) {
      await streamer.flushNow().catch(() => {});
      await message.reply(`Backend error: ${err.message}`);
    }
  });
});

client.login(env.discordToken);
