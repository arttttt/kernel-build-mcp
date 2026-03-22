"""Kernel build logic — subprocess execution, make commands, log parsing."""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config

logger = logging.getLogger(__name__)

BUILD_LOG = "/tmp/kernel-build-mcp.log"


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


async def run(cmd: list[str], cwd: str, log_path: str | None = None) -> RunResult:
    """Run a subprocess, capture output. Single entry point for all execution."""
    import asyncio

    expanded_cwd = str(Path(cwd).expanduser())
    logger.info("Running: %s in %s", " ".join(cmd), expanded_cwd)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=expanded_cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    duration = time.monotonic() - start

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if log_path:
        combined = stdout + stderr
        Path(log_path).write_text(combined)

    return RunResult(
        exit_code=proc.returncode or 0,
        stdout=stdout,
        stderr=stderr,
        duration_s=round(duration, 2),
    )


def make_cmd(config: Config, target: str, extra_args: list[str] | None = None) -> list[str]:
    """Build a make command from config. Single source of truth for make invocation."""
    jobs = os.cpu_count() or 4
    cmd = [
        "make",
        f"ARCH={config.arch}",
        f"CROSS_COMPILE={config.cross_compile}",
        f"-j{jobs}",
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(target)
    return cmd


# --- High-level operations ---


async def git_pull(config: Config, branch: str | None = None) -> RunResult:
    """Fetch and pull. Optionally switch branch first."""
    cwd = config.kernel_dir
    # Always fetch first
    fetch = await run(["git", "fetch", "--all"], cwd)
    if fetch.exit_code != 0:
        return fetch

    if branch:
        checkout = await run(["git", "checkout", branch], cwd)
        if checkout.exit_code != 0:
            return checkout

    return await run(["git", "pull"], cwd)


async def git_reset(config: Config, branch: str | None = None) -> RunResult:
    """Fetch and hard reset to remote branch."""
    cwd = config.kernel_dir
    fetch = await run(["git", "fetch", "--all"], cwd)
    if fetch.exit_code != 0:
        return fetch

    if branch:
        checkout = await run(["git", "checkout", branch], cwd)
        if checkout.exit_code != 0:
            return checkout

    # Determine current branch for reset target
    current = await run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    branch_name = current.stdout.strip()
    return await run(["git", "reset", "--hard", f"origin/{branch_name}"], cwd)


async def build(config: Config, target: str = "zImage modules") -> RunResult:
    """Full kernel build."""
    cmd = make_cmd(config, target)
    return await run(cmd, config.kernel_dir, log_path=BUILD_LOG)


async def build_module(config: Config, path: str) -> RunResult:
    """Build a specific module directory."""
    cmd = make_cmd(config, "modules", extra_args=[f"M={path}"])
    return await run(cmd, config.kernel_dir, log_path=BUILD_LOG)


async def defconfig(config: Config, name: str | None = None) -> RunResult:
    """Apply a defconfig."""
    defconfig_name = name or config.defconfig
    cmd = make_cmd(config, defconfig_name)
    return await run(cmd, config.kernel_dir)


async def clean(config: Config, full: bool = False) -> RunResult:
    """Clean build artifacts."""
    target = "mrproper" if full else "clean"
    cmd = make_cmd(config, target)
    return await run(cmd, config.kernel_dir)


async def run_command(config: Config, command: str) -> RunResult:
    """Run an arbitrary shell command in kernel dir."""
    return await run(["bash", "-c", command], config.kernel_dir)


def read_build_log(lines: int = 100, errors_only: bool = False) -> str:
    """Read the last build log."""
    log_path = Path(BUILD_LOG)
    if not log_path.exists():
        return "No build log found. Run a build first."

    content = log_path.read_text()

    if errors_only:
        pattern = re.compile(r"(error|warning|undefined reference|fatal)", re.IGNORECASE)
        filtered = [line for line in content.splitlines() if pattern.search(line)]
        return "\n".join(filtered[-lines:]) if filtered else "No errors or warnings found."

    all_lines = content.splitlines()
    return "\n".join(all_lines[-lines:])


def read_artifact(config: Config, path: str) -> dict:
    """Read a build artifact as base64."""
    full_path = Path(config.kernel_dir).expanduser() / path
    if not full_path.exists():
        return {"error": f"Artifact not found: {path}"}
    if not full_path.is_file():
        return {"error": f"Not a file: {path}"}

    size = full_path.stat().st_size
    data = base64.b64encode(full_path.read_bytes()).decode("ascii")
    return {
        "path": str(full_path),
        "size_bytes": size,
        "base64": data,
    }
