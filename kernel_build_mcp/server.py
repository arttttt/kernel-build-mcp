"""MCP server for remote kernel builds. Tool definitions only — logic in builder/config."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from . import builder, config

# Logging to stderr (stdio transport — stdout is for JSON-RPC)
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

mcp = FastMCP("kernel-build")


def _require_config() -> config.Config:
    """Load config and raise if not configured."""
    cfg = config.load()
    if not cfg.is_configured():
        raise ValueError(
            "Server not configured. Use set_config to set kernel_dir and cross_compile first.\n"
            f"Config file: {config.CONFIG_FILE}"
        )
    return cfg


def _format_result(result: builder.RunResult) -> str:
    """Format RunResult for MCP response."""
    parts = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(f"--- stderr ---\n{result.stderr}")
    parts.append(f"\n[exit_code={result.exit_code}, duration={result.duration_s}s]")
    return "\n".join(parts)


# --- Config tools ---


@mcp.tool()
async def get_config() -> str:
    """Show current server configuration."""
    cfg = config.load()
    data = asdict(cfg)
    data["config_file"] = str(config.CONFIG_FILE)
    data["is_configured"] = cfg.is_configured()
    errors = cfg.validate()
    if errors:
        data["validation_errors"] = errors
    return json.dumps(data, indent=2)


@mcp.tool()
async def set_config(
    kernel_dir: str | None = None,
    cross_compile: str | None = None,
    arch: str | None = None,
    defconfig: str | None = None,
) -> str:
    """Update server configuration. Only provided fields are changed.

    Args:
        kernel_dir: Absolute path to kernel source directory on this machine
        cross_compile: Full path to cross-compiler prefix (e.g. /opt/toolchain/bin/arm-linux-gnueabihf-)
        arch: Target architecture (default: arm)
        defconfig: Default defconfig name (default: mocha_android_defconfig)
    """
    changes = {
        "kernel_dir": kernel_dir,
        "cross_compile": cross_compile,
        "arch": arch,
        "defconfig": defconfig,
    }
    cfg = config.update(changes)
    errors = cfg.validate()
    result = asdict(cfg)
    if errors:
        result["validation_errors"] = errors
    else:
        result["status"] = "ok"
    return json.dumps(result, indent=2)


# --- Git tools ---


@mcp.tool()
async def git_pull(branch: str | None = None) -> str:
    """Fetch and pull latest changes. Optionally switch to a different branch first.

    Args:
        branch: Branch to checkout before pulling (optional, stays on current if omitted)
    """
    cfg = _require_config()
    result = await builder.git_pull(cfg, branch)
    return _format_result(result)


@mcp.tool()
async def git_reset(branch: str | None = None) -> str:
    """Fetch and hard reset to remote state. Discards all local changes.

    Args:
        branch: Branch to reset to (optional, uses current branch if omitted)
    """
    cfg = _require_config()
    result = await builder.git_reset(cfg, branch)
    return _format_result(result)


# --- Build tools ---


@mcp.tool()
async def build(target: str = "zImage modules") -> str:
    """Run kernel build. Output is saved to build log.

    Args:
        target: Make target(s) (default: "zImage modules")
    """
    cfg = _require_config()
    result = await builder.build(cfg, target)
    return _format_result(result)


@mcp.tool()
async def build_module(path: str) -> str:
    """Build a specific kernel module directory.

    Args:
        path: Path relative to kernel root (e.g. "drivers/media/platform/tegra/")
    """
    cfg = _require_config()
    result = await builder.build_module(cfg, path)
    return _format_result(result)


@mcp.tool()
async def make_defconfig(defconfig: str | None = None) -> str:
    """Apply a kernel defconfig.

    Args:
        defconfig: Defconfig name (uses configured default if omitted)
    """
    cfg = _require_config()
    result = await builder.defconfig(cfg, defconfig)
    return _format_result(result)


@mcp.tool()
async def clean(full: bool = False) -> str:
    """Clean build artifacts.

    Args:
        full: If true, runs mrproper (removes .config too). Otherwise just clean.
    """
    cfg = _require_config()
    result = await builder.clean(cfg, full)
    return _format_result(result)


# --- Result tools ---


@mcp.tool()
async def get_build_log(lines: int = 100, errors_only: bool = False) -> str:
    """Get the last build log output.

    Args:
        lines: Number of lines to return from the end (default: 100)
        errors_only: If true, only show error and warning lines
    """
    return builder.read_build_log(lines, errors_only)


@mcp.tool()
async def get_artifact(path: str) -> str:
    """Get a build artifact as base64-encoded data.

    Args:
        path: Path relative to kernel root (e.g. "arch/arm/boot/zImage")
    """
    cfg = _require_config()
    result = builder.read_artifact(cfg, path)
    return json.dumps(result, indent=2)


# --- Shell tool ---


@mcp.tool()
async def run_command(command: str) -> str:
    """Run an arbitrary shell command in the kernel source directory.

    Args:
        command: Shell command to execute
    """
    cfg = _require_config()
    result = await builder.run_command(cfg, command)
    return _format_result(result)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
