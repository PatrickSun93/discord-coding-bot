# DevBot — AI Development Assistant

## Final Architecture Document v4.3

---

## 1. Overview

**DevBot** is a cross-platform AI development assistant accessed via messaging platforms. You talk to it in Discord (or Telegram, Slack, MS Teams — see Section 21); it codes, reviews, tests, runs commands, and manages projects on your local machine.

### Core Capabilities

| # | Capability | Description |
|---|-----------|-------------|
| 1 | **Chat** | Answer questions, explain errors, discuss approaches via MiniMax / Ollama |
| 2 | **CLI Agents** | Dispatch coding tasks to Claude Code, Codex, Gemini CLI, or Qwen CLI |
| 3 | **Shell Execution** | Run commands on the host (bash/zsh/WSL/PowerShell) with a safety blocklist |
| 4 | **Todo Queue** | Process prioritized task lists — parallel across CLIs |
| 5 | **Review Pipeline** | Code → Review → Fix loop → Test → Push → PR (fully automatic) |
| 6 | **Project Management** | Scaffolding, dev containers, context file auto-refresh, project registry |
| 7 | **Harness Engineering** | Structured knowledge base, linter enforcement, doc gardening, execution plans |
| 8 | **Shared Skills** | Reusable SKILL.md instructions shared across all CLIs |
| 9 | **Usage Management** | Rate limit detection, session pause/resume, usage tracking + reports |

```
You (Discord / Telegram / Slack / Teams)
  │
  ▼
Message Provider (abstract interface)
  │
  ▼
DevBot Core (Python)
  │
  ├──► MiniMax / Ollama (Router LLM) ──► decides action
  │
  ├──► CLI Agents (parallel, one task per CLI)
  │      ├── Claude Code    (-p --dangerously-skip-permissions --output-format stream-json)
  │      ├── Codex          (exec --full-auto --json)
  │      ├── Gemini CLI     (-p --yolo --output-format stream-json)
  │      └── Qwen CLI       (-p --yolo --output-format stream-json)
  │
  ├──► Shell Executor (bash / zsh / WSL / PowerShell)
  │      ├── Command blocklist (rm, dd, mkfs, chmod 777, shutdown...)
  │      └── OpenClaw management (start/stop/restart/status via WSL)
  │
  ├──► Review Pipeline
  │      branch → code → commit → review → fix loop → test → push → PR
  │
  ├──► Todo Queue
  │      todos.md → parse → validate → parallel dispatch → done.md
  │
  └──► Project Manager
         scaffolding → devcontainer → git init → /init → context refresh
```

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Simpler, good async, cross-platform |
| LLM Router | MiniMax (OpenAI-compat) + Ollama fallback | Cost-effective, offline fallback |
| Ad-hoc concurrency | Single task | Safer for one-off commands |
| Todo/Pipeline concurrency | Parallel across CLIs (1 per CLI) | Maximize throughput |
| Cross-platform | Windows (WSL+native) / macOS / Linux | Auto-detect, allow override |
| Auth | Single-user (owner ID) | Full trust, open-source ready |
| CLI permissions | All fully autonomous | `--dangerously-skip-permissions` / `--yolo` / `--full-auto` |
| Shell safety | Blocklist dangerous commands | Block rm/dd/mkfs/chmod 777/shutdown |
| Project env | Docker dev containers | Consistent across all OS |
| Context freshness | Auto-refresh CLAUDE.md if >7 days | Keep project understanding current |

---

## 2. CLI Communication

### 2.1 CLI Capability Matrix

| Feature | Claude Code | Codex | Gemini CLI | Qwen CLI |
|---------|-------------|-------|------------|----------|
| Non-interactive | `-p` / `--print` | `exec` subcommand | `-p` / `--prompt` | `-p` (headless) |
| Auto-approve | `--dangerously-skip-permissions` | `--full-auto` | `--yolo` / `-y` | `--yolo` / `-y` |
| Stream JSON | `--output-format stream-json` | `--json` (NDJSON) | `--output-format stream-json` | `--output-format stream-json` |
| Plain text | `--output-format text` | default (stderr=progress, stdout=final) | default with `-p` | default with `-p` |
| JSON blob | `--output-format json` | *(use --json)* | `--output-format json` | `--output-format json` |
| Session resume | `--resume <id>` | `exec resume --last` | `--resume <id>` | `--resume <id>` |
| Max turns | `--max-turns N` | *(not documented)* | *(not documented)* | *(not documented)* |
| Context file | `CLAUDE.md` (auto) | `AGENTS.md` (auto) | `GEMINI.md` (auto) | project files |
| Install | `npm i -g @anthropic-ai/claude-code` | `npm i -g @openai/codex` | `npm i -g @google/gemini-cli` | `npm i -g @qwen-code/qwen-code` |

### 2.2 Full Commands

```bash
# Claude Code — coder role
claude -p "task" --dangerously-skip-permissions --output-format stream-json

# Codex — coder role
codex exec --full-auto --json "task"

# Gemini CLI — reviewer/tester role
gemini -p "task" --yolo --output-format stream-json

# Qwen CLI — reviewer role
qwen -p "task" --yolo --output-format stream-json
```

### 2.3 Stream-JSON Parser

All CLIs emit NDJSON. DevBot uses a unified parser:

```python
async def read_cli_stream(process, reporter):
    """Universal stream-json reader for all CLIs."""
    async for raw_line in process.stdout:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            await reporter.on_text(line)  # plain text fallback
            continue

        etype = event.get("type", "")
        if etype == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "text":
                    await reporter.on_text(block["text"])
        elif etype == "tool_use":
            await reporter.on_tool_use(event.get("name"), event.get("input", {}))
        elif etype == "result":
            await reporter.on_complete(
                success=(event.get("subtype") == "success"),
                result=event.get("result", ""),
                duration_ms=event.get("duration_ms", 0),
            )
```

### 2.4 Adapter Configuration

```yaml
cli:
  claude_code:
    command: "claude"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--dangerously-skip-permissions"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["coder"]

  codex:
    command: "codex"
    base_args: ["exec", "--json"]
    autonomy_args: ["--full-auto"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["coder"]

  gemini_cli:
    command: "gemini"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--yolo"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["reviewer", "tester"]

  qwen_cli:
    command: "qwen"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--yolo"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["reviewer"]
```

Command assembly: `[command] + base_args + autonomy_args + extra_args + [task_message]`

---

## 3. Shell Execution

### 3.1 Platform Detection

| OS | Default Shell | Fallback | WSL |
|----|---------------|----------|-----|
| Windows | WSL bash | PowerShell → cmd | Auto via `shutil.which("wsl")` |
| macOS | zsh | bash | N/A |
| Linux | bash | zsh | N/A |

Override: `"run in powershell: ..."`, `"run in bash: ..."`, `"run in wsl: ..."`

WSL path auto-conversion: `C:\Users\me\project` → `/mnt/c/Users/me/project`

### 3.2 Command Safety Blocklist

DevBot refuses to execute commands matching these patterns. The router LLM is also instructed to never generate them.

```python
BLOCKED_COMMANDS = [
    # File/directory deletion
    r"\brm\b",             # rm, rm -rf, rm -r
    r"\brmdir\b",
    r"\bunlink\b",
    r"\bshred\b",

    # Disk formatting / raw writes
    r"\bmkfs\b",           # mkfs, mkfs.ext4, etc.
    r"\bdd\b",             # dd if=/dev/zero ...
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bformat\b",         # Windows format

    # Dangerous permission changes
    r"chmod\s+777",        # chmod 777
    r"chmod\s+-R",         # recursive chmod
    r"chown\s+-R",         # recursive chown

    # System shutdown/reboot
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\binit\s+0\b",
    r"\binit\s+6\b",

    # Fork bombs / dangerous redirects
    r":\(\)\{",            # :(){ :|:& };:
    r">\s*/dev/sd",        # writing to raw devices
    r">\s*/dev/null.*2>&1.*&",  # background + suppress all output (suspicious)
]

def is_command_blocked(command: str) -> tuple[bool, str | None]:
    """Check if a command matches the blocklist. Returns (blocked, reason)."""
    for pattern in BLOCKED_COMMANDS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, f"Blocked pattern: {pattern}"
    return False, None
```

When a blocked command is detected:

```
You: "clean up old logs with rm -rf /var/log/old/*"
DevBot: 🚫 **Command blocked** — `rm` is on the safety blocklist.
        This protects against accidental destructive operations.
        If you really need this, run it manually in your terminal.
```

### 3.3 OpenClaw Management

OpenClaw runs in WSL. DevBot manages it via shell commands:

```yaml
# In config — registered as a "service" that DevBot knows about
services:
  openclaw:
    shell: "wsl"
    commands:
      start: "cd ~/openclaw && npm start"
      stop: "cd ~/openclaw && npm stop"
      restart: "cd ~/openclaw && npm restart"
      status: "cd ~/openclaw && npm run status"
      logs: "cd ~/openclaw && tail -50 logs/openclaw.log"
```

```
You: "restart openclaw"
LLM: → run_shell(command="cd ~/openclaw && npm restart", shell="wsl")
DevBot: 🔧 Running in WSL: cd ~/openclaw && npm restart
DevBot: ✅ OpenClaw restarted
```

---

## 4. Review Pipeline

### 4.1 Overview

The review pipeline is a fully automatic multi-agent workflow with harness engineering integration:

```
┌──────────────────────────────────────────────────────────────┐
│                    REVIEW PIPELINE                             │
│                                                                │
│  0. PLAN       (complex tasks) generate execution plan         │
│       │        check into docs/plans/, coder follows it        │
│                                                                │
│  1. BRANCH     git checkout -b feature/<llm-generated-name>   │
│       │                                                        │
│  2. CODE       coder CLI (claude/codex) implements task        │
│       │        reads AGENTS.md → follows pointers to docs/     │
│                                                                │
│  3. LINT       run project linters + structural tests          │
│       │        if violations → feed errors to coder, loop      │
│                                                                │
│  4. COMMIT     git add -A && git commit -m "<message>"         │
│       │                                                        │
│  5. REVIEW     reviewer CLI(s) review git diff against main    │
│       │        output: APPROVED or CHANGES_REQUESTED           │
│                                                                │
│  6. DECISION   parse structured verdict                        │
│       ├── APPROVED → go to step 7                              │
│       └── CHANGES_REQUESTED → feed back to coder (step 2)     │
│           └── max 10 cycles, then stop                         │
│                                                                │
│  7. TEST       shell runs test command (npm test / pytest)     │
│       │        reviewer CLI interprets any failures            │
│       ├── PASS → go to step 8                                  │
│       └── FAIL → feed failures to coder (step 2), loop        │
│                                                                │
│  8. PUSH       git push origin feature/<name>                  │
│       │                                                        │
│  9. PR         gh pr create --title "..." --body "..."         │
│                LLM auto-generates title + description          │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Pipeline Configuration

```yaml
# In project config or global config
pipeline:
  coder: "claude_code"                # or "codex" — which CLI writes code
  reviewers: ["gemini_cli"]           # list — 1 or 2 reviewers
  tester: "gemini_cli"                # who interprets test failures
  test_command: "npm test"            # shell command to run tests
  lint_command: "npm run lint"         # linter/structural tests (run before review)
  max_cycles: 10                      # max review+fix cycles before stopping
  auto_pr: true                       # create PR via gh CLI
  pr_tool: "gh"                       # GitHub CLI
  base_branch: "main"                 # branch to diff against
  plan_threshold: "complex"            # "always", "complex", or "never" — when to generate execution plans
