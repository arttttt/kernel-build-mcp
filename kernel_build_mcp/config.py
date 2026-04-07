"""Build MCP server configuration with named profiles for kernel and Android."""

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


# --- Dataclasses ---


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


@dataclass
class AndroidConfig:
    source_dir: str = ""
    lunch_target: str = ""

    def is_configured(self) -> bool:
        return bool(self.source_dir and self.lunch_target)

    def validate(self) -> list[str]:
        errors = []
        if not self.source_dir:
            errors.append("source_dir is not set")
        elif not Path(self.source_dir).expanduser().is_dir():
            errors.append(f"source_dir does not exist: {self.source_dir}")
        if not self.lunch_target:
            errors.append("lunch_target is not set")
        return errors


# --- Storage ---


def _read_store() -> dict:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        store = {"profiles": {}, "android_profiles": {}}
        CONFIG_FILE.write_text(json.dumps(store, indent=2) + "\n")
        return store
    return json.loads(CONFIG_FILE.read_text())


def _write_store(store: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(store, indent=2) + "\n")


# --- Generic profile operations ---


def _dict_to_dataclass(cls, data: dict):
    """Convert a dict to a dataclass, ignoring unknown fields."""
    known = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in known}
    return cls(**filtered)


def _get_profile(store: dict, name: str, section: str, label: str) -> dict:
    """Get a profile dict by name or raise ValueError."""
    profiles = store.get(section, {})
    if name not in profiles:
        available = ", ".join(profiles.keys()) if profiles else "none"
        raise ValueError(f"{label} '{name}' not found. Available: {available}.")
    return profiles[name]


def _list_section(section: str) -> dict[str, dict]:
    store = _read_store()
    return store.get(section, {})


def _load_from_section(cls, section: str, label: str, name: str):
    store = _read_store()
    return _dict_to_dataclass(cls, _get_profile(store, name, section, label))


def _create_in_section(cls, section: str, name: str, data: dict):
    store = _read_store()
    profiles = store.setdefault(section, {})
    if name in profiles:
        raise ValueError(f"Profile '{name}' already exists.")
    cfg = _dict_to_dataclass(cls, data)
    profiles[name] = asdict(cfg)
    _write_store(store)
    return cfg


def _update_in_section(cls, section: str, label: str, name: str, changes: dict):
    store = _read_store()
    profile_data = _get_profile(store, name, section, label)
    known = {f.name for f in fields(cls)}
    for key, value in changes.items():
        if key in known and value is not None:
            profile_data[key] = value
    _write_store(store)
    return _dict_to_dataclass(cls, profile_data)


def _delete_from_section(section: str, label: str, name: str) -> None:
    store = _read_store()
    _get_profile(store, name, section, label)
    del store[section][name]
    _write_store(store)


# --- Kernel profile API ---

_K_SECTION = "profiles"
_K_LABEL = "Kernel profile"


def list_profiles() -> dict[str, dict]:
    return _list_section(_K_SECTION)

def load_profile(name: str) -> Config:
    return _load_from_section(Config, _K_SECTION, _K_LABEL, name)

def create_profile(name: str, data: dict) -> Config:
    return _create_in_section(Config, _K_SECTION, name, data)

def update_profile(name: str, changes: dict) -> Config:
    return _update_in_section(Config, _K_SECTION, _K_LABEL, name, changes)

def delete_profile(name: str) -> None:
    _delete_from_section(_K_SECTION, _K_LABEL, name)


# --- Android profile API ---

_A_SECTION = "android_profiles"
_A_LABEL = "Android profile"


def list_android_profiles() -> dict[str, dict]:
    return _list_section(_A_SECTION)

def load_android_profile(name: str) -> AndroidConfig:
    return _load_from_section(AndroidConfig, _A_SECTION, _A_LABEL, name)

def create_android_profile(name: str, data: dict) -> AndroidConfig:
    return _create_in_section(AndroidConfig, _A_SECTION, name, data)

def update_android_profile(name: str, changes: dict) -> AndroidConfig:
    return _update_in_section(AndroidConfig, _A_SECTION, _A_LABEL, name, changes)

def delete_android_profile(name: str) -> None:
    _delete_from_section(_A_SECTION, _A_LABEL, name)
