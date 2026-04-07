"""Android/LineageOS/CM build logic — envsetup, lunch, make."""

from __future__ import annotations

import logging
import os

from .builder import RunResult, run
from .config import AndroidConfig

logger = logging.getLogger(__name__)

BUILD_LOG_DIR = "/tmp"


def build_log_path(profile: str) -> str:
    """Return the log file path for an android profile."""
    safe_name = profile.replace("/", "_").replace(" ", "_")
    return f"{BUILD_LOG_DIR}/android-build-mcp-{safe_name}.log"


def _envsetup_cmd(config: AndroidConfig, command: str) -> list[str]:
    """Wrap a command with envsetup + lunch."""
    script = (
        f"source build/envsetup.sh && "
        f"lunch {config.lunch_target} && "
        f"{command}"
    )
    return ["bash", "-c", script]


async def build(config: AndroidConfig, target: str = "bacon", profile: str = "") -> RunResult:
    """Run Android build with envsetup + lunch + make."""
    jobs = os.cpu_count() or 4
    cmd = _envsetup_cmd(config, f"make -j{jobs} {target}")
    return await run(cmd, config.source_dir, log_path=build_log_path(profile))


async def clean(config: AndroidConfig, full: bool = False) -> RunResult:
    """Clean Android build. full=True runs 'make clobber', otherwise 'make clean'."""
    target = "clobber" if full else "clean"
    cmd = _envsetup_cmd(config, f"make {target}")
    return await run(cmd, config.source_dir)


async def run_command(config: AndroidConfig, command: str) -> RunResult:
    """Run an arbitrary command in android source dir with envsetup + lunch sourced."""
    cmd = _envsetup_cmd(config, command)
    return await run(cmd, config.source_dir)


def get_log_info(profile: str) -> dict:
    """Return log file path and metadata."""
    import time
    from pathlib import Path

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