```

Per-project override in `.devbot.yaml`:

```yaml
pipeline:
  coder: "codex"
  reviewers: ["gemini_cli", "qwen_cli"]  # two reviewers
  test_command: "pytest -v"
  lint_command: "ruff check . && mypy ."  # multiple linters chained
  base_branch: "develop"
  plan_threshold: "always"                # always generate a plan first
```

### 4.3 Pipeline Executor

```python
class ReviewPipeline:
    def __init__(self, config, project_path, task, channel):
        self.config = config
        self.project = project_path
        self.task = task
        self.channel = channel
        self.cycle = 0
        self.branch_name = None

    async def run(self):
        """Execute the full pipeline."""

        # Step 1: Create feature branch
        self.branch_name = await self._create_branch()
        await self.channel.send(
            f"🌿 Created branch: `{self.branch_name}`"
        )

        while self.cycle < self.config.pipeline.max_cycles:
            self.cycle += 1
            await self.channel.send(
                f"🔄 **Cycle {self.cycle}/{self.config.pipeline.max_cycles}**"
            )

            # Step 2: Code
            feedback = self._get_feedback() if self.cycle > 1 else None
            await self._run_coder(feedback)

            # Step 3: Commit
            await self._commit()

            # Step 4: Review
            verdict = await self._run_review()

            # Step 5: Decision
            if verdict == "CHANGES_REQUESTED":
                await self.channel.send("📝 Changes requested — looping back to coder")
                continue

            # Step 6: Test
            test_passed = await self._run_tests()
            if not test_passed:
                await self.channel.send("🧪 Tests failed — looping back to coder")
                continue

            # Step 7 + 8: Push + PR
            await self._push_and_pr()
            await self.channel.send(
                f"✅ Pipeline complete! PR created on `{self.branch_name}`"
            )
            return True

        # Exhausted cycles
        await self.channel.send(
            f"⚠️ Stopped after {self.config.pipeline.max_cycles} cycles. "
            f"Branch `{self.branch_name}` has partial work."
        )
        return False

    async def _create_branch(self) -> str:
        """LLM generates branch name, then create it via shell."""
        # Ask router LLM to generate a branch name
        name = await llm_router.generate_branch_name(self.task)
        # Sanitize: lowercase, hyphens, no special chars
        slug = re.sub(r'[^a-z0-9-]', '-', name.lower())[:50]
        branch = f"feature/{slug}"

        await shell_exec(f"git checkout -b {branch}", cwd=self.project)
        return branch

    async def _run_coder(self, feedback: str | None):
        """Run the coder CLI (Claude Code or Codex)."""
        coder = self.config.pipeline.coder
        prompt = self.task
        if feedback:
            prompt = (
                f"Previous review feedback:\n{feedback}\n\n"
                f"Original task:\n{self.task}\n\n"
                f"Fix the issues raised in the review."
            )

        await self.channel.send(f"💻 [{coder}] Coding...")
        adapter = get_adapter(coder)
        process = await adapter.spawn(prompt, self.project)
        reporter = DiscordReporter(self.channel, prefix=f"[{coder}]")
        await read_cli_stream(process, reporter)
        await process.wait()

    async def _commit(self):
        """Stage and commit all changes."""
        await shell_exec("git add -A", cwd=self.project)
        msg = f"devbot: cycle {self.cycle} — {self.task[:50]}"
        await shell_exec(f'git commit -m "{msg}" --allow-empty', cwd=self.project)

    async def _run_review(self) -> str:
        """Run reviewer CLI(s) and get structured verdict."""
        diff = await shell_exec(
            f"git diff {self.config.pipeline.base_branch}",
            cwd=self.project, capture=True,
        )

        verdicts = []
        for reviewer_name in self.config.pipeline.reviewers:
            await self.channel.send(f"🔍 [{reviewer_name}] Reviewing...")

            prompt = (
                f"Review the following code changes. "
                f"You MUST end your response with exactly one of these verdicts "
                f"on its own line:\n"
                f"VERDICT: APPROVED\n"
                f"VERDICT: CHANGES_REQUESTED\n\n"
                f"If you request changes, list specific issues to fix.\n\n"
                f"Task: {self.task}\n\n"
                f"Diff:\n```\n{diff[:15000]}\n```"
            )

            adapter = get_adapter(reviewer_name)
            process = await adapter.spawn(prompt, self.project)
            reporter = DiscordReporter(self.channel, prefix=f"[{reviewer_name}]")
            output = await read_cli_stream_capture(process, reporter)
            await process.wait()

            # Parse verdict from output
            verdict = self._parse_verdict(output)
            verdicts.append(verdict)
            await self.channel.send(
                f"📋 [{reviewer_name}] Verdict: **{verdict}**"
            )

            if verdict == "CHANGES_REQUESTED":
                self._last_feedback = output
                return "CHANGES_REQUESTED"

        # All reviewers approved
        return "APPROVED"

    def _parse_verdict(self, output: str) -> str:
        """Extract APPROVED or CHANGES_REQUESTED from reviewer output."""
        for line in reversed(output.splitlines()):
            line = line.strip().upper()
            if "VERDICT:" in line:
                if "APPROVED" in line:
                    return "APPROVED"
                elif "CHANGES_REQUESTED" in line:
                    return "CHANGES_REQUESTED"
        # Default to changes requested if no clear verdict
        return "CHANGES_REQUESTED"

    async def _run_tests(self) -> bool:
        """Run tests via shell, then have reviewer interpret failures."""
        test_cmd = self.config.pipeline.test_command
        await self.channel.send(f"🧪 Running: `{test_cmd}`")

        result = await shell_exec(test_cmd, cwd=self.project, capture=True)
        returncode = result.returncode

        if returncode == 0:
            await self.channel.send("🧪 ✅ Tests passed")
            return True

        # Tests failed — have reviewer interpret
        await self.channel.send("🧪 ❌ Tests failed — asking reviewer to interpret")
        tester = self.config.pipeline.tester
        prompt = (
            f"The following test output shows failures. "
            f"Analyze the failures and provide specific instructions "
            f"for the coder to fix them.\n\n"
            f"Test command: {test_cmd}\n"
            f"Exit code: {returncode}\n\n"
            f"Output:\n```\n{result.output[:10000]}\n```"
        )

        adapter = get_adapter(tester)
        process = await adapter.spawn(prompt, self.project)
        reporter = DiscordReporter(self.channel, prefix=f"[{tester}]")
        output = await read_cli_stream_capture(process, reporter)
        self._last_feedback = output
        return False

    async def _push_and_pr(self):
        """Push branch and create PR via gh CLI."""
        await shell_exec(
            f"git push origin {self.branch_name}",
            cwd=self.project,
        )
        await self.channel.send(f"📤 Pushed `{self.branch_name}`")

        # Generate PR title + body via LLM
        diff_summary = await shell_exec(
            f"git log {self.config.pipeline.base_branch}..HEAD --oneline",
            cwd=self.project, capture=True,
        )
        pr_info = await llm_router.generate_pr_description(
            task=self.task,
            diff_summary=diff_summary.output,
            cycles=self.cycle,
        )

        await shell_exec(
            f'gh pr create '
            f'--title "{pr_info.title}" '
            f'--body "{pr_info.body}" '
            f'--base {self.config.pipeline.base_branch}',
            cwd=self.project,
        )
        await self.channel.send(f"📬 PR created: **{pr_info.title}**")
```

### 4.4 Review Pipeline in Todo Format

Todo items can trigger the full pipeline:

```markdown
## Priority 1 — Critical
- [ ] `pipeline` | `myapp` | Add input validation to all API endpoints
- [ ] `pipeline` | `backend` | Fix the SQL injection vulnerability in search
```

When `cli` is `pipeline`, the todo executor runs the full review pipeline instead of a single CLI task.

### 4.5 Review Pipeline via Discord Message

```
You: "pipeline myapp: add rate limiting to the auth endpoints"
LLM: → run_pipeline(project="myapp", task="add rate limiting to the auth endpoints")
DevBot: 🌿 Created branch: feature/add-rate-limiting-auth-endpoints
DevBot: 🔄 Cycle 1/10
DevBot: 💻 [claude_code] Coding...
DevBot: 📤 [claude_code] (streaming output...)
DevBot: 🔍 [gemini_cli] Reviewing...
DevBot: 📋 [gemini_cli] Verdict: CHANGES_REQUESTED
DevBot: 📝 Changes requested — looping back to coder
DevBot: 🔄 Cycle 2/10
DevBot: 💻 [claude_code] Coding...
DevBot: 🔍 [gemini_cli] Reviewing...
DevBot: 📋 [gemini_cli] Verdict: APPROVED
DevBot: 🧪 Running: npm test
DevBot: 🧪 ✅ Tests passed
DevBot: 📤 Pushed feature/add-rate-limiting-auth-endpoints
DevBot: 📬 PR created: Add rate limiting to auth endpoints
DevBot: ✅ Pipeline complete!
```

---

## 5. Project Management

### 5.1 Project Registry

```yaml
projects:
  myapp:
    path: "/home/user/projects/myapp"
    context_files: ["claude.md", "AGENTS.md"]
    description: "Main web application"
    devcontainer: true                   # use devcontainer
    pipeline:                            # per-project pipeline overrides
      coder: "codex"
      reviewers: ["gemini_cli", "qwen_cli"]
      test_command: "pytest -v"
  frontend:
    path: "/home/user/projects/frontend"
    context_files: ["claude.md", "README.md"]
    description: "React frontend"
    devcontainer: true
    pipeline:
      test_command: "npm test"
```

### 5.2 Docker Dev Containers

Each project uses a `.devcontainer/` directory for consistent environments and a structured knowledge base for agent context:

```
project_root/
├── .devcontainer/
│   ├── devcontainer.json        # VS Code / DevBot dev container config
│   └── Dockerfile               # custom image if needed
├── .devbot.yaml                 # per-project DevBot overrides
│
├── AGENTS.md                    # ~100 lines — table of contents, NOT encyclopedia
├── CLAUDE.md                    # Claude Code context (auto-generated, auto-refreshed)
├── GEMINI.md                    # Gemini CLI context
│
├── docs/                        # ← STRUCTURED KNOWLEDGE BASE (harness engineering)
│   ├── architecture.md          # domain map, package layering, dependency rules
│   ├── conventions.md           # code style, naming, patterns
│   ├── quality.md               # quality grades per domain, known gaps
│   ├── api.md                   # API contracts, data shapes
│   ├── plans/                   # execution plans (versioned, checked in)
│   │   ├── active/
│   │   │   └── add-rate-limiting.md
│   │   └── completed/
│   │       └── fix-auth-bypass.md
│   └── debt.md                  # known technical debt tracker
│
└── src/
    └── ...
