"""Tool definitions for the router LLM in both Anthropic and OpenAI formats.

Design principles:
- Tool descriptions are self-discriminating -- each one clearly states WHEN to use it
- System prompt uses intent-first routing: classify intent -> pick tool
- No negative rules ("never do X"); only positive decision paths
- Services, projects, and shells are injected as structured facts, not prose
"""

from __future__ import annotations

import platform
import shutil
from typing import TYPE_CHECKING

from devbot.workflow.registry import load_role_registry, load_workflow_registry

if TYPE_CHECKING:
    from devbot.config.settings import Config

# ---------------------------------------------------------------------------
# Tool definitions - Anthropic SDK format (used by MiniMax)
# ---------------------------------------------------------------------------

ANTHROPIC_TOOLS: list[dict] = [
    {
        "name": "run_cli",
        "description": (
            "Dispatch a software task to an AI coding agent (Claude Code, Codex, Gemini CLI, or Qwen CLI). "
            "Use this when the user wants to WRITE, EDIT, FIX, REFACTOR, or IMPLEMENT source code, "
            "generate new files, debug logic errors, or do any task that requires an AI to read and "
            "modify a codebase. Do NOT use for project evaluation, architecture analysis, shell "
            "commands, service management, or reading documentation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cli": {
                    "type": "string",
                    "enum": ["claude_code", "codex", "gemini_cli", "qwen_cli"],
                    "description": "Which CLI agent to use. Coders: claude_code, codex. Reviewers: gemini_cli, qwen_cli.",
                },
                "task": {
                    "type": "string",
                    "description": "The full task description to pass to the CLI.",
                },
                "project": {
                    "type": "string",
                    "description": "Project name (from config) or absolute path.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: specific files to focus on (relative to project root).",
                },
            },
            "required": ["cli", "task", "project"],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Execute a shell command on the host machine. "
            "Use this for: service management (start/stop/restart/status/logs), "
            "git operations, running tests or builds, checking system state, "
            "installing packages, any other operational or system-level task. "
            "When a service name is mentioned with an operational verb "
            "(start, stop, restart, status, logs, deploy, kill), always use this tool "
            "with the pre-configured command for that service."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "shell": {
                    "type": "string",
                    "enum": ["auto", "bash", "zsh", "wsl", "powershell", "cmd"],
                    "description": "Shell to use. Default: auto.",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory. Omit to inherit from bot.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_context",
        "description": (
            "Read a project's context files (CLAUDE.md, AGENTS.md, README.md). "
            "Use this ONLY when the user explicitly asks to see, read, or explain the "
            "project documentation or context -- e.g. 'show me the context for X', "
            "'what does the README say', 'read the AGENTS.md'. "
            "Do NOT use this for service management or running tasks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name or absolute path.",
                },
            },
            "required": ["project"],
        },
    },
    {
        "name": "read_files",
        "description": (
            "Read specific files from a project by relative path or glob. "
            "Use this when the user explicitly names files or asks to show, summarize, or inspect "
            "specific docs or source files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name or absolute path.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relative file paths or glob patterns to read.",
                },
                "purpose": {
                    "type": "string",
                    "description": "Optional: why these files are being read.",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Optional cap on matched files.",
                },
            },
            "required": ["project", "files"],
        },
    },
    {
        "name": "analyze_project",
        "description": (
            "Run a structured project evaluation or review using a reviewer-style role. "
            "Use this when the user wants an analysis, evaluation, review, critique, or assessment "
            "of workflow, architecture, design docs, implementation quality, risks, or completeness. "
            "Prefer this over run_cli when the main deliverable is a report rather than code changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name or absolute path.",
                },
                "goal": {
                    "type": "string",
                    "description": "The analysis goal to hand to the reviewer role.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["analyze", "review", "evaluate"],
                    "description": "Analysis style. Default: analyze.",
                },
                "file_hints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional explicit file names or globs to prioritize.",
                },
                "role": {
                    "type": "string",
                    "description": "Role to use from the role registry. Default: reviewer.",
                },
                "workflow": {
                    "type": "string",
                    "description": "Workflow name from the workflow registry. Default: analysis.",
                },
                "reviewer_cli": {
                    "type": "string",
                    "enum": ["claude_code", "codex", "gemini_cli", "qwen_cli"],
                    "description": "Optional CLI override for the reviewer role.",
                },
            },
            "required": ["project", "goal"],
        },
    },
    {
        "name": "ask_clarification",
        "description": (
            "Ask the user for more information before proceeding. "
            "Use this when the request is genuinely ambiguous and cannot be resolved "
            "from context -- e.g. multiple projects exist and none is mentioned, "
            "or the task description is too vague to act on safely."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "list_projects",
        "description": "List all registered projects with their paths and descriptions.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# ---------------------------------------------------------------------------
# Tool definitions - OpenAI-compat format (used by Ollama fallback)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "run_cli",
            "description": (
                "Dispatch a software task to an AI coding agent. "
                "Use for: writing, editing, fixing, refactoring, or implementing source code. "
                "Do NOT use for project evaluation, shell commands, service management, or reading docs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cli": {
                        "type": "string",
                        "enum": ["claude_code", "codex", "gemini_cli", "qwen_cli"],
                    },
                    "task": {"type": "string"},
                    "project": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["cli", "task", "project"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Execute a shell command. "
                "Use for: service management, git, tests, builds, system checks. "
                "When a service name + operational verb (start/stop/restart/status/logs) is mentioned, "
                "use the pre-configured command for that service."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "shell": {
                        "type": "string",
                        "enum": ["auto", "bash", "zsh", "wsl", "powershell", "cmd"],
                        "default": "auto",
                    },
                    "working_dir": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_context",
            "description": (
                "Read project context files (CLAUDE.md, AGENTS.md, README.md). "
                "Use ONLY when user explicitly asks to read/show project documentation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string"}},
                "required": ["project"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_files",
            "description": (
                "Read specific files from a project by relative path or glob. "
                "Use when the user explicitly names files or wants to inspect specific docs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "purpose": {"type": "string"},
                    "max_files": {"type": "integer"},
                },
                "required": ["project", "files"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_project",
            "description": (
                "Run a structured project evaluation or review using a reviewer-style role. "
                "Use when the user wants an assessment rather than code changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "goal": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["analyze", "review", "evaluate"],
                    },
                    "file_hints": {"type": "array", "items": {"type": "string"}},
                    "role": {"type": "string"},
                    "workflow": {"type": "string"},
                    "reviewer_cli": {
                        "type": "string",
                        "enum": ["claude_code", "codex", "gemini_cli", "qwen_cli"],
                    },
                },
                "required": ["project", "goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "Ask the user for clarification when the request is genuinely ambiguous.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "List all registered projects.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# ---------------------------------------------------------------------------
# Dynamic system prompt
# ---------------------------------------------------------------------------

def _detect_shells() -> list[str]:
    shells: list[str] = []
    for s in ("bash", "zsh", "wsl", "powershell", "pwsh", "cmd"):
        if shutil.which(s):
            shells.append(s)
    return shells


def _detect_clis() -> list[str]:
    clis: list[str] = []
    for name, binary in [
        ("claude_code", "claude"),
        ("codex", "codex"),
        ("gemini_cli", "gemini"),
        ("qwen_cli", "qwen"),
    ]:
        if shutil.which(binary):
            clis.append(name)
    return clis


def _shell_rules(os_name: str, available_shells: list[str]) -> str:
    if os_name == "Windows":
        if "wsl" in available_shells:
            return "WSL bash (default) for Unix commands; powershell for Windows-native. Paths: C:\\x -> /mnt/c/x in WSL."
        return "PowerShell (WSL not available)."
    if os_name == "Darwin":
        return "zsh (default)."
    return "bash (default)."


def _build_projects_section(config: "Config | None") -> str:
    if not config or not config.projects:
        return "  (none registered)"
    lines: list[str] = []
    for name, proj in config.projects.items():
        desc = f" - {proj.description}" if proj.description else ""
        lines.append(f"  {name}: {proj.path}{desc}")
    return "\n".join(lines)


def _build_services_section(config: "Config | None") -> str:
    """Render services as a structured lookup table for the LLM."""
    if not config or not config.services:
        return "  (none configured)"
    lines: list[str] = []
    for name, svc in config.services.items():
        lines.append(f"  {name} (shell: {svc.shell}):")
        for action, cmd in svc.commands.items():
            lines.append(f"    {action}: {cmd}")
    return "\n".join(lines)


def _build_roles_section(config: "Config | None") -> str:
    if not config:
        return "  (defaults unavailable)"
    registry = load_role_registry(config)
    lines: list[str] = []
    for name, role in registry.items():
        preferred = ", ".join(role.preferred_clis) or "auto"
        lines.append(f"  {name}: {role.purpose or '(no purpose)'} [preferred: {preferred}]")
    return "\n".join(lines)


def _build_workflows_section(config: "Config | None") -> str:
    if not config:
        return "  (defaults unavailable)"
    registry = load_workflow_registry(config)
    lines: list[str] = []
    for name, workflow in registry.items():
        stages = " -> ".join(workflow.stages) or "(no stages)"
        lines.append(f"  {name}: {stages}")
    return "\n".join(lines)


def build_system_prompt(config: "Config | None" = None) -> str:
    """Build the router system prompt from live environment state."""
    os_name = platform.system()
    available_shells = _detect_shells()
    installed_clis = _detect_clis()

    return f"""\
You are DevBot, an AI development assistant. You receive natural language requests
and call the appropriate tool to fulfil them.

== ENVIRONMENT ============================================================
OS: {os_name}
Shells: {', '.join(available_shells) or 'none detected'}
Shell default: {_shell_rules(os_name, available_shells)}
CLI agents installed: {', '.join(installed_clis) or 'none detected'}

== PROJECTS ===============================================================
(use run_cli or read_context for these)
{_build_projects_section(config)}

== SERVICES ===============================================================
(always use run_shell for these — copy the command exactly as listed)
{_build_services_section(config)}

== TEAM ROLES =============================================================
{_build_roles_section(config)}

== WORKFLOWS ==============================================================
{_build_workflows_section(config)}

== INTENT -> TOOL MAPPING =================================================
Classify the user's intent, then pick the tool:

  OPERATIONAL  -> run_shell
    Signals: start, stop, restart, status, logs, deploy, kill, check, run,
             git *, docker *, npm *, pip *, test, build, install
    LITERAL COMMAND RULE (highest priority):
      If the user says "run <X> in <shell>" or "run <X>", treat <X> as the
      exact verbatim command. Pass it directly as command=, do not interpret it.
      Example: "run openclaw gateway restart in WSL"
               -> command="openclaw gateway restart", shell="wsl"
      Example: "run git status"
               -> command="git status"
    SERVICES TABLE (second priority):
      If the user mentions a service verb (start/stop/restart/status/logs) on a
      name that IS in the SERVICES table above: copy its exact command.
    BEST-GUESS (fallback when no table match and no literal "run" prefix):
      Construct a command from the name + action -- do NOT ask for clarification.
    The shell= field should match what the user specified ("wsl", "bash", etc.).

  CODE TASK    -> run_cli
    Signals: fix, add, implement, refactor, debug, write code,
              generate, edit file, add feature, add tests
    Requires a project name or path.

  ANALYZE      -> analyze_project
    Signals: evaluate, analyze, assess, critique, review architecture,
             review workflow, review design, find risks, audit completeness
    Use when the main deliverable is an assessment, not code changes.

  READ DOCS    -> read_context or read_files
    Signals: show context, read CLAUDE.md / AGENTS.md / README,
             "what does the context say", "explain the project",
             "show devbot-architecture-v4-final.md"
    Use read_files when the user names explicit files.

  LIST ITEMS   -> list_projects
    Signals: list projects, what projects, show projects

  AMBIGUOUS    -> ask_clarification
    LAST RESORT only -- when it is literally impossible to attempt the task
    without more info (e.g. user says "fix it" with zero context).
    DO NOT ask when:
      - A service name + action are both present (construct a best-guess command)
      - A shell is mentioned (use it)
      - The request is an operational verb on a named thing
    Example: "restart openclaw gateway in WSL" -> run_shell, do NOT ask.

  CHAT         -> (no tool call, reply directly)
    Signals: questions, explanations, how-to, what-is, why-does

== SHELL SAFETY ===========================================================
These commands are blocked and must never be generated:
  rm, rmdir, unlink, shred, mkfs, dd, fdisk, parted, format,
  chmod 777, chmod -R, chown -R, shutdown, reboot, halt, poweroff
If asked for one, explain the block and suggest running it manually.

== CLI ROLES ==============================================================
  Coders (write/edit code):   claude_code, codex
  Reviewers (review/analyze): gemini_cli, qwen_cli
  If the user names a specific CLI, use it. Otherwise pick the best fit for the role.
"""


# Fallback static prompt for when config is not available at import time
ROUTER_SYSTEM_PROMPT = build_system_prompt()
