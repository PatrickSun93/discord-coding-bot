const { spawn } = require('child_process');

function defaultErrorMessage(command, error) {
  if (error && error.code === 'ENOENT') {
    return `Command not found: ${command}`;
  }

  return error && error.message ? error.message : `Failed to start command: ${command}`;
}

function runCliBackend({ command, args, cwd, onChunk, onBeforeRun, formatStartError, formatExitError }) {
  return new Promise((resolve, reject) => {
    try {
      if (onBeforeRun) onBeforeRun();
    } catch (error) {
      reject(error);
      return;
    }

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

    child.on('error', (error) => {
      const message = formatStartError
        ? formatStartError({ command, args, cwd, error })
        : defaultErrorMessage(command, error);
      reject(new Error(message));
    });

    child.on('close', (code) => {
      if (code === 0) {
        return resolve(stdout.trim() || '(empty output)');
      }

      const message = formatExitError
        ? formatExitError({ command, args, cwd, code, stdout, stderr })
        : (stderr.trim() || stdout.trim() || `Process exited with code ${code}`);
      reject(new Error(message));
    });
  });
}

module.exports = { runCliBackend };
