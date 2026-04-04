"""Kernel build MCP server configuration with named profiles."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

CONFIG_DIR = Path("~/.config/kernel-build-mcp").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"

_DEFAULT_BOOT_IMG_PARAMS = {
    "base": "0x10000000",
    "kernel_offset": "0x00008000",
    "ramdisk_offset": "0x02000000",
    "tags_offset": "0x00000100",
    "pagesize": "2048",
    "cmdline": "vpr_resize androidboot.selinux=permissive buildvariant=userdebug",
}


@dataclass
class Config:
    kernel_dir: str = ""
    cross_compile: str = ""
    arch: str = "arm"
    defconfig: str = ""
    ramdisk: str = ""
    dtb_name: str = "tegra124-mocha.dtb"
    boot_img_params: dict = None

    def __post_init__(self):
        if self.boot_img_params is None:
            self.boot_img_params = dict(_DEFAULT_BOOT_IMG_PARAMS)

    def is_configured(self) -> bool:
        return bool(self.kernel_dir and self.cross_compile)

    def validate(self) -> list[str]:
        errors = []
        if not self.kernel_dir:
            errors.append("kernel_dir is not set")
        elif not Path(self.kernel_dir).expanduser().is_dir():
            errors.append(f"kernel_dir does not exist: {self.kernel_dir}")
        if not self.cross_compile:
            errors.append("cross_compile is not set")
        if not self.arch:
            errors.append("arch is not set")
        return errors


def _read_store() -> dict:
    """Read raw config file. Returns {"profiles": {...}}."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        store = {"profiles": {}}
        CONFIG_FILE.write_text(json.dumps(store, indent=2) + "\n")
        return store
    return json.loads(CONFIG_FILE.read_text())


def _write_store(store: dict) -> None:
    """Write raw config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(store, indent=2) + "\n")


def _dict_to_config(data: dict) -> Config:
    """Convert a profile dict to Config, ignoring unknown fields."""
    known = {f.name for f in fields(Config)}
    filtered = {k: v for k, v in data.items() if k in known}
    cfg = Config(**filtered)
    return cfg


def list_profiles() -> dict[str, dict]:
    """Return all profiles as {name: config_dict}."""
    store = _read_store()
    return store.get("profiles", {})


def load_profile(name: str) -> Config:
    """Load a specific profile by name. Raises ValueError if not found."""
    store = _read_store()
    profiles = store.get("profiles", {})
    if name not in profiles:
        available = ", ".join(profiles.keys()) if profiles else "none"
        raise ValueError(
            f"Profile '{name}' not found. Available profiles: {available}. "
            "Use list_profiles() to see all profiles."
        )
    return _dict_to_config(profiles[name])


def create_profile(name: str, data: dict) -> Config:
    """Create a new profile. Raises ValueError if name already exists."""
    store = _read_store()
    profiles = store.setdefault("profiles", {})
    if name in profiles:
        raise ValueError(f"Profile '{name}' already exists. Use set_config() to update it.")
    cfg = _dict_to_config(data)
    profiles[name] = asdict(cfg)
    _write_store(store)
    return cfg


def update_profile(name: str, changes: dict) -> Config:
    """Update fields of an existing profile. Only non-None values are applied."""
    store = _read_store()
    profiles = store.get("profiles", {})
    if name not in profiles:
        available = ", ".join(profiles.keys()) if profiles else "none"
        raise ValueError(
            f"Profile '{name}' not found. Available profiles: {available}. "
            "Use list_profiles() to see all profiles."
        )
    known = {f.name for f in fields(Config)}
    for key, value in changes.items():
        if key in known and value is not None:
            profiles[name][key] = value
    _write_store(store)
    return _dict_to_config(profiles[name])


def delete_profile(name: str) -> None:
    """Delete a profile by name. Raises ValueError if not found."""
    store = _read_store()
    profiles = store.get("profiles", {})
    if name not in profiles:
        available = ", ".join(profiles.keys()) if profiles else "none"
        raise ValueError(
            f"Profile '{name}' not found. Available profiles: {available}."
        )
    del profiles[name]
    _write_store(store)