```

Standard `devcontainer.json`:

```json
{
  "name": "myapp",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
  "features": {
    "ghcr.io/devcontainers/features/node:1": { "version": "20" },
    "ghcr.io/devcontainers/features/python:1": { "version": "3.12" },
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  },
  "postCreateCommand": "npm install && pip install -r requirements.txt",
  "customizations": {
    "devbot": {
      "cli_overrides": {
        "claude_code": { "extra_args": ["--model", "sonnet"] }
      }
    }
  }
}
```

DevBot can run CLI agents **inside** the dev container when configured:

```python
class DevContainerRunner:
    """Run commands inside a project's dev container."""

    async def exec_in_container(self, project_path, command):
        container_name = self._get_container_name(project_path)
        # Check if container is running
        result = await shell_exec(
            f"docker ps --filter name={container_name} --format '{{{{.Names}}}}'",
            capture=True,
        )
        if not result.output.strip():
            # Start the container
            await shell_exec(
                f"docker compose -f {project_path}/.devcontainer/docker-compose.yml up -d",
            )

        # Execute inside container
        return await shell_exec(
            f"docker exec {container_name} {command}",
            capture=True,
        )
```

### 5.3 Project Initialization & Context Refresh

When a project is first registered or its `CLAUDE.md` is stale (>7 days), DevBot runs Claude Code `/init`:

```python
import os
from datetime import datetime, timedelta
from pathlib import Path

CONTEXT_MAX_AGE = timedelta(days=7)

CONTEXT_FILES_TO_CHECK = [
    "CLAUDE.md", "claude.md",
    "AGENTS.md", "GEMINI.md",
]

