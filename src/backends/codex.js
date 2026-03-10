const { codexCmd } = require('../config/env');
const { runCliBackend } = require('./cli');

function callCodex(prompt, cwd, options = {}) {
  return runCliBackend({
    command: codexCmd,
    args: [prompt],
    cwd,
    onChunk: options.onChunk,
  });
}

module.exports = { callCodex };
