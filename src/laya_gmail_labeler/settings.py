"""Load and validate the local, non-secret application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

LABELS: dict[str, str] = {
    "action": "IA/Acción",
    "receipts": "IA/Recibos",
    "newsletters": "IA/Boletines",
    "work": "IA/Trabajo",
    "personal": "IA/Personal",
    "spam": "IA/Spam",
}
POLL_INTERVAL_SECONDS = 60
MAX_EXCERPT_CHARS = 3000
DEFAULT_CONFIDENCE_THRESHOLD = 0.90


@dataclass(frozen=True)
class AppConfig:
    state_dir: Path
    credentials_file: Path
    apply_labels: bool = False
    interval_seconds: int = POLL_INTERVAL_SECONDS
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    max_excerpt_chars: int = MAX_EXCERPT_CHARS
    labels: dict[str, str] | None = None


def local_data_dir() -> Path:
    """Return the per-user Windows app-data directory."""
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise RuntimeError("LOCALAPPDATA is unavailable; this app is intended for Windows.")
    return Path(root) / "LayaGmailLabeler"


def _expand_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path")
    expanded = os.path.expandvars(value.strip())
    if "$" in expanded or "%" in expanded:
        raise ValueError(f"{field} contains an environment variable that could not be expanded")
    return Path(expanded).expanduser()


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        value = tomllib.load(stream)
    if not isinstance(value, dict):
        raise ValueError("Configuration root must be a TOML table")
    return value


def load_config(config_path: Path | None = None, apply_override: bool | None = None) -> AppConfig:
    """Load a config file if present, otherwise use safe built-in defaults."""
    default_dir = local_data_dir()
    path = config_path or (default_dir / "config.toml")
    raw = _read_toml(path) if path.exists() else {}
    app = raw.get("app", {})
    polling = raw.get("polling", {})
    classification = raw.get("classification", {})
    configured_labels = raw.get("labels", dict(LABELS))
    if not all(isinstance(section, dict) for section in (app, polling, classification, configured_labels)):
        raise ValueError("app, polling, classification, and labels must be TOML tables")

    if set(configured_labels) != set(LABELS) or any(configured_labels.get(key) != value for key, value in LABELS.items()):
        raise ValueError("The six Gmail label names are fixed and cannot be changed in config.toml")

    apply_value = app.get("apply_labels", False)
    if not isinstance(apply_value, bool):
        raise ValueError("app.apply_labels must be true or false")
    if apply_override is not None:
        apply_value = apply_override

    interval = polling.get("interval_seconds", POLL_INTERVAL_SECONDS)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval != POLL_INTERVAL_SECONDS:
        raise ValueError("polling.interval_seconds must be 60")

    threshold = classification.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.0 < threshold <= 1.0:
        raise ValueError("classification.confidence_threshold must be greater than 0 and at most 1")

    excerpt_limit = classification.get("max_excerpt_chars", MAX_EXCERPT_CHARS)
    if not isinstance(excerpt_limit, int) or isinstance(excerpt_limit, bool) or not 1 <= excerpt_limit <= MAX_EXCERPT_CHARS:
        raise ValueError(f"classification.max_excerpt_chars must be between 1 and {MAX_EXCERPT_CHARS}")

    state_dir = _expand_path(app.get("state_dir", str(default_dir)), "app.state_dir")
    credentials_file = _expand_path(app.get("credentials_file", str(default_dir / "credentials.json")), "app.credentials_file")
    return AppConfig(
        state_dir=state_dir,
        credentials_file=credentials_file,
        apply_labels=apply_value,
        interval_seconds=interval,
        confidence_threshold=float(threshold),
        max_excerpt_chars=excerpt_limit,
        labels=dict(LABELS),
    )