async def ensure_project_context(project_path: Path, config):
    """Check if project context files need refresh. Auto-run /init if stale."""

    claude_md = project_path / "CLAUDE.md"
    if not claude_md.exists():
        claude_md = project_path / "claude.md"

    needs_init = False

    if not claude_md.exists():
        needs_init = True
        reason = "CLAUDE.md does not exist"
    else:
        mod_time = datetime.fromtimestamp(claude_md.stat().st_mtime)
        age = datetime.now() - mod_time
        if age > CONTEXT_MAX_AGE:
            needs_init = True
            reason = f"CLAUDE.md is {age.days} days old (max: {CONTEXT_MAX_AGE.days})"

    if needs_init:
        logger.info(f"Project context refresh needed: {reason}")
        # Run claude /init to regenerate CLAUDE.md
        process = await asyncio.create_subprocess_exec(
            "claude", "-p",
            "Analyze this project and generate/update CLAUDE.md with: "
            "project overview, architecture, key files, conventions, "
            "and development workflow.",
            "--dangerously-skip-permissions",
            "--output-format", "text",
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.wait()
        return True

    return False
```

This runs:

- **On project registration** (first time)
- **On bot startup** (checks all projects)
- **Before any CLI task** (checks the target project)
- **Manually** via `!init <project>`

### 5.4 New Project Scaffolding

DevBot can create projects from scratch:

```
You: "create a new project called payment-api, it's a Python FastAPI service"
```

DevBot executes:

```python
async def scaffold_project(name: str, description: str, base_path: str):
    project_path = Path(base_path) / name

    # 1. Create directory
    project_path.mkdir(parents=True, exist_ok=True)

    # 2. Git init
    await shell_exec("git init", cwd=project_path)
    await shell_exec("git checkout -b main", cwd=project_path)

    # 3. Create devcontainer
    devcontainer_dir = project_path / ".devcontainer"
    devcontainer_dir.mkdir(exist_ok=True)
    # Write devcontainer.json based on project type (LLM decides)
    devcontainer_config = await llm_router.generate_devcontainer(description)
    (devcontainer_dir / "devcontainer.json").write_text(devcontainer_config)

    # 4. Create .devbot.yaml
    devbot_config = {
        "description": description,
        "pipeline": {
            "coder": "claude_code",
            "reviewers": ["gemini_cli"],
            "test_command": "pytest -v",  # LLM chooses based on description
        }
    }
    (project_path / ".devbot.yaml").write_text(yaml.dump(devbot_config))

    # 5. Run Claude Code /init to scaffold code + generate CLAUDE.md
    await run_cli("claude_code", f"Initialize this project: {description}. "
                  "Create the basic directory structure, config files, "
                  "and a README.md.", project_path)

    # 6. Initial commit
    await shell_exec("git add -A", cwd=project_path)
    await shell_exec(f'git commit -m "Initial scaffold: {name}"', cwd=project_path)

    # 7. Register in DevBot config
    await register_project(name, str(project_path), description)

    return project_path
```

### 5.5 Pre-Task Context Loading

Before any CLI runs on a project, DevBot:

1. **Checks context freshness** — refresh CLAUDE.md if >7 days
2. **Loads context files** — CLAUDE.md, AGENTS.md, GEMINI.md, README.md
3. **Passes context to the CLI** — either via the prompt or relying on the CLI's auto-loading (Claude reads CLAUDE.md, Gemini reads GEMINI.md, Codex reads AGENTS.md)

```python
CONTEXT_FILE_PRIORITY = [
    "CLAUDE.md", "claude.md",
    "AGENTS.md", "agents.md",
    "GEMINI.md",
    "CONVENTIONS.md",
    "README.md",
]

async def load_project_context(project_path: Path, config) -> str:
    """Load and concatenate project context files."""
    # First ensure context is fresh
    await ensure_project_context(project_path, config)

    # Check for per-project config override
    devbot_yaml = project_path / ".devbot.yaml"
    if devbot_yaml.exists():
        proj_config = yaml.safe_load(devbot_yaml.read_text())
        files_to_check = proj_config.get("context_files", CONTEXT_FILE_PRIORITY)
    else:
        files_to_check = CONTEXT_FILE_PRIORITY

    sections = []
    for filename in files_to_check:
        filepath = project_path / filename
        if filepath.is_file():
            content = filepath.read_text(encoding="utf-8", errors="replace")
            sections.append(f"# {filename}\n\n{content}")

    return "\n\n---\n\n".join(sections) if sections else "(No context files found)"
```

---

## 6. Todo Queue System

### 6.1 File Format (`~/.devbot/todos.md`)

```markdown
# DevBot Todo List

## Priority 1 — Critical
- [ ] `claude` | `myapp` | Fix the authentication bypass in src/auth/login.py
- [ ] `pipeline` | `myapp` | Add input validation to all API endpoints

## Priority 2 — High
- [ ] `codex` | `infra` | Refactor Terraform modules to use workspaces
- [ ] `qwen` | `frontend` | Add loading skeletons to data-fetching components

## Priority 3 — Normal
- [ ] `gemini` | `backend` | Generate OpenAPI documentation for all routes
- [ ] `pipeline` | `backend` | Add rate limiting to public endpoints
```

Item syntax: `- [ ] \`<cli|pipeline>\` | \`<project>\` | <task description>`

When `cli` is `pipeline`, the full review pipeline runs instead of a single CLI.

### 6.2 Execution Model

- **Auto-start on bot startup** + manual `!todo run`
- **Parallel across CLIs**: one task per CLI simultaneously
- **Priority ordering**: process all Priority 1 items before Priority 2
- **Busy-CLI**: ask user → `assign <cli>` / `hold` / `skip`
- **Pipeline items**: run the full review pipeline (occupies the coder CLI lock)
- **Pre-run validation**: check all CLIs installed, all projects exist
- **Archive**: completed items → `done.md` with metadata

### 6.3 Done Archive (`~/.devbot/done.md`)

```markdown
# DevBot — Completed Tasks

## 2026-03-20

- [x] `claude` | `myapp` | Fix the authentication bypass
  - **Status**: ✅ Success (exit 0)
  - **Duration**: 45s
  - **Completed**: 2026-03-20 14:23:07

- [x] `pipeline` | `myapp` | Add input validation to all API endpoints
  - **Status**: ✅ Pipeline complete (3 cycles)
  - **Duration**: 340s
  - **PR**: #42 — "Add comprehensive input validation"
  - **Completed**: 2026-03-20 14:30:15
```

---

## 7. Configuration (Complete)

### 7.1 Global Config (`~/.devbot/config.yaml`)

```yaml
# ── Messaging ────────────────────────────────────────
messaging:
  provider: "discord"                    # discord | telegram | slack | teams
  discord:
    token: "${DISCORD_BOT_TOKEN}"
    owner_id: "123456789012345678"
    channel_id: null                       # null = any channel

# ── LLM Router ───────────────────────────────────────
llm:
  primary:
    provider: "minimax"
    base_url: "https://api.minimaxi.chat/v1"
    api_key: "${MINIMAX_API_KEY}"
    model: "MiniMax-Text-01"
  fallback:
    provider: "ollama"
    base_url: "http://localhost:11434/v1"
    model: "qwen3.5:4b"

# ── CLI Agents ───────────────────────────────────────
cli:
  claude_code:
    command: "claude"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--dangerously-skip-permissions"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["coder"]

  codex:
    command: "codex"
    base_args: ["exec", "--json"]
    autonomy_args: ["--full-auto"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["coder"]

  gemini_cli:
    command: "gemini"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--yolo"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["reviewer", "tester"]

  qwen_cli:
    command: "qwen"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--yolo"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["reviewer"]

# ── Shell ────────────────────────────────────────────
shell:
  default: "auto"
  timeout: 300
  wsl_distro: null

# ── Services (managed via shell) ─────────────────────
services:
  openclaw:
    shell: "wsl"
    commands:
      start: "cd ~/openclaw && npm start"
      stop: "cd ~/openclaw && npm stop"
      restart: "cd ~/openclaw && npm restart"
      status: "cd ~/openclaw && npm run status"
      logs: "cd ~/openclaw && tail -50 logs/openclaw.log"

# ── Projects ─────────────────────────────────────────
projects:
  myapp:
    path: "/home/user/projects/myapp"
    context_files: ["claude.md", "AGENTS.md"]
    description: "Main web application"
    devcontainer: true
    pipeline:
      coder: "claude_code"
      reviewers: ["gemini_cli"]
      test_command: "npm test"
  infra:
    path: "/home/user/projects/infra"
    context_files: ["claude.md"]
    description: "Infrastructure repo"
    devcontainer: true

# ── Default Pipeline ─────────────────────────────────
pipeline:
  coder: "claude_code"
  reviewers: ["gemini_cli"]
  tester: "gemini_cli"
  test_command: "npm test"
  max_cycles: 10
  auto_pr: true
  pr_tool: "gh"
  base_branch: "main"

# ── Todo Queue ───────────────────────────────────────
todo:
  file: "~/.devbot/todos.md"
  done_file: "~/.devbot/done.md"
  auto_start: true
  busy_cli_timeout: 300

# ── Project Scaffolding ──────────────────────────────
scaffolding:
  base_path: "~/projects"             # where new projects are created
  default_devcontainer: true

# ── Context Refresh ──────────────────────────────────
context:
  max_age_days: 7                     # re-run /init if CLAUDE.md older than this

# ── Reporting ────────────────────────────────────────
reporter:
  stream_threshold: 30
  batch_interval: 15
  max_message_length: 1900
```

---

## 8. LLM Router — Tool Definitions

### 8.1 System Prompt (Dynamic)

```python
SYSTEM_PROMPT = f"""You are DevBot, a development assistant in Discord.

## Host Environment
- OS: {os_name}
- Default shell: {default_shell}
- Available shells: {available_shells}
- Installed CLIs: {installed_clis}
- Registered projects: {project_list}
- Services: {service_list}

## Actions

1. **Chat** — answer questions (no tool call)
2. **run_cli** — coding tasks → CLI agent
3. **run_shell** — operational tasks → shell command
4. **run_pipeline** — code+review+test+push+PR workflow
5. **todo_add** — add to the todo queue
6. **scaffold_project** — create a new project from scratch
7. **list_projects** / **read_context** — project info

## Shell Safety
NEVER generate these commands: rm, rmdir, unlink, shred, mkfs, dd, fdisk,
chmod 777, chmod -R, chown -R, shutdown, reboot, halt, poweroff, format.
If the user asks for a destructive operation, explain why it's blocked.

## Shell Selection ({os_name})
{shell_rules}

## CLI Roles
- Coders: claude_code, codex
- Reviewers: gemini_cli, qwen_cli
- Tester: gemini_cli (runs tests + interprets failures)
If user specifies a CLI, use it. Otherwise pick best fit for the role.
"""
```

### 8.2 Tool Definitions

```python
TOOLS = [
    # run_cli — single CLI task
    {
        "type": "function",
        "function": {
            "name": "run_cli",
            "description": "Run a coding task using a CLI agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cli": {"type": "string", "enum": ["claude_code", "codex", "gemini_cli", "qwen_cli"]},
                    "task": {"type": "string"},
                    "project": {"type": "string"},
                },
                "required": ["cli", "task", "project"],
            },
        },
    },
    # run_shell — execute command
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Execute a shell command. NEVER use rm, dd, mkfs, chmod 777, shutdown, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "shell": {"type": "string", "enum": ["auto", "bash", "zsh", "wsl", "powershell", "cmd"], "default": "auto"},
                    "working_dir": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    # run_pipeline — full review pipeline
    {
        "type": "function",
        "function": {
            "name": "run_pipeline",
            "description": "Run the full code-review-test-push-PR pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "task": {"type": "string"},
                    "coder": {"type": "string", "enum": ["claude_code", "codex"], "default": "claude_code"},
                    "reviewers": {"type": "array", "items": {"type": "string"}, "default": ["gemini_cli"]},
                },
                "required": ["project", "task"],
            },
        },
    },
    # scaffold_project — create new project
    {
        "type": "function",
        "function": {
            "name": "scaffold_project",
            "description": "Create a new project from scratch with git, devcontainer, and /init.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name (used as directory name)"},
                    "description": {"type": "string", "description": "What kind of project (e.g., 'Python FastAPI REST API')"},
                },
                "required": ["name", "description"],
            },
        },
    },
    # todo_add
    {
        "type": "function",
        "function": {
            "name": "todo_add",
            "description": "Add a task to the todo queue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cli": {"type": "string", "enum": ["claude_code", "codex", "gemini_cli", "qwen_cli", "pipeline"]},
                    "project": {"type": "string"},
                    "task": {"type": "string"},
                    "priority": {"type": "integer", "default": 3},
                },
                "required": ["cli", "project", "task"],
            },
        },
    },
    # list_projects
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "List all configured projects.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # read_context
    {
        "type": "function",
        "function": {
            "name": "read_context",
            "description": "Read project context files.",
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string"}},
                "required": ["project"],
            },
        },
    },
]
```

---

## 9. Bot Commands (Provider-Agnostic)

Commands work identically across all messaging providers. Slash commands adapt to each platform's native format.

### Message Commands

| Command | Description |
|---------|-------------|
| `!todo add <cli> <project> <task>` | Add to todo list |
| `!todo add <cli> <project> <task> --priority 1` | Add with priority |
| `!todo list` | Show pending items |
| `!todo run` | Start processing queue |
| `!todo status` | Show running tasks per CLI |
| `!todo cancel` | Cancel queue run |
| `!init <project>` | Re-run /init to refresh CLAUDE.md |
| `!harness init <project>` | Scaffold docs/ knowledge base |
| `!harness garden <project>` | Run doc-gardening agent |
| `!harness status <project>` | Show knowledge base health |
| `!skills list` | List all available skills |
| `!skills show <name>` | Show a specific skill's content |
| `!skills create <name>` | Create a new skill template |
| `!usage` | Show today's usage stats per CLI |
| `!usage weekly` | Show weekly usage report |
| `!paused` | List paused tasks waiting for usage refresh |
| `!resume <task_id>` | Force resume a paused task |
| `!cancel` | Cancel current ad-hoc task |

### Slash Commands

| Command | Description |
|---------|-------------|
| `/status` | Current task(s) — ad-hoc, pipeline, or todo |
| `/cancel` | Cancel running task/pipeline/queue |
| `/projects` | List registered projects |
| `/project add <name> <path>` | Register existing project |
| `/shells` | Show OS, shells, default |
| `/doctor` | Check CLIs, shells, gh, docker, LLM connectivity |
| `/config reload` | Hot-reload config |

---

## 10. Module Map

```
devbot/
├── pyproject.toml
├── README.md
├── .env.example
├── config/
│   └── default.yaml
│
├── src/devbot/
│   ├── __init__.py
│   ├── main.py                         # Entry point — devbot start
│   │
│   ├── messaging/                      # ← MESSAGE PROVIDER ABSTRACTION
│   │   ├── __init__.py
│   │   ├── base.py                     # Abstract MessageProvider interface
│   │   ├── discord.py                  # Discord provider (Phase 1)
│   │   ├── telegram.py                 # Telegram provider (future)
│   │   ├── slack.py                    # Slack provider (future)
│   │   └── teams.py                    # MS Teams provider (future)
│   │
│   ├── bot/
│   │   ├── handler.py                  # Core message handler (provider-agnostic)
│   │   ├── commands.py                 # Command registry (slash + message)
│   │   └── formatter.py               # Platform-adaptive formatting
│   │
│   ├── llm/
│   │   ├── router.py                   # MiniMax → Ollama routing
│   │   ├── prompts.py                  # Dynamic system prompts
│   │   └── tools_schema.py             # Tool definitions
│   │
│   ├── executor/
│   │   ├── manager.py                  # Task lifecycle, locks, mode switching
│   │   ├── runner.py                   # Subprocess spawner
│   │   ├── adapters/
│   │   │   ├── base.py                 # Abstract CLI adapter
│   │   │   ├── claude_code.py
│   │   │   ├── codex.py
│   │   │   ├── gemini_cli.py
│   │   │   └── qwen_cli.py
│   │   └── shell/
│   │       ├── platform.py             # OS detection + shell resolution
│   │       ├── executor.py             # Shell command executor
│   │       └── blocklist.py            # Dangerous command patterns
│   │
│   ├── pipeline/
│   │   ├── executor.py                 # Review pipeline orchestrator
│   │   ├── branch.py                   # Branch creation + naming
│   │   ├── review.py                   # Reviewer dispatch + verdict parsing
│   │   ├── test.py                     # Test runner + failure interpretation
│   │   └── pr.py                       # Push + PR creation (gh CLI)
│   │
│   ├── todo/
│   │   ├── parser.py                   # Parse todos.md
│   │   ├── executor.py                 # Parallel dispatch + busy handling
│   │   ├── archiver.py                 # Mark done + move to done.md
│   │   └── validator.py                # Pre-run checks
│   │
│   ├── project/
│   │   ├── registry.py                 # Project config + ad-hoc paths
│   │   ├── context.py                  # Load context files
│   │   ├── init.py                     # /init runner + freshness check
│   │   ├── scaffold.py                 # New project creation
│   │   └── devcontainer.py             # Dev container management
│   │
│   ├── harness/                        # ← HARNESS ENGINEERING
│   │   ├── knowledge_base.py           # Scaffold + manage docs/ structure
│   │   ├── progressive_context.py      # Layered context loading for agents
│   │   ├── execution_plan.py           # Generate + manage versioned plans
│   │   ├── doc_gardening.py            # Stale doc detection + fix-up agent
│   │   └── linter.py                   # Lint runner + remediation feedback
│   │
│   ├── skills/                         # ← SHARED SKILLS SYSTEM
│   │   ├── loader.py                   # Load SKILL.md files from global dir
│   │   ├── injector.py                 # Inject relevant skills into CLI prompts
│   │   └── manager.py                  # List, create, test skills
│   │
│   ├── usage/                          # ← USAGE MANAGEMENT
│   │   ├── tracker.py                  # Log CLI invocations to usage.jsonl
│   │   ├── detector.py                 # Detect rate limit errors from CLI output
│   │   ├── pauser.py                   # Save session + pause task
│   │   ├── scheduler.py                # Auto-resume paused tasks on timer
│   │   └── reporter.py                 # Daily/weekly usage reports
│   │
│   └── reporter/
│       └── base.py                     # Provider-agnostic progress reporter
│
└── tests/
    ├── test_router.py
    ├── test_executor.py
    ├── test_shell.py
    ├── test_blocklist.py
    ├── test_pipeline.py
    ├── test_todo.py
    ├── test_project.py
    ├── test_messaging.py               # Test provider abstraction
    └── test_reporter.py
```

---

## 11. Cross-Platform Matrix

| Concern | Solution |
|---------|----------|
| OS detection | `platform.system()` → Windows / Darwin / Linux |
| Shell resolution | `shutil.which()` per shell |
| WSL detection | `shutil.which("wsl")` on Windows |
| Path conversion | `C:\x` → `/mnt/c/x` for WSL |
| CLI lookup | `shutil.which("claude")`, `shutil.which("codex")`, etc. |
| Subprocess | `asyncio.create_subprocess_exec` (never `shell=True`) |
| Process kill | `terminate()` → 5s → `kill()` |
| Dev containers | Docker — consistent env across all OS |
| Config location | `~/.devbot/` (expands on all OS) |

---

## 12. Error Handling

| Scenario | Behavior |
|----------|----------|
| MiniMax down | Fallback to Ollama; notify Discord |
| Both LLMs down | "⚠️ Both LLMs unavailable" |
| CLI not on PATH | Report + suggest install command |
| CLI times out | Kill process; report |
| Blocked command | Refuse + explain why |
| Project not found | Ask for clarification |
| Shell not available | Suggest alternatives |
| WSL not installed | Fall back to PowerShell |
| Docker not running | Warn; offer to run without container |
| `gh` CLI not installed | Warn; push branch but skip PR creation |
| Pipeline cycle limit | Stop at 10; report partial work on branch |
| Lint fails repeatedly | Counted in cycle limit; report lint errors |
| Reviewer gives no verdict | Default to CHANGES_REQUESTED |
| Tests fail repeatedly | Counted in cycle limit |
| Discord rate limit | Exponential backoff + buffer |
| Busy CLI (todo) | Ask user: assign / hold / skip |
| Context file missing | Run /init to generate |
| CLAUDE.md stale >7 days | Auto-refresh before task |
| docs/ missing | Scaffold knowledge base on first pipeline run |
| Stale docs detected | Warn + schedule gardening; don't block task |
| Execution plan missing | Auto-generate for complex tasks per config |
| CLI usage limit hit | Pause task, save session, auto-resume after refresh period |
| Resume fails (limit again) | Re-pause with new timer, notify user |
| Skill file malformed | Warn + skip skill, don't block task |
| Skills dir missing | Create on first `!skills` command |

---

## 13. Dependencies

```toml
[project]
name = "devbot"
version = "0.1.0"
requires-python = ">=3.11"

[project.dependencies]
"discord.py" = ">=2.3"
openai = ">=1.0"
pyyaml = ">=6.0"
python-dotenv = ">=1.0"
```

---

## 14. Phased Build Plan

### Phase 1 — Foundation
- [ ] Project scaffold (pyproject.toml, src layout)
- [ ] Config loader (YAML + env vars + project registry)
- [ ] Platform detection (OS, shells, all 4 CLIs, docker, gh)
- [ ] Discord bot (connect, owner auth, message handler)
- [ ] **Milestone:** bot connects and replies in Discord

### Phase 2 — Shell Execution
- [ ] Shell executor (bash/zsh/wsl/powershell)
- [ ] Command blocklist (rm, dd, mkfs, chmod 777, shutdown...)
- [ ] WSL path conversion
- [ ] Service management (OpenClaw start/stop/restart/status)
- [ ] Single-task lock + progress reporter
- [ ] **Milestone:** commands in Discord → shell output with safety

### Phase 3 — LLM Router
- [ ] MiniMax + Ollama clients (OpenAI-compat)
- [ ] All tool schemas (run_cli, run_shell, run_pipeline, scaffold_project, todo_add)
- [ ] Dynamic system prompt with platform info + blocklist rules
- [ ] Router: message → LLM → dispatch
- [ ] **Milestone:** natural language → correct action

### Phase 4 — CLI Agents
- [ ] Base adapter + universal stream-json parser
- [ ] Claude Code adapter
- [ ] Codex adapter
- [ ] Gemini CLI adapter
- [ ] Qwen CLI adapter
- [ ] Context loader with freshness check + auto /init
- [ ] **Milestone:** all 4 CLIs work via Discord

### Phase 5 — Project Management + Harness Foundation
- [ ] Project registry (config + ad-hoc)
- [ ] Dev container support (.devcontainer/)
- [ ] Project scaffolding (dir, git init, devcontainer, /init)
- [ ] Knowledge base scaffolding (docs/ directory, AGENTS.md template)
- [ ] Progressive context loader (layered: AGENTS.md → docs/ → plans)
- [ ] Context auto-refresh (>7 days → re-run /init)
- [ ] `!init <project>` and `!harness init <project>` commands
- [ ] **Milestone:** create projects with structured knowledge base

### Phase 6 — Review Pipeline + Harness Enforcement
- [ ] Branch creation (LLM-generated names)
- [ ] Execution plan generation (Step 0 for complex tasks)
- [ ] Coder dispatch (Claude Code / Codex)
- [ ] Lint step (run linters, feed violations back to coder)
- [ ] Reviewer dispatch + structured verdict parsing
- [ ] Test runner (shell) + failure interpretation (reviewer CLI)
- [ ] Fix loop (max 10 cycles)
- [ ] Push + PR creation (gh CLI) + LLM-generated description
- [ ] Plan archival (active → completed after merge)
- [ ] Per-project pipeline + harness config overrides
- [ ] **Milestone:** full pipeline with linting and execution plans

### Phase 7 — Todo Queue
- [ ] Todo parser (todos.md → structured items)
- [ ] Pre-run validator
- [ ] Per-CLI locks (parallel execution)
- [ ] Busy-CLI handling (ask user → assign/hold/skip)
- [ ] Pipeline items in todo list (`pipeline` as cli type)
- [ ] Archiver (done → done.md)
- [ ] `!todo add/list/run/status/cancel`
- [ ] Auto-start on bot startup
- [ ] **Milestone:** parallel todo queue with pipeline support

### Phase 8 — Harness Maintenance + Polish
- [ ] Doc-gardening agent (stale docs, broken links, drift detection)
- [ ] `!harness garden <project>` and `!harness status <project>`
- [ ] Scheduled gardening (daily/weekly cron via todo system)
- [ ] Slash commands (/status, /cancel, /projects, /shells, /doctor)
- [ ] Rich embeds
- [ ] `devbot init` setup wizard
- [ ] `devbot doctor` (validate all tools + connectivity)
- [ ] Cross-platform testing (Windows+WSL, macOS, Ubuntu)
- [ ] README, LICENSE, contributing guide
- [ ] **Milestone:** ready for public repo

---

## 15. Target UX

```bash
# ── Install & Setup ──────────────────────────────
pip install devbot
devbot init            # interactive wizard
devbot doctor          # check everything
devbot start           # launch

# ── Discord: Chat ────────────────────────────────
> what does exit code 137 mean?
> explain the difference between docker compose up and start

# ── Discord: Shell Commands ──────────────────────
> restart openclaw
> check docker status
> run npm install in myapp
> run in powershell: Get-Process node
> git status in infra

# ── Discord: CLI Agent Tasks ─────────────────────
> use claude to fix the auth bug in myapp
> use codex to add a payment module to backend
> ask gemini to review the security of myapp

# ── Discord: Review Pipeline ─────────────────────
> pipeline myapp: add rate limiting to auth endpoints
> pipeline backend: fix SQL injection in search --coder codex

# ── Discord: Project Management ──────────────────
> create a new project called payment-api, Python FastAPI service
> !init myapp
> list projects

# ── Discord: Todo Queue ──────────────────────────
> !todo add claude myapp Fix auth bypass --priority 1
> !todo add pipeline backend Add rate limiting --priority 2
> !todo list
> !todo run

# ── Discord: Todo Queue Running ──────────────────
📋 Starting todo queue: 4 tasks
▶️ Priority 1 — 2 tasks
[claude] 🚀 Fix auth bypass...
[pipeline] 🌿 Created branch: feature/add-rate-limiting
[pipeline] 💻 [codex] Coding...
[claude] ✅ Done (45s)
[pipeline] 🔍 [gemini] Reviewing...
[pipeline] 📋 Verdict: APPROVED
[pipeline] 🧪 Tests passed
[pipeline] 📬 PR created: Add rate limiting
▶️ Priority 2 — 2 tasks
...
📋 Todo queue complete. 4/4 succeeded.
```

---

## 16. Extensibility Points

DevBot is designed to be extended:

| Extension Point | How |
|----------------|-----|
| Add a new CLI | Add entry to `cli:` config + create adapter in `executor/adapters/` |
| Add a messaging platform | Implement `MessageProvider` in `messaging/` (see Section 21) |
| Add a new service | Add to `services:` config — managed via shell |
| Custom blocklist | Edit `shell.blocklist` in config or `blocklist.py` |
| Custom pipeline steps | Subclass `ReviewPipeline` and override steps |
| Custom harness rules | Add linters, structural tests, doc templates per project |
| Add a new skill | Create `~/.devbot/skills/<name>/SKILL.md` |
| Custom usage limits | Set per-CLI refresh periods in config |
| New project templates | Add to scaffolding config |
| Custom commands | Add to `bot/commands.py` (auto-registered across providers) |
| New LLM provider | Add OpenAI-compat client config (same interface) |
| MCP integration | Add MCP server config per CLI |

---

---

## 17. Harness Engineering (Inspired by OpenAI)

### 17.1 Overview

Harness engineering is the practice of designing the environment, feedback loops, and control systems that make AI agents reliable — rather than just writing better prompts. The concept comes from OpenAI's internal team, which built a million-line production codebase with zero manually-written code by investing in scaffolding, not prompting.

DevBot integrates harness engineering at three levels:

| Level | What | How DevBot Implements It |
|-------|------|-------------------------|
| **Context Engineering** | Give agents a map, not an encyclopedia | Structured `docs/` knowledge base, ~100-line AGENTS.md as table of contents, progressive disclosure |
| **Mechanical Enforcement** | If a rule matters, enforce it with a linter | Lint step in pipeline, structural tests in CI, custom linter error messages as remediation hints |
| **Garbage Collection** | Fight entropy with periodic maintenance | Doc-gardening agent, stale-doc detection, automated fix-up PRs |

### 17.2 Structured Knowledge Base

Every DevBot-managed project uses a `docs/` directory as the single source of truth. AGENTS.md is the entry point — short, stable, and pointing to deeper docs.

**AGENTS.md template (~100 lines):**

```markdown
# AGENTS.md — Project Map

## Quick Start
- Run tests: `npm test`
- Lint: `npm run lint`
- Build: `npm run build`

## Architecture
See [docs/architecture.md](docs/architecture.md) for domain map and package layering.

## Code Conventions
See [docs/conventions.md](docs/conventions.md) for style rules and patterns.

## Quality Status
See [docs/quality.md](docs/quality.md) for per-domain quality grades.

## API Contracts
See [docs/api.md](docs/api.md) for data shapes and endpoint specs.

## Active Plans
See [docs/plans/active/](docs/plans/active/) for current execution plans.

## Technical Debt
See [docs/debt.md](docs/debt.md) for known issues and prioritized debt.

## Boundaries
- Dependencies flow: Types → Config → Repo → Service → Runtime → UI
- Cross-cutting concerns enter through Providers only
- Parse data at boundaries — never trust external input shapes
- All architectural rules enforced via linters (see lint config)
```

**Why this works for DevBot:** When a CLI agent starts a task, it reads AGENTS.md first (Claude auto-reads CLAUDE.md, Gemini auto-reads GEMINI.md, Codex auto-reads AGENTS.md). The short entry point keeps the context window focused. The agent navigates to deeper docs only when needed for the current task — progressive disclosure.

### 17.3 Execution Plans

For complex tasks, DevBot generates a versioned execution plan before coding starts. This is the "Step 0" in the review pipeline.

```python
async def generate_execution_plan(task: str, project_path: Path, config) -> Path:
    """Generate an execution plan for complex tasks."""
    plans_dir = project_path / "docs" / "plans" / "active"
    plans_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r'[^a-z0-9-]', '-', task.lower()[:40])
    plan_path = plans_dir / f"{slug}.md"

    # Use the router LLM to generate the plan
    plan_content = await llm_router.generate(
        f"Generate an execution plan for this task. "
        f"Read the project's docs/architecture.md and docs/conventions.md first.\n\n"
        f"Task: {task}\n\n"
        f"Output a markdown plan with:\n"
        f"- Goal (1 sentence)\n"
        f"- Files to modify (list)\n"
        f"- Steps (numbered, specific)\n"
        f"- Verification criteria (how to know it's done)\n"
        f"- Risks and edge cases\n"
    )

    plan_path.write_text(plan_content)

    # Commit the plan
    await shell_exec(f"git add {plan_path}", cwd=project_path)
    await shell_exec(
        f'git commit -m "plan: {slug}"',
        cwd=project_path,
    )

    return plan_path
```

Plan lifecycle:

```
docs/plans/
├── active/                    # plans currently being worked on
│   └── add-rate-limiting.md   # ← coder reads this before coding
└── completed/                 # archived after PR is merged
    ├── fix-auth-bypass.md
    └── add-input-validation.md
```

When the pipeline completes, the plan moves from `active/` to `completed/` with a completion timestamp and PR link appended.

### 17.4 Linter Integration in Pipeline

The lint step runs after coding but before review. Linter errors are fed directly back to the coder as remediation instructions.

```python
async def run_linters(self) -> tuple[bool, str]:
    """Run project linters. Returns (passed, output)."""
    lint_cmd = self.config.pipeline.lint_command
    if not lint_cmd:
        return True, ""

    await self.channel.send(f"🔍 Running linters: `{lint_cmd}`")

    result = await shell_exec(lint_cmd, cwd=self.project, capture=True)

    if result.returncode == 0:
        await self.channel.send("🔍 ✅ Linters passed")
        return True, ""

    await self.channel.send(
        f"🔍 ❌ Lint violations found — feeding back to coder"
    )
    return False, result.output
```

In the pipeline loop, lint failures short-circuit before review:

```python
# In pipeline cycle:
# Step 2: Code
await self._run_coder(feedback)

# Step 3: Lint (NEW — before commit)
lint_passed, lint_output = await self.run_linters()
if not lint_passed:
    feedback = (
        f"Lint violations found. Fix these before proceeding:\n\n"
        f"```\n{lint_output[:5000]}\n```\n\n"
        f"The linter command was: {self.config.pipeline.lint_command}"
    )
    continue  # loop back to coder

# Step 4: Commit (only if lint passes)
await self._commit()
```

**Key insight from OpenAI:** Custom linter error messages should double as remediation instructions. When an agent violates a rule, the error message tells the agent how to fix it — the tooling teaches the agent while it works.

### 17.5 Doc-Gardening Agent

A scheduled maintenance agent scans for stale or inconsistent documentation and opens fix-up PRs.

```python
class DocGardeningAgent:
    """Periodic agent that maintains the knowledge base."""

    CHECKS = [
        "stale_docs",          # docs older than configured threshold
        "broken_links",        # internal links that point to missing files
        "undocumented_modules", # source files with no corresponding doc
        "drift_detection",     # docs that don't match actual code behavior
    ]

    async def run(self, project_path: Path, config):
        """Run all doc gardening checks."""
        issues = []

        # Check for stale docs
        for doc in (project_path / "docs").rglob("*.md"):
            age_days = (datetime.now() - datetime.fromtimestamp(
                doc.stat().st_mtime
            )).days
            if age_days > config.harness.doc_max_age_days:
                issues.append(f"STALE ({age_days}d): {doc.relative_to(project_path)}")

        # Check for broken internal links
        for doc in (project_path / "docs").rglob("*.md"):
            content = doc.read_text()
            for match in re.finditer(r'\[.*?\]\((.*?)\)', content):
                link = match.group(1)
                if link.startswith("http"):
                    continue
                target = (doc.parent / link).resolve()
                if not target.exists():
                    issues.append(f"BROKEN LINK: {doc.name} → {link}")

        if not issues:
            return None

        # Use a CLI agent to fix the issues
        issue_list = "\n".join(f"- {i}" for i in issues)
        task = (
            f"Fix these documentation issues:\n{issue_list}\n\n"
            f"For stale docs: review the current code and update the doc.\n"
            f"For broken links: fix the link or remove it.\n"
            f"For undocumented modules: create a brief doc entry."
        )

        # Run through the review pipeline on a maintenance branch
        return task  # handed to pipeline as a maintenance task
```

### 17.6 Progressive Context Loading

Instead of loading all project docs into the CLI prompt, DevBot uses layered context:

```python
class ProgressiveContextLoader:
    """Load context in layers — small entry point, deeper docs on demand."""

    async def load_for_task(self, project_path: Path, task: str) -> str:
        """Build layered context for a CLI task."""
        layers = []

        # Layer 1: AGENTS.md (always loaded — the map)
        agents_md = self._find_file(project_path, ["AGENTS.md", "agents.md"])
        if agents_md:
            layers.append(f"# Project Map\n\n{agents_md.read_text()}")

        # Layer 2: Relevant docs based on task keywords
        # (let the CLI navigate deeper on its own via AGENTS.md pointers)

        # Layer 3: Active execution plan if one exists for this task
        plans_dir = project_path / "docs" / "plans" / "active"
        if plans_dir.exists():
            for plan in plans_dir.glob("*.md"):
                # Simple keyword matching — the router LLM already parsed the task
                if any(word in plan.stem for word in task.lower().split()):
                    layers.append(f"# Execution Plan\n\n{plan.read_text()}")
                    break

        # Layer 4: Technical debt (always useful context)
        debt_file = project_path / "docs" / "debt.md"
        if debt_file.exists():
            layers.append(f"# Known Technical Debt\n\n{debt_file.read_text()}")

        return "\n\n---\n\n".join(layers)
```

### 17.7 Harness Configuration

```yaml
# In ~/.devbot/config.yaml
harness:
  enabled: true
  doc_max_age_days: 14               # docs older than this flagged as stale
  gardening_schedule: "weekly"       # "daily", "weekly", "manual"
  gardening_cli: "gemini_cli"        # which CLI runs doc gardening
  enforce_knowledge_base: true       # require docs/ directory in managed projects
  plan_threshold: "complex"          # "always", "complex", "never"

# Per-project in .devbot.yaml
harness:
  lint_command: "npm run lint && npm run typecheck"
  structural_tests: "npm run test:architecture"  # custom architectural tests
  doc_gardening: true
  plan_threshold: "always"
```

### 17.8 Knowledge Base Scaffolding

When a new project is created or an existing project is registered, DevBot can scaffold the `docs/` knowledge base:

```
You: "create a new project called payment-api, Python FastAPI service"

DevBot:
  1. mkdir ~/projects/payment-api
  2. git init
  3. Create .devcontainer/
  4. Create docs/ knowledge base:
     - docs/architecture.md  (generated by CLI based on project description)
     - docs/conventions.md   (language-specific defaults)
     - docs/quality.md       (empty template)
     - docs/api.md           (empty template)
     - docs/plans/active/    (empty)
     - docs/plans/completed/ (empty)
     - docs/debt.md          (empty template)
  5. Generate AGENTS.md (table of contents pointing to docs/)
  6. Run Claude /init to enrich everything
  7. Initial commit
```

### 17.9 Harness Engineering UX in Discord

```
# Scaffold knowledge base for existing project
> !harness init myapp
DevBot: 📚 Scaffolding knowledge base for myapp...
DevBot: Created docs/architecture.md, conventions.md, quality.md, api.md, debt.md
DevBot: Generated AGENTS.md (table of contents)
DevBot: ✅ Knowledge base ready

# Run doc gardening manually
> !harness garden myapp
DevBot: 🌱 Running doc gardening on myapp...
DevBot: Found 3 issues: 2 stale docs, 1 broken link
DevBot: 🌿 Created branch: maintenance/doc-gardening-20260320
DevBot: [gemini] Fixing documentation issues...
DevBot: 📬 PR created: Fix stale docs and broken links

# Check harness health
> !harness status myapp
DevBot: 📊 Harness status for myapp:
  Knowledge base: ✅ docs/ exists (7 files)
  AGENTS.md: ✅ up to date (2 days old)
  Stale docs: ⚠️ 1 file older than 14 days
  Broken links: ✅ none
  Active plans: 1 (add-rate-limiting)
  Lint config: ✅ npm run lint
  Last gardening: 3 days ago
```

---

## 18. Shared Skills System

### 18.1 Overview

Skills are reusable markdown instruction files that any CLI agent can consume. They live in a global directory shared across all CLIs and projects, providing consistent capabilities regardless of which agent runs the task.

```
~/.devbot/skills/
├── code-review/
│   └── SKILL.md          # How to do a thorough code review
├── testing/
│   └── SKILL.md          # How to write comprehensive tests
├── refactoring/
│   └── SKILL.md          # Refactoring patterns and safety checks
├── security-audit/
│   └── SKILL.md          # Security review checklist
├── api-design/
│   └── SKILL.md          # REST/GraphQL API design conventions
├── documentation/
│   └── SKILL.md          # How to write good docs
├── git-workflow/
│   └── SKILL.md          # Branch naming, commit messages, PR conventions
└── devops/
    └── SKILL.md          # Docker, CI/CD, deployment patterns
```

### 18.2 SKILL.md Format

Each skill follows a standard format that all CLIs can parse:

```markdown
# Skill: Code Review

## Description
Comprehensive code review focusing on correctness, security, performance, and maintainability.

## When to Use
- Reviewing a git diff before approving
- Reviewing changes in the pipeline review step
- Manual code review requested by user

## Instructions
1. Check for correctness: does the code do what it claims?
2. Check for security: SQL injection, XSS, auth bypasses, secrets in code
3. Check for performance: N+1 queries, unnecessary loops, missing indexes
4. Check for maintainability: naming, complexity, duplication, test coverage
5. Check for conventions: does it follow the project's docs/conventions.md?

## Output Format
End your review with exactly one of:
- `VERDICT: APPROVED` — no issues found
- `VERDICT: CHANGES_REQUESTED` — list specific issues above

## Examples
<example>
Good: "The input validation in `login()` doesn't sanitize the email field..."
Bad: "Looks fine" (too vague, not actionable)
</example>
```

### 18.3 How Skills Are Injected

When a CLI agent runs a task, DevBot determines which skills are relevant and injects them into the prompt:

```python
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._cache: dict[str, str] = {}

    def load_all(self) -> dict[str, str]:
        """Load all skills into a name → content map."""
        skills = {}
        if not self.skills_dir.exists():
            return skills
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skills[skill_dir.name] = skill_file.read_text()
        return skills

    def get_for_role(self, role: str) -> list[str]:
        """Get relevant skills for a given role."""
        all_skills = self.load_all()
        role_mapping = {
            "coder": ["refactoring", "testing", "git-workflow", "api-design"],
            "reviewer": ["code-review", "security-audit"],
            "tester": ["testing"],
            "devops": ["devops"],
            "documentation": ["documentation"],
        }
        relevant = role_mapping.get(role, [])
        return [all_skills[name] for name in relevant if name in all_skills]

    def get_by_name(self, name: str) -> str | None:
        """Get a specific skill by name."""
        all_skills = self.load_all()
        return all_skills.get(name)
```

### 18.4 Skill Injection in CLI Adapters

Skills are appended to the task prompt before sending to the CLI:

```python
class CLIAdapter:
    def build_prompt(self, task: str, context: str, skills: list[str]) -> str:
        """Build the full prompt with context and skills."""
        parts = []

        # Project context (AGENTS.md, docs, etc.)
        if context:
            parts.append(f"## Project Context\n\n{context}")

        # Relevant skills
        for skill in skills:
            parts.append(f"## Skill Instructions\n\n{skill}")

        # The actual task
        parts.append(f"## Task\n\n{task}")

        return "\n\n---\n\n".join(parts)
```

### 18.5 Skills in the Review Pipeline

The pipeline automatically selects skills based on the current step:

```
Step 2 (CODE)   → injects: refactoring, api-design, git-workflow skills
Step 3 (LINT)   → no skills needed (shell command)
Step 5 (REVIEW) → injects: code-review, security-audit skills
Step 7 (TEST)   → injects: testing skill
```

### 18.6 Skill Management Commands

```
# List available skills
> !skills list
DevBot: 📚 Available skills (8):
  code-review, testing, refactoring, security-audit,
  api-design, documentation, git-workflow, devops

# Show a specific skill
> !skills show code-review
DevBot: 📄 Skill: Code Review
  (shows SKILL.md content)

# Create a new skill (DevBot scaffolds the file)
> !skills create database-migration
DevBot: 📝 Created ~/.devbot/skills/database-migration/SKILL.md (template)
  Edit the file to add your instructions.

# Test a skill by running it against a project
> !skills test code-review myapp
DevBot: 🧪 Running code-review skill against myapp with gemini...
```

### 18.7 Configuration

```yaml
# In ~/.devbot/config.yaml
skills:
  dir: "~/.devbot/skills"
  auto_inject: true                    # automatically inject relevant skills
  role_mapping:                        # override which skills map to which roles
    coder: ["refactoring", "testing", "git-workflow"]
    reviewer: ["code-review", "security-audit"]
    tester: ["testing"]
```

---

## 19. Usage Management & Session Persistence

### 19.1 Overview

When a CLI agent hits its usage/rate limit mid-task, DevBot doesn't switch to a different CLI. Instead, it **saves the session and pauses**, then **auto-resumes** when the refresh period passes. This preserves all task context and avoids the complexity of cross-CLI handoffs.

```
CLI hits usage limit
  │
  ▼
Detect limit error (parse stderr/exit code)
  │
  ▼
Save session ID + task state to ~/.devbot/paused.yaml
  │
  ▼
Mark task as ⏸️ PAUSED (waiting for usage refresh)
  │
  ▼
Notify user in Discord
  │
  ▼
Wait for refresh period (per-CLI config)
  │
  ▼
Auto-resume: cli --resume <session_id> "continue the task"
  │
  ▼
Task continues where it left off
```

### 19.2 Usage Limit Detection

DevBot detects limits by parsing CLI error output — no pre-tracking needed:

```python
import re

# Patterns that indicate usage/rate limit errors
LIMIT_PATTERNS = [
    r"rate.?limit",
    r"quota.?exceeded",
    r"too.?many.?requests",
    r"429",                           # HTTP 429 Too Many Requests
    r"usage.?limit",
    r"token.?limit.?reached",
    r"capacity.?exceeded",
    r"try.?again.?(in|after)",
    r"cooldown",
    r"throttl",
]

def detect_usage_limit(stderr: str, exit_code: int) -> bool:
    """Check if a CLI failure was due to usage limits."""
    combined = stderr.lower()
    for pattern in LIMIT_PATTERNS:
        if re.search(pattern, combined):
            return True
    # Some CLIs use specific exit codes for rate limits
    if exit_code in (429, 42, 75):    # varies by CLI
        return True
    return False
```

### 19.3 Session Persistence

When a limit is hit, DevBot saves the session state:

```python
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

@dataclass
class PausedTask:
    task_id: str                       # unique ID
    cli: str                           # which CLI was running
    session_id: str                    # CLI session ID for --resume
    project: str                       # project name or path
    task: str                          # original task description
    paused_at: str                     # ISO timestamp
    resume_after: str                  # ISO timestamp — earliest resume time
    cycle: int                         # pipeline cycle number (if in pipeline)
    pipeline: bool                     # was this a pipeline task?
    status: str                        # "paused" | "resuming" | "completed"

# Refresh periods per CLI
CLI_REFRESH_PERIODS = {
    "claude_code": timedelta(hours=5),
    "codex": timedelta(hours=5),
    "gemini_cli": timedelta(days=1),
    "qwen_cli": timedelta(days=1),
    "minimax": timedelta(hours=5),
}

async def pause_task(cli: str, session_id: str, project: str,
                     task: str, cycle: int, is_pipeline: bool) -> PausedTask:
    """Save a paused task for later resumption."""
    now = datetime.now()
    refresh = CLI_REFRESH_PERIODS.get(cli, timedelta(hours=5))

    paused = PausedTask(
        task_id=f"{cli}-{now.strftime('%Y%m%d%H%M%S')}",
        cli=cli,
        session_id=session_id,
        project=project,
        task=task,
        paused_at=now.isoformat(),
        resume_after=(now + refresh).isoformat(),
        cycle=cycle,
        pipeline=is_pipeline,
        status="paused",
    )

    # Append to paused tasks file
    paused_file = Path("~/.devbot/paused.yaml").expanduser()
    existing = yaml.safe_load(paused_file.read_text()) if paused_file.exists() else []
    existing.append(asdict(paused))
    paused_file.write_text(yaml.dump(existing))

    return paused
```

### 19.4 Auto-Resume Scheduler

A background task checks for paused tasks that are ready to resume:

```python
class ResumeScheduler:
    def __init__(self, task_manager, config, channel):
        self.task_manager = task_manager
        self.config = config
        self.channel = channel
        self._running = True

    async def run(self):
        """Background loop — check for resumable tasks every 5 minutes."""
        while self._running:
            await asyncio.sleep(300)  # check every 5 min
            await self._check_paused()

    async def _check_paused(self):
        paused_file = Path("~/.devbot/paused.yaml").expanduser()
        if not paused_file.exists():
            return

        tasks = yaml.safe_load(paused_file.read_text()) or []
        now = datetime.now()
        still_paused = []

        for t in tasks:
            if t["status"] != "paused":
                still_paused.append(t)
                continue

            resume_after = datetime.fromisoformat(t["resume_after"])
            if now >= resume_after:
                # Ready to resume
                await self._resume_task(t)
            else:
                still_paused.append(t)

        # Write back remaining paused tasks
        paused_file.write_text(yaml.dump(still_paused))

    async def _resume_task(self, t: dict):
        """Resume a paused task using the CLI's session resume."""
        cli = t["cli"]
        session_id = t["session_id"]
        cli_config = self.config.cli[cli]

        await self.channel.send(
            f"▶️ Resuming paused task on **{cli}**\n"
            f"Task: `{t['task'][:100]}`\n"
            f"Session: `{session_id[:12]}...`\n"
            f"Paused for: {self._format_duration(t['paused_at'])}"
        )

        # Build resume command — each CLI has different resume syntax
        resume_commands = {
            "claude_code": ["claude", "--resume", session_id, "-p",
                           "Continue the task from where you left off.",
                           "--dangerously-skip-permissions",
                           "--output-format", "stream-json"],
            "codex":       ["codex", "exec", "resume", session_id,
                           "Continue the task from where you left off.",
                           "--full-auto", "--json"],
            "gemini_cli":  ["gemini", "--resume", session_id, "-p",
                           "Continue the task from where you left off.",
                           "--yolo", "--output-format", "stream-json"],
            "qwen_cli":    ["qwen", "--resume", session_id, "-p",
                           "Continue the task from where you left off.",
                           "--yolo", "--output-format", "stream-json"],
        }

        cmd = resume_commands.get(cli)
        if not cmd:
            await self.channel.send(f"⚠️ Don't know how to resume {cli}")
            return

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=t["project"],
        )

        reporter = DiscordReporter(self.channel, prefix=f"[{cli}:resumed]")
        await read_cli_stream(process, reporter)
        returncode = await process.wait()

        if returncode == 0:
            await self.channel.send(
                f"✅ [{cli}] Resumed task completed successfully"
            )
        else:
            # Check if it hit the limit again
            stderr = (await process.stderr.read()).decode()
            if detect_usage_limit(stderr, returncode):
                await self.channel.send(
                    f"⏸️ [{cli}] Hit usage limit again — re-pausing"
                )
                # Re-pause with new session ID if available
                await pause_task(cli, session_id, t["project"],
                                t["task"], t["cycle"], t["pipeline"])
            else:
                await self.channel.send(
                    f"❌ [{cli}] Resumed task failed (exit {returncode})"
                )
```

### 19.5 Usage Tracking & Reports

DevBot logs every CLI invocation and generates reports:

```python
@dataclass
class UsageEntry:
    timestamp: str
    cli: str
    project: str
    task: str                          # first 100 chars
    duration_seconds: float
    exit_code: int
    paused: bool                       # was this task paused due to limits?

class UsageTracker:
    def __init__(self, log_path: Path):
        self.log_path = log_path       # ~/.devbot/usage.jsonl

    async def log(self, entry: UsageEntry):
        """Append a usage entry to the log."""
        with open(self.log_path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    async def daily_report(self) -> str:
        """Generate a daily usage report."""
        entries = self._load_entries(days=1)
        by_cli = defaultdict(list)
        for e in entries:
            by_cli[e["cli"]].append(e)

        lines = ["📊 **Daily Usage Report**\n"]
        total_tasks = 0
        total_paused = 0

        for cli, tasks in sorted(by_cli.items()):
            count = len(tasks)
            paused = sum(1 for t in tasks if t["paused"])
            total_time = sum(t["duration_seconds"] for t in tasks)
            success = sum(1 for t in tasks if t["exit_code"] == 0)
            total_tasks += count
            total_paused += paused

            lines.append(
                f"**{cli}**: {count} tasks, "
                f"{success}/{count} succeeded, "
                f"{total_time/60:.0f}min total"
                f"{f', ⏸️ {paused} paused' if paused else ''}"
            )

        lines.append(f"\n**Total**: {total_tasks} tasks, "
                     f"{total_paused} paused due to limits")
        return "\n".join(lines)

    async def weekly_report(self) -> str:
        """Generate a weekly usage report."""
        entries = self._load_entries(days=7)
        # Similar to daily but grouped by day
        ...
```

### 19.6 Integration with Pipeline

When a limit is hit during a pipeline run, the entire pipeline pauses — not just the current step:

```python
# In ReviewPipeline._run_coder() or _run_review():
process = await adapter.spawn(prompt, self.project)
await read_cli_stream(process, reporter)
returncode = await process.wait()

# Check for usage limit
stderr = (await process.stderr.read()).decode()
if detect_usage_limit(stderr, returncode):
    session_id = extract_session_id(process, stderr)
    paused = await pause_task(
        cli=self.config.pipeline.coder,
        session_id=session_id,
        project=str(self.project),
        task=self.task,
        cycle=self.cycle,
        is_pipeline=True,
    )
    await self.channel.send(
        f"⏸️ **Pipeline paused** — {paused.cli} hit usage limit\n"
        f"Will auto-resume after {paused.resume_after}\n"
        f"Or use `!resume {paused.task_id}` to force resume"
    )
    raise PipelinePausedError(paused)
```

### 19.7 Commands

```
# View current usage stats
> !usage
DevBot: 📊 Today's usage:
  claude_code: 12 tasks, 11 succeeded, 45min total
  gemini_cli: 8 tasks, 8 succeeded, 22min total
  codex: 3 tasks, 2 succeeded, ⏸️ 1 paused
  qwen_cli: 5 tasks, 5 succeeded, 15min total

# View paused tasks
> !paused
DevBot: ⏸️ Paused tasks (1):
  1. [codex] `Add payment module to backend`
     Paused: 2h ago | Resumes in: 3h
     Session: abc123...

# Force resume a paused task
> !resume codex-20260320143000
DevBot: ▶️ Force resuming codex task...

# View weekly report
> !usage weekly
DevBot: 📊 Weekly report: ...
```

### 19.8 Configuration

```yaml
# In ~/.devbot/config.yaml
usage:
  log_file: "~/.devbot/usage.jsonl"
  paused_file: "~/.devbot/paused.yaml"
  daily_report: true                    # auto-send daily report
  daily_report_time: "09:00"            # when to send daily report
  weekly_report: true                   # auto-send weekly report
  weekly_report_day: "monday"

  # Per-CLI refresh periods (how long to wait before resuming)
  refresh_periods:
    claude_code: "5h"
    codex: "5h"
    gemini_cli: "24h"
    qwen_cli: "24h"
    minimax: "5h"
```

---

## 20. Future Considerations

- Multi-user support with role-based permissions
- Task dependencies (DAG execution in todo queue)
- Web dashboard alongside messaging platforms
- SSH remote execution
- SQLite result storage + searchable task history
- Conversation memory across sessions
- Auto-retry failed tasks with different strategies
- Deeper OpenClaw integration (delegate tasks, share context)
- Harness templates marketplace (share harness configs across projects)
- Skill marketplace (community-shared skills)
- Usage cost estimation (map CLI usage to estimated $ cost)

---

## 21. Messaging Provider Abstraction (Design-Ready, Lowest Priority)

### 21.1 Overview

DevBot's entire interaction layer is abstracted behind a `MessageProvider` interface. Discord is the first (and currently only) implementation. Additional providers can be added without changing any core logic — the LLM router, CLI executor, pipeline, todo queue, and project manager are all provider-agnostic.

```
┌─────────────────────────────────────────────────┐
│              MessageProvider (ABC)                │
│                                                   │
│  on_message(text, author_id, channel)             │
│  send_text(channel, text)                         │
│  send_rich(channel, title, body, color, fields)   │
│  send_code_block(channel, text, language)          │
│  wait_for_reply(channel, check_fn, timeout)        │
│  register_command(name, description, handler)      │
│  start() / stop()                                  │
└─────────┬──────────┬──────────┬──────────┬───────┘
          │          │          │          │
   ┌──────▼──┐ ┌────▼────┐ ┌──▼───┐ ┌───▼────┐
   │ Discord │ │Telegram │ │Slack │ │ Teams  │
   │Provider │ │Provider │ │Prov. │ │Provider│
   └─────────┘ └─────────┘ └──────┘ └────────┘
     Phase 1     Future      Future    Future
```

### 21.2 Abstract Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Awaitable, Any

@dataclass
class IncomingMessage:
    text: str
    author_id: str
    channel_id: str
    platform: str              # "discord", "telegram", "slack", "teams"
    raw: Any = None            # platform-specific message object

@dataclass
class RichMessage:
    title: str
    body: str = ""
    color: str = "blue"        # "green", "red", "blue", "yellow"
    fields: list[tuple[str, str, bool]] = None  # (name, value, inline)

class MessageProvider(ABC):
    """Abstract messaging platform interface."""

    @abstractmethod
    async def start(self):
        """Connect to the platform and start listening."""
        ...

    @abstractmethod
    async def stop(self):
        """Gracefully disconnect."""
        ...

    @abstractmethod
    async def send_text(self, channel_id: str, text: str):
        """Send a plain text message."""
        ...

    @abstractmethod
    async def send_rich(self, channel_id: str, message: RichMessage):
        """Send a rich/formatted message (embed, card, etc.)."""
        ...

    @abstractmethod
    async def send_code_block(self, channel_id: str, text: str, language: str = ""):
        """Send text wrapped in a code block."""
        ...

    @abstractmethod
    async def wait_for_reply(
        self,
        channel_id: str,
        check: Callable[[IncomingMessage], bool],
        timeout: float = 300,
    ) -> IncomingMessage | None:
        """Wait for a user reply matching the check function."""
        ...

    @abstractmethod
    async def register_command(
        self,
        name: str,
        description: str,
        handler: Callable[[IncomingMessage], Awaitable[None]],
    ):
        """Register a platform command (slash command, bot command, etc.)."""
        ...

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return platform identifier: 'discord', 'telegram', etc."""
        ...

    @property
    @abstractmethod
    def max_message_length(self) -> int:
        """Platform's max message length (Discord=2000, Telegram=4096, etc.)."""
        ...
```

### 21.3 Platform Capabilities & Constraints

| Feature | Discord | Telegram | Slack | MS Teams |
|---------|---------|----------|-------|----------|
| Max message length | 2,000 chars | 4,096 chars | 40,000 chars | 28,000 chars |
| Rich embeds/cards | Embeds | HTML formatting | Blocks (JSON) | Adaptive Cards |
| Code blocks | ` ```lang ``` ` | ` ```lang ``` ` | ` ```lang ``` ` | ` ```lang ``` ` |
| Slash commands | Yes (native) | Bot commands | Slash commands | Bot commands |
| Reactions | Yes | Yes | Yes (emoji) | Yes (emoji) |
| Threads | Yes | Reply threads | Threads | Reply threads |
| File upload | Yes | Yes | Yes | Yes |
| Rate limits | 5 msg/5s per channel | 30 msg/s | 1 msg/s per channel | 4 msg/s |
| Bot library | `discord.py` | `python-telegram-bot` | `slack-bolt` | `botbuilder-python` |
| Auth model | Bot token | Bot token | OAuth + Bot token | Azure AD + Bot ID |

### 21.4 Platform-Adaptive Formatting

The `formatter.py` module adapts output based on the provider's capabilities:

```python
class MessageFormatter:
    """Adapts DevBot output to platform-specific formatting."""

    def __init__(self, provider: MessageProvider):
        self.provider = provider
        self.max_len = provider.max_message_length

    def format_task_start(self, cli: str, task: str, project: str) -> str | RichMessage:
        """Format a task start notification."""
        if self.provider.platform_name == "discord":
            return RichMessage(
                title=f"🚀 {cli}",
                body=f"**Task:** {task[:200]}\n**Project:** {project}",
                color="blue",
            )
        elif self.provider.platform_name == "telegram":
            return f"🚀 <b>{cli}</b>\n<b>Task:</b> {task[:200]}\n<b>Project:</b> {project}"
        elif self.provider.platform_name == "slack":
            return {  # Slack Block Kit
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn",
                     "text": f"🚀 *{cli}*\n*Task:* {task[:200]}\n*Project:* {project}"}}
                ]
            }
        else:
            return f"🚀 {cli}\nTask: {task[:200]}\nProject: {project}"

    def truncate(self, text: str, reserve: int = 100) -> str:
        """Truncate text to fit platform limits."""
        limit = self.max_len - reserve
        if len(text) <= limit:
            return text
        return "..." + text[-(limit - 3):]
