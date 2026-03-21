const fs = require('fs');
const path = require('path');
const { codexCmd, codexArgs } = require('../config/env');
const { runCliBackend } = require('./cli');

function findGitRoot(startDir) {
  let currentDir = path.resolve(startDir);

  while (true) {
    if (fs.existsSync(path.join(currentDir, '.git'))) {
      return currentDir;
    }

    const parentDir = path.dirname(currentDir);
    if (parentDir === currentDir) {
      return null;
    }

    currentDir = parentDir;
  }
}

function buildCodexArgs(prompt) {
  return [...codexArgs, prompt];
}

function formatCodexStartError({ command, cwd, error }) {
  if (error && error.code === 'ENOENT') {
    return `Codex CLI not found: ${command}. Set CODEX_CMD to the installed codex binary.`;
  }

  return `Failed to start Codex in ${cwd}: ${error.message}`;
}

function formatCodexExitError({ cwd, code, stdout, stderr }) {
  const details = stderr.trim() || stdout.trim() || `Codex exited with code ${code}`;
  return `Codex failed in ${cwd}: ${details}`;
}

function callCodex(prompt, cwd, options = {}) {
  return runCliBackend({
    command: codexCmd,
    args: buildCodexArgs(prompt),
    cwd,
    onChunk: options.onChunk,
    onBeforeRun: () => {
      const gitRoot = findGitRoot(cwd);
      if (!gitRoot) {
        throw new Error(
          `Codex backend requires a git repository. Current directory is not inside a repo: ${cwd}`,
        );
      }
    },
    formatStartError: formatCodexStartError,
    formatExitError: formatCodexExitError,
  });
}

module.exports = { callCodex };
