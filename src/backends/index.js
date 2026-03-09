const { callGemini } = require('./gemini');
const { callCodex } = require('./codex');

async function callBackend({ backend, prompt, cwd }) {
  if (backend === 'gemini') return callGemini(prompt, cwd);
  if (backend === 'codex') return callCodex(prompt, cwd);
  throw new Error(`Unsupported backend: ${backend}`);
}

module.exports = { callBackend };
