"""Cross-platform, per-user automatic startup registration."""

from __future__ import annotations

import platform
import sys
from pathlib import Path


class AutostartError(RuntimeError):
    """Raised when an automatic-startup operation cannot be completed."""


def _watch_command(config_path: Path | None, apply_labels: bool) -> list[str]:
    # Keep the virtual-environment path itself; resolving a symlink on macOS
    # or Linux can escape the environment and lose the installed dependencies.
    command = [str(Path(sys.executable).absolute()), "-m", "laya_gmail_labeler"]
    if config_path is not None:
        command.extend(["--config", str(config_path.expanduser().resolve())])
    command.extend(["watch", "--apply" if apply_labels else "--dry-run"])
    return command


def install_autostart(*, apply_labels: bool, config_path: Path | None) -> None:
    """Install a current-user logon poller for the current desktop platform."""
    system = platform.system()
    command = _watch_command(config_path, apply_labels)
    if system == "Windows":
        from .windows import install
    elif system == "Darwin":
        from .macos import install
    elif system == "Linux":
        from .linux import install
    else:
        raise AutostartError("Automatic startup is supported on Windows, macOS, and Linux desktop systems.")
    install(command)


def remove_autostart() -> None:
    """Stop and remove the current-user logon poller for this platform."""
    system = platform.system()
    if system == "Windows":
        from .windows import remove
    elif system == "Darwin":
        from .macos import remove
    elif system == "Linux":
        from .linux import remove
    else:
        raise AutostartError("Automatic startup is supported on Windows, macOS, and Linux desktop systems.")
    remove()
