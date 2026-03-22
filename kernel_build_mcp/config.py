"""Kernel build MCP server configuration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "kernel-build-mcp"
CONFIG_FILE = CONFIG_DIR / "config.json"

_DEFAULTS = {
    "kernel_dir": "",
    "cross_compile": "",
    "arch": "arm",
    "defconfig": "mocha_android_defconfig",
}


@dataclass
class Config:
    kernel_dir: str = ""
    cross_compile: str = ""
    arch: str = "arm"
    defconfig: str = "mocha_android_defconfig"

    def is_configured(self) -> bool:
        return bool(self.kernel_dir and self.cross_compile)

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errors = []
        if not self.kernel_dir:
            errors.append("kernel_dir is not set")
        elif not Path(self.kernel_dir).expanduser().is_dir():
            errors.append(f"kernel_dir does not exist: {self.kernel_dir}")
        if not self.cross_compile:
            errors.append("cross_compile is not set")
        if not self.arch:
            errors.append("arch is not set")
        if not self.defconfig:
            errors.append("defconfig is not set")
        return errors


def load() -> Config:
    """Load config from disk. Creates default config if missing."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(_DEFAULTS, indent=2) + "\n")
        return Config(**_DEFAULTS)
    data = json.loads(CONFIG_FILE.read_text())
    known_fields = {f.name for f in fields(Config)}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return Config(**{**_DEFAULTS, **filtered})


def save(config: Config) -> None:
    """Save config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(config), indent=2) + "\n")


def update(changes: dict) -> Config:
    """Load config, apply changes, validate, save, return updated config."""
    config = load()
    known_fields = {f.name for f in fields(Config)}
    for key, value in changes.items():
        if key in known_fields and value is not None:
            setattr(config, key, value)
    save(config)
    return config
