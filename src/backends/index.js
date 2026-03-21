const { callGemini } = require('./gemini');
const { callCodex } = require('./codex');

async function callBackend({ backend, prompt, cwd, onChunk }) {
  const options = { onChunk };

  if (backend === 'gemini') return callGemini(prompt, cwd, options);
  if (backend === 'codex') return callCodex(prompt, cwd, options);
  throw new Error(`Unsupported backend: ${backend}`);
}

module.exports = { callBackend };
