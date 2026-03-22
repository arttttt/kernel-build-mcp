"""Kernel build logic — subprocess execution, make commands, log parsing."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Awaitable

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
    """Run a subprocess, capture output."""
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
        Path(log_path).write_text(stdout + stderr)

    return RunResult(
        exit_code=proc.returncode or 0,
        stdout=stdout,
        stderr=stderr,
        duration_s=round(duration, 2),
    )


async def run_streaming(
    cmd: list[str],
    cwd: str,
    on_line: Callable[[str], Awaitable[None]],
    log_path: str | None = None,
) -> RunResult:
    """Run a subprocess, stream each line via callback, capture full output."""
    expanded_cwd = str(Path(cwd).expanduser())
    logger.info("Running (streaming): %s in %s", " ".join(cmd), expanded_cwd)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=expanded_cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def read_stream(stream: asyncio.StreamReader, lines: list[str], is_stderr: bool = False):
        while True:
            line_bytes = await stream.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
            lines.append(line)
            await on_line(line)

    await asyncio.gather(
        read_stream(proc.stdout, stdout_lines),
        read_stream(proc.stderr, stderr_lines, is_stderr=True),
    )
    await proc.wait()
    duration = time.monotonic() - start

    stdout = "\n".join(stdout_lines)
    stderr = "\n".join(stderr_lines)

    if log_path:
        Path(log_path).write_text(stdout + "\n" + stderr)

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
    cmd.extend(target.split())
    return cmd


# --- High-level operations ---


async def git_pull(config: Config, branch: str | None = None) -> RunResult:
    """Fetch and pull. Optionally switch branch first."""
    cwd = config.kernel_dir
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

    current = await run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    branch_name = current.stdout.strip()
    return await run(["git", "reset", "--hard", f"origin/{branch_name}"], cwd)


async def build(config: Config, target: str = "zImage modules", on_line: Callable[[str], Awaitable[None]] | None = None) -> RunResult:
    """Full kernel build."""
    cmd = make_cmd(config, target)
    if on_line:
        return await run_streaming(cmd, config.kernel_dir, on_line, log_path=BUILD_LOG)
    return await run(cmd, config.kernel_dir, log_path=BUILD_LOG)


async def build_module(config: Config, path: str, on_line: Callable[[str], Awaitable[None]] | None = None) -> RunResult:
    """Build a specific module directory."""
    cmd = make_cmd(config, "modules", extra_args=[f"M={path}"])
    if on_line:
        return await run_streaming(cmd, config.kernel_dir, on_line, log_path=BUILD_LOG)
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


async def build_boot_img(config: Config) -> RunResult:
    """Build boot.img from zImage + DTB + ramdisk."""
    kdir = Path(config.kernel_dir).expanduser()
    zimage = kdir / "arch" / config.arch / "boot" / "zImage"
    dtb = kdir / "arch" / config.arch / "boot" / "dts" / config.dtb_name
    ramdisk = Path(config.ramdisk).expanduser()
    output = kdir / "boot.img"

    if not zimage.exists():
        return RunResult(1, "", f"zImage not found: {zimage}", 0)
    if not dtb.exists():
        return RunResult(1, "", f"DTB not found: {dtb}", 0)
    if not ramdisk.exists():
        return RunResult(1, "", f"ramdisk not found: {ramdisk}", 0)

    p = config.boot_img_params
    server_dir = Path(__file__).resolve().parent.parent
    mkbootimg_path = server_dir / "mkbootimg"
    if not mkbootimg_path.exists():
        return RunResult(1, "", f"mkbootimg not found at {mkbootimg_path}", 0)
    cmd = [
        str(mkbootimg_path),
        "--kernel", str(zimage),
        "--ramdisk", str(ramdisk),
        "--dt", str(dtb),
        "--base", p["base"],
        "--kernel_offset", p["kernel_offset"],
        "--ramdisk_offset", p["ramdisk_offset"],
        "--tags_offset", p["tags_offset"],
        "--pagesize", p["pagesize"],
        "--cmdline", p["cmdline"],
        "--output", str(output),
    ]
    result = await run(cmd, config.kernel_dir)
    if result.exit_code == 0:
        size = output.stat().st_size
        result.stdout += f"\nboot.img created: {output} ({size} bytes, {size/1024/1024:.1f} MB)"
    return result


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
