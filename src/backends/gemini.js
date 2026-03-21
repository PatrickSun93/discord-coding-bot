const { geminiCmd } = require('../config/env');
const { runCliBackend } = require('./cli');

function callGemini(prompt, cwd, options = {}) {
  return runCliBackend({
    command: geminiCmd,
    args: ['-p', prompt],
    cwd,
    onChunk: options.onChunk,
  });
}

module.exports = { callGemini };
