const { spawn } = require('child_process');

function runCliBackend({ command, args, cwd, onChunk }) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (data) => {
      const chunk = data.toString();
      stdout += chunk;
      if (onChunk) onChunk(chunk);
    });

    child.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) {
        return resolve(stdout.trim() || '(empty output)');
      }

      reject(new Error(stderr.trim() || `Process exited with code ${code}`));
    });
  });
}

module.exports = { runCliBackend };