```

### 21.5 Configuration

```yaml
# In ~/.devbot/config.yaml
messaging:
  provider: "discord"                   # active provider
  discord:
    token: "${DISCORD_BOT_TOKEN}"
    owner_id: "123456789012345678"
    channel_id: null
  telegram:                              # ready for future use
    token: "${TELEGRAM_BOT_TOKEN}"
    owner_id: "987654321"                # Telegram user ID
    allowed_chat_ids: []                 # empty = any chat with owner
  slack:
    bot_token: "${SLACK_BOT_TOKEN}"
    app_token: "${SLACK_APP_TOKEN}"
    owner_user_id: "U0123456789"
    channel_id: "C0123456789"
  teams:
    app_id: "${TEAMS_APP_ID}"
    app_password: "${TEAMS_APP_PASSWORD}"
    tenant_id: "${TEAMS_TENANT_ID}"
    owner_email: "user@company.com"
```

### 21.6 Provider Startup

```python
# In main.py
async def create_provider(config) -> MessageProvider:
    """Factory — create the configured messaging provider."""
    provider_name = config.messaging.provider

    if provider_name == "discord":
        from devbot.messaging.discord import DiscordProvider
        return DiscordProvider(config.messaging.discord)
    elif provider_name == "telegram":
        from devbot.messaging.telegram import TelegramProvider
        return TelegramProvider(config.messaging.telegram)
    elif provider_name == "slack":
        from devbot.messaging.slack import SlackProvider
        return SlackProvider(config.messaging.slack)
    elif provider_name == "teams":
        from devbot.messaging.teams import TeamsProvider
        return TeamsProvider(config.messaging.teams)
    else:
        raise ValueError(f"Unknown messaging provider: {provider_name}")

# Core handler is provider-agnostic
async def main():
    config = load_config()
    provider = await create_provider(config)

    handler = MessageHandler(
        provider=provider,
        llm_router=LLMRouter(config.llm),
        task_manager=TaskManager(config),
        todo_executor=TodoExecutor(config),
        pipeline_runner=PipelineRunner(config),
    )

    provider.on_message = handler.handle_message
    await provider.start()
```

### 21.7 Implementation Priority

| Provider | Priority | Status | Dependency |
|----------|----------|--------|------------|
| Discord | Phase 1 | Build first | `discord.py` |
| Telegram | Lowest | Design ready | `python-telegram-bot` |
| Slack | Lowest | Design ready | `slack-bolt` |
| MS Teams | Lowest | Design ready | `botbuilder-python` |
| WhatsApp | Future | Not designed | Business API required |

The Discord provider ships first and is the reference implementation. Other providers are added by implementing the `MessageProvider` interface — no changes to core logic needed.
