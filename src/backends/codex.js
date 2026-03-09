const { spawn } = require('child_process');
const { codexCmd } = require('../config/env');

function callCodex(prompt, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(codexCmd, [prompt], {
      cwd,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (d) => (stdout += d.toString()));
    child.stderr.on('data', (d) => (stderr += d.toString()));
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) return resolve(stdout.trim() || '(empty output)');
      reject(new Error(stderr.trim() || `Codex exited with code ${code}`));
    });
  });
}

module.exports = { callCodex };
