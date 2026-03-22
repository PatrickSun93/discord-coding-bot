"""Machine and provider healthchecks for DevBot startup and doctor commands."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from openai import AsyncOpenAI
from devbot.executor.adapters.factory import build_adapter

if TYPE_CHECKING:
    from devbot.config.settings import Config, LLMProviderConfig


_STATUS_ICONS = {
    "ok": "✅",
    "warn": "⚠️",
    "fail": "❌",
    "skip": "⏭️",
}
_CLI_LABELS = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "gemini_cli": "Gemini CLI",
    "qwen_cli": "Qwen CLI",
}


@dataclass
class HealthCheckItem:
    name: str
    status: str
    detail: str
    critical: bool = False

    @property
    def icon(self) -> str:
        return _STATUS_ICONS.get(self.status, "•")


@dataclass
class HealthReport:
    items: list[HealthCheckItem] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
        for item in self.items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    def has_failures(self) -> bool:
        return any(item.status == "fail" for item in self.items)

    def has_critical_failures(self) -> bool:
        return any(item.status == "fail" and item.critical for item in self.items)

    def summary_line(self) -> str:
        counts = self.counts()
        return (
            f"{counts['ok']} ok, {counts['warn']} warn, "
            f"{counts['fail']} fail, {counts['skip']} skipped"
        )


async def run_machine_healthcheck(config: "Config") -> HealthReport:
    cli_checks, primary_provider, fallback_provider = await asyncio.gather(
        _check_cli_agents(config),
        _check_provider(
            config.llm.primary,
            name="Primary LLM",
            critical=True,
        ),
        _check_provider(
            config.llm.fallback,
            name="Fallback LLM",
            critical=False,
        ),
    )
    items = list(cli_checks)
    items.extend([primary_provider, fallback_provider])
    return HealthReport(items=items)


def format_health_report(
    report: HealthReport,
    *,
    title: str = "DevBot Healthcheck",
    markdown: bool = True,
) -> str:
    header = f"**{title}**" if markdown else title
    lines = [header]
    for item in report.items:
        name = f"`{item.name}`" if markdown else item.name
        lines.append(f"{item.icon} {name}: {item.detail}")
    lines.append(f"Summary: {report.summary_line()}")
    return "\n".join(lines)


async def _check_cli_agents(config: "Config") -> list[HealthCheckItem]:
    items: list[HealthCheckItem] = []
    probe_tasks: list[asyncio.Future] = []
    for cli_key, label in _CLI_LABELS.items():
        cli_cfg = getattr(config.cli, cli_key, None)
        if cli_cfg is None:
            items.append(
                HealthCheckItem(
                    name=label,
                    status="fail",
                    detail=f"`{cli_key}` is missing from config.",
                    critical=True,
                )
            )
            continue

        if not cli_cfg.enabled:
            items.append(
                HealthCheckItem(
                    name=label,
                    status="skip",
                    detail="disabled in config",
                )
            )
            continue

        resolved = shutil.which(cli_cfg.command)
        if resolved:
            probe_tasks.append(
                asyncio.create_task(
                    _probe_cli_health(
                        config,
                        cli_key=cli_key,
                        label=label,
                        resolved_path=resolved,
                    )
                )
            )
        else:
            items.append(
                HealthCheckItem(
                    name=label,
                    status="fail",
                    detail=f"`{cli_cfg.command}` is not on PATH",
                    critical=True,
                )
            )
    if probe_tasks:
        items.extend(await asyncio.gather(*probe_tasks))
    return items


async def _check_provider(
    provider_cfg: "LLMProviderConfig",
    *,
    name: str,
    critical: bool,
) -> HealthCheckItem:
    provider = provider_cfg.provider.strip().lower()

    if not provider:
        return HealthCheckItem(
            name=name,
            status="skip",
            detail="provider not configured",
            critical=critical,
        )

    if provider == "minimax":
        return await _check_minimax_provider(provider_cfg, name=name, critical=critical)

    return await _check_openai_compatible_provider(
        provider_cfg,
        name=name,
        critical=critical,
    )


async def _check_minimax_provider(
    provider_cfg: "LLMProviderConfig",
    *,
    name: str,
    critical: bool,
) -> HealthCheckItem:
    if not provider_cfg.api_key:
        return HealthCheckItem(
            name=name,
            status="fail",
            detail=f"MiniMax API key is missing for model `{provider_cfg.model}`",
            critical=critical,
        )

    try:
        preview = await asyncio.to_thread(
            _probe_minimax_model,
            provider_cfg.base_url,
            provider_cfg.api_key,
            provider_cfg.model,
        )
    except Exception as exc:
        return HealthCheckItem(
            name=name,
            status="fail",
            detail=f"MiniMax `{provider_cfg.model}` unavailable: {_short_error(exc)}",
            critical=critical,
        )

    detail = f"MiniMax `{provider_cfg.model}` responded"
    if preview:
        detail += f" ({preview})"
    return HealthCheckItem(
        name=name,
        status="ok",
        detail=detail,
        critical=critical,
    )


async def _check_openai_compatible_provider(
    provider_cfg: "LLMProviderConfig",
    *,
    name: str,
    critical: bool,
) -> HealthCheckItem:
    try:
        models = await _list_openai_models(
            provider_cfg.base_url,
            provider_cfg.api_key or "ollama",
        )
    except Exception as exc:
        return HealthCheckItem(
            name=name,
            status="fail",
            detail=(
                f"{provider_cfg.provider} endpoint unavailable for model "
                f"`{provider_cfg.model}`: {_short_error(exc)}"
            ),
            critical=critical,
        )

    if provider_cfg.model and provider_cfg.model not in models:
        preview = ", ".join(models[:5]) or "(no models reported)"
        return HealthCheckItem(
            name=name,
            status="fail",
            detail=(
                f"{provider_cfg.provider} reachable, but model `{provider_cfg.model}` "
                f"is missing. Available: {preview}"
            ),
            critical=critical,
        )

    detail = f"{provider_cfg.provider} reachable"
    if provider_cfg.model:
        detail += f" with model `{provider_cfg.model}`"
    return HealthCheckItem(
        name=name,
        status="ok",
        detail=detail,
        critical=critical,
    )


def _probe_minimax_model(base_url: str, api_key: str, model: str) -> str:
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url or None,
        timeout=10.0,
        max_retries=0,
    )
    response = client.messages.create(
        model=model,
        max_tokens=8,
        messages=[{"role": "user", "content": "Reply with OK only."}],
    )
    for block in response.content:
        text = getattr(block, "text", "").strip()
        if text:
            return text[:40]
    return ""


async def _list_openai_models(base_url: str, api_key: str) -> list[str]:
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=10.0,
        max_retries=0,
    )
    try:
        response = await client.models.list()
    finally:
        await client.close()
    return [model.id for model in response.data]


async def _probe_cli_health(
    config: "Config",
    *,
    cli_key: str,
    label: str,
    resolved_path: str,
) -> HealthCheckItem:
    cli_cfg = getattr(config.cli, cli_key)
    try:
        adapter = build_adapter(cli_key, config)
        command = adapter.build_command("Reply with exactly OK and nothing else.", str(Path.cwd()))
    except Exception as exc:
        return HealthCheckItem(
            name=label,
            status="fail",
            detail=f"probe setup failed for `{cli_cfg.command}`: {_short_error(exc)}",
            critical=True,
        )

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as exc:
        return HealthCheckItem(
            name=label,
            status="fail",
            detail=f"`{cli_cfg.command}` failed to start: {_short_error(exc)}",
            critical=True,
        )

    try:
        output_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=45)
    except asyncio.TimeoutError:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        return HealthCheckItem(
            name=label,
            status="fail",
            detail=f"`{cli_cfg.command}` timed out during live probe",
            critical=True,
        )

    output = (output_bytes or b"").decode(errors="replace").strip()
    if process.returncode != 0:
        return HealthCheckItem(
            name=label,
            status="fail",
            detail=(
                f"`{cli_cfg.command}` found at `{resolved_path}` but live probe failed: "
                f"{_short_error(RuntimeError(output or f'exit {process.returncode}'))}"
            ),
            critical=True,
        )

    detail = f"`{cli_cfg.command}` ready at `{resolved_path}`"
    preview = _first_output_line(output)
    if preview:
        detail += f" ({preview})"
    return HealthCheckItem(
        name=label,
        status="ok",
        detail=detail,
        critical=True,
    )


def _short_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return error.__class__.__name__
    return message.replace("\n", " ")[:220]


def _first_output_line(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return ""
