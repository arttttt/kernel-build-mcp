"""MCP server for remote kernel builds. Stateless, profile-based."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import builder, config

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

mcp = FastMCP("kernel-build")


def _require_profile(profile: str) -> config.Config:
    """Load and validate a profile. Raises on missing or misconfigured profile."""
    cfg = config.load_profile(profile)
    if not cfg.is_configured():
        raise ValueError(
            f"Profile '{profile}' is not fully configured (missing kernel_dir or cross_compile). "
            "Use set_config() to fix it."
        )
    return cfg


def _build_summary(result: builder.RunResult, log_path: str) -> str:
    """Format build result as a compact summary."""
    if result.exit_code == 0:
        return (
            f"Build OK ({result.duration_s}s).\n"
            f"Log: {log_path}"
        )
    # On failure — include error lines from log
    error_lines = _extract_errors_from_log(log_path)
    parts = [
        f"Build FAILED (exit {result.exit_code}, {result.duration_s}s).",
        f"Log: {log_path}",
    ]
    if error_lines:
        parts.append(f"\n--- Errors ---\n{error_lines}")
    if result.stderr:
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:])
        parts.append(f"\n--- stderr (last 20 lines) ---\n{stderr_tail}")
    return "\n".join(parts)


def _extract_errors_from_log(log_path: str) -> str:
    """Extract error/warning lines from a build log file."""
    p = Path(log_path)
    if not p.exists():
        return ""
    content = p.read_text()
    pattern = re.compile(r"(error|undefined reference|fatal)", re.IGNORECASE)
    filtered = [line for line in content.splitlines() if pattern.search(line)]
    if not filtered:
        return ""
    return "\n".join(filtered[-50:])


def _format_result(result: builder.RunResult) -> str:
    """Format RunResult for non-build commands."""
    parts = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(f"--- stderr ---\n{result.stderr}")
    parts.append(f"\n[exit_code={result.exit_code}, duration={result.duration_s}s]")
    return "\n".join(parts)


def _profile_response(cfg: config.Config, name: str, status: str) -> str:
    """Format a profile config as JSON response with validation info."""
    result = asdict(cfg)
    result["name"] = name
    result["status"] = status
    errors = cfg.validate()
    if errors:
        result["validation_errors"] = errors
    return json.dumps(result, indent=2)


# --- Profile management tools ---


@mcp.tool()
async def list_profiles() -> str:
    """List all available kernel build profiles with their configuration.

    Returns a JSON object with all profiles. Each profile contains:
    kernel_dir, cross_compile, arch, defconfig, dtb_name, ramdisk.

    Example: list_profiles()
    """
    profiles = config.list_profiles()
    if not profiles:
        return "No profiles configured. Use create_profile() to add one."
    return json.dumps(profiles, indent=2)


@mcp.tool()
async def create_profile(
    name: str,
    kernel_dir: str,
    cross_compile: str,
    arch: str = "arm",
    defconfig: str = "",
    dtb_name: str = "",
    ramdisk: str = "",
) -> str:
    """Create a new kernel build profile.

    Args:
        name: Unique profile name (e.g. "SmokeR24.1", "Stock")
        kernel_dir: Absolute path to kernel source on this machine
        cross_compile: Absolute path to cross-compiler prefix
        arch: Target architecture (default: arm)
        defconfig: Defconfig name (e.g. "tegra12_android_defconfig")
        dtb_name: DTB filename (e.g. "tegra124-mocha.dtb")
        ramdisk: Path to ramdisk.img for boot.img assembly (optional)

    Example: create_profile(name="Stock", kernel_dir="/home/user/kernel", cross_compile="/opt/toolchain/bin/arm-linux-gnueabihf-", defconfig="mocha_user_defconfig")
    """
    data = {
        "kernel_dir": kernel_dir,
        "cross_compile": cross_compile,
        "arch": arch,
        "defconfig": defconfig,
        "dtb_name": dtb_name,
        "ramdisk": ramdisk,
    }
    cfg = config.create_profile(name, data)
    return _profile_response(cfg, name, "created")


@mcp.tool()
async def delete_profile(name: str) -> str:
    """Delete a kernel build profile.

    Args:
        name: Profile name to delete. Use list_profiles() to see available profiles.

    Example: delete_profile(name="Stock")
    """
    config.delete_profile(name)
    return f"Profile '{name}' deleted."


@mcp.tool()
async def set_config(
    profile: str,
    kernel_dir: str | None = None,
    cross_compile: str | None = None,
    arch: str | None = None,
    defconfig: str | None = None,
    dtb_name: str | None = None,
    ramdisk: str | None = None,
) -> str:
    """Update configuration of an existing profile. Only provided fields are changed.

    Args:
        profile: Profile name to update. Required. Use list_profiles() to see available profiles.
        kernel_dir: Absolute path to kernel source on this machine
        cross_compile: Absolute path to cross-compiler prefix
        arch: Target architecture
        defconfig: Defconfig name
        dtb_name: DTB filename
        ramdisk: Path to ramdisk.img

    Example: set_config(profile="SmokeR24.1", defconfig="tegra12_android_defconfig")
    """
    changes = {
        "kernel_dir": kernel_dir,
        "cross_compile": cross_compile,
        "arch": arch,
        "defconfig": defconfig,
        "dtb_name": dtb_name,
        "ramdisk": ramdisk,
    }
    cfg = config.update_profile(profile, changes)
    return _profile_response(cfg, profile, "updated")


# --- Git tools ---


@mcp.tool()
async def git_pull(profile: str, branch: str | None = None) -> str:
    """Fetch and pull latest changes in the kernel source directory.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.
        branch: Branch to checkout before pulling (optional, stays on current if omitted)

    Example: git_pull(profile="SmokeR24.1", branch="main")
    """
    cfg = _require_profile(profile)
    result = await builder.git_pull(cfg, branch)
    return _format_result(result)


@mcp.tool()
async def git_reset(profile: str, branch: str | None = None) -> str:
    """Fetch and hard reset to remote state. Discards all local changes.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.
        branch: Branch to reset to (optional, uses current branch if omitted)

    Example: git_reset(profile="Stock")
    """
    cfg = _require_profile(profile)
    result = await builder.git_reset(cfg, branch)
    return _format_result(result)


# --- Build tools ---


@mcp.tool()
async def build(profile: str, target: str = "zImage modules") -> str:
    """Run kernel build. Output is saved to a log file (path returned in response).

    The full build log is NOT included in the response to save context.
    On success: returns summary with duration and log path.
    On failure: returns exit code, error lines from the log, and log path.
    To analyze the full log, download it via scp and use grep/rg locally.

    The build process will be terminated if this tool call is cancelled.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.
        target: Make target(s) (default: "zImage modules")

    Example: build(profile="SmokeR24.1", target="zImage modules")
    """
    cfg = _require_profile(profile)
    log_path = builder.build_log_path(profile)
    result = await builder.build(cfg, target, profile=profile)
    return _build_summary(result, log_path)


@mcp.tool()
async def build_module(profile: str, path: str) -> str:
    """Build a specific kernel module directory. Output is saved to a log file.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.
        path: Path relative to kernel root (e.g. "drivers/media/platform/tegra/")

    Example: build_module(profile="SmokeR24.1", path="drivers/media/platform/tegra/")
    """
    cfg = _require_profile(profile)
    log_path = builder.build_log_path(profile)
    result = await builder.build_module(cfg, path, profile=profile)
    return _build_summary(result, log_path)


@mcp.tool()
async def make_defconfig(profile: str, defconfig: str | None = None) -> str:
    """Apply a kernel defconfig. Uses the profile's default defconfig if not specified.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.
        defconfig: Defconfig name (uses profile default if omitted)

    Example: make_defconfig(profile="SmokeR24.1")
    """
    cfg = _require_profile(profile)
    result = await builder.defconfig(cfg, defconfig)
    return _format_result(result)


@mcp.tool()
async def clean(profile: str, full: bool = False) -> str:
    """Clean build artifacts in the kernel source directory.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.
        full: If true, runs mrproper (removes .config too). Otherwise just clean.

    Example: clean(profile="Stock", full=True)
    """
    cfg = _require_profile(profile)
    result = await builder.clean(cfg, full)
    return _format_result(result)


@mcp.tool()
async def build_boot_img(profile: str) -> str:
    """Build boot.img from zImage + DTB + ramdisk.

    Requires ramdisk path to be set in profile config. Uses zImage and DTB
    from the last kernel build. Output: boot.img in kernel dir root.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.

    Example: build_boot_img(profile="SmokeR24.1")
    """
    cfg = _require_profile(profile)
    if not cfg.ramdisk:
        return f"Error: ramdisk path not set for profile '{profile}'. Use set_config(profile=\"{profile}\", ramdisk='/path/to/ramdisk.img')"
    result = await builder.build_boot_img(cfg)
    return _format_result(result)


# --- Utility tools ---


@mcp.tool()
async def run_command(profile: str, command: str) -> str:
    """Run an arbitrary shell command in the kernel source directory.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.
        command: Shell command to execute

    Example: run_command(profile="SmokeR24.1", command="ls arch/arm/boot/")
    """
    cfg = _require_profile(profile)
    result = await builder.run_command(cfg, command)
    return _format_result(result)


@mcp.tool()
async def get_build_log_path(profile: str) -> str:
    """Check if a build log exists for the profile and return its path and metadata.

    Returns log file path, size in bytes, and last modified time.
    Use this to check if a build log is available before downloading it via scp.

    Args:
        profile: Kernel profile name. Required. Use list_profiles() to see available profiles.

    Example: get_build_log_path(profile="SmokeR24.1")
    """
    info = builder.get_log_info(profile)
    return json.dumps(info, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
