"""Kernel build logic — subprocess execution, make commands, process management."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config

logger = logging.getLogger(__name__)

BUILD_LOG_DIR = "/tmp"


def build_log_path(profile: str) -> str:
    """Return the log file path for a given profile."""
    safe_name = profile.replace("/", "_").replace(" ", "_")
    return f"{BUILD_LOG_DIR}/kernel-build-mcp-{safe_name}.log"


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


async def run(cmd: list[str], cwd: str, log_path: str | None = None) -> RunResult:
    """Run a subprocess, capture output. Kills process group on cancellation."""
    expanded_cwd = str(Path(cwd).expanduser())
    logger.info("Running: %s in %s", " ".join(cmd), expanded_cwd)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=expanded_cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = await proc.communicate()
    except asyncio.CancelledError:
        _kill_process_group(proc)
        await proc.wait()
        raise

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


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Send SIGTERM to the entire process group."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        logger.info("Sent SIGTERM to process group %d", proc.pid)
    except ProcessLookupError:
        pass
    except OSError as e:
        logger.warning("Failed to kill process group %d: %s", proc.pid, e)


def make_cmd(config: Config, target: str, extra_args: list[str] | None = None) -> list[str]:
    """Build a make command from config."""
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


async def build(config: Config, target: str = "zImage", profile: str = "") -> RunResult:
    """Full kernel build."""
    if "zImage" in target.split() and config.dtb_name and config.dtb_name not in target:
        target = f"{target} {config.dtb_name}"
    cmd = make_cmd(config, target)
    return await run(cmd, config.kernel_dir, log_path=build_log_path(profile))


async def build_module(config: Config, path: str, profile: str = "") -> RunResult:
    """Build a specific module directory."""
    cmd = make_cmd(config, "modules", extra_args=[f"M={path}"])
    return await run(cmd, config.kernel_dir, log_path=build_log_path(profile))


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


def get_log_info(profile: str) -> dict:
    """Return log file path and metadata (size, mtime). None values if log doesn't exist."""
    path = build_log_path(profile)
    p = Path(path)
    if not p.exists():
        return {"path": path, "exists": False}
    stat = p.stat()
    return {
        "path": path,
        "exists": True,
        "size_bytes": stat.st_size,
        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
    }
