const { splitMessage } = require('./utils');

class DiscordReplyStreamer {
  constructor(message, options = {}) {
    this.message = message;
    this.prefix = options.prefix || '';
    this.updateIntervalMs = options.updateIntervalMs || 1200;
    this.messages = [];
    this.buffer = '';
    this.statusSuffix = '';
    this.flushTimer = null;
    this.flushing = Promise.resolve();
  }

  append(chunk) {
    if (!chunk) return;
    this.buffer += chunk;
    this.scheduleFlush();
  }

  scheduleFlush() {
    if (this.flushTimer) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      this.flush().catch((err) => {
        console.error('Failed to stream Discord reply:', err);
      });
    }, this.updateIntervalMs);
  }

  async flushNow() {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    await this.flush();
  }

  async finalize(finalText) {
    if (typeof finalText === 'string') {
      this.buffer = finalText;
    }
    this.statusSuffix = '';
    await this.flushNow();
  }

  async fail(errorMessage) {
    const trimmedError = (errorMessage || 'Unknown backend error').trim();
    this.statusSuffix = this.buffer.trim()
      ? `\n\n---\n⚠️ Partial output above. Backend error: ${trimmedError}`
      : `\n\n⚠️ Backend error: ${trimmedError}`;
    await this.flushNow();
  }

  async flush() {
    this.flushing = this.flushing.then(() => this.syncMessages());
    return this.flushing;
  }

  async syncMessages() {
    const body = this.buffer || '(no output yet)';
    const content = `${this.prefix}${body}${this.statusSuffix}`;
    const chunks = splitMessage(content);

    for (let i = 0; i < chunks.length; i += 1) {
      if (this.messages[i]) {
        if (this.messages[i].content !== chunks[i]) {
          this.messages[i] = await this.messages[i].edit(chunks[i]);
        }
      } else if (i === 0) {
        this.messages[i] = await this.message.reply(chunks[i]);
      } else {
        this.messages[i] = await this.message.channel.send(chunks[i]);
      }
    }

    for (let i = this.messages.length - 1; i >= chunks.length; i -= 1) {
      await this.messages[i].delete().catch(() => {});
      this.messages.pop();
    }
  }
}

module.exports = { DiscordReplyStreamer };
