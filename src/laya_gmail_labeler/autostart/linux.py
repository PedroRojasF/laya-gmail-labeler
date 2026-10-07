"""Linux per-user systemd integration for desktop sessions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import AutostartError

UNIT_NAME = "laya-gmail-labeler.service"


def _unit_path() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(configured).expanduser() if configured else Path.home() / ".config"
    if not config_home.is_absolute():
        config_home = Path.home() / ".config"
    return config_home / "systemd" / "user" / UNIT_NAME


def _run(arguments: list[str], *, allowed_codes: set[int] | None = None) -> int:
    allowed = allowed_codes or {0}
    try:
        result = subprocess.run(
            ["systemctl", "--user", *arguments],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise AutostartError("The current user's systemd service manager is unavailable.") from None
    if result.returncode not in allowed:
        raise AutostartError("The current user's systemd service manager could not complete the operation.")
    return result.returncode


def _escape_argument(value: str) -> str:
    if any(character in value for character in "\n\r\0"):
        raise AutostartError("A startup argument contains an unsupported control character.")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$").replace("%", "%%")
    return f'"{escaped}"'


def _unit_content(command: list[str]) -> str:
    executable_and_arguments = " ".join(_escape_argument(argument) for argument in command)
    return (
        "[Unit]\n"
        "Description=Local Laya Gmail labeler\n\n"
        "After=graphical-session.target\n"
        "PartOf=graphical-session.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={executable_and_arguments}\n\n"
        "Restart=on-failure\n"
        "RestartSec=30s\n\n"
        "[Install]\n"
        "WantedBy=graphical-session.target\n"
    )


def install(command: list[str]) -> None:
    unit_path = _unit_path()
    # Clean up a stale loaded service even if its old unit file was removed.
    remove()
    try:
        unit_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        unit_path.write_text(_unit_content(command), encoding="utf-8")
        os.chmod(unit_path, 0o600)
    except OSError:
        raise AutostartError("The Linux user service file could not be written.") from None
    try:
        _run(["daemon-reload"])
        _run(["enable", UNIT_NAME])
        # Start in the current login only after the desktop has brought up its
        # graphical target and session keyring. Otherwise, the enabled link
        # starts the service on the next graphical login.
        if _run(["is-active", "graphical-session.target"], allowed_codes={0, 3, 4}) == 0:
            _run(["start", UNIT_NAME])
    except AutostartError:
        for action in (
            ["disable", "--now", UNIT_NAME],
            ["stop", UNIT_NAME],
            ["daemon-reload"],
        ):
            try:
                _run(action, allowed_codes={0, 1, 3, 4})
            except AutostartError:
                pass
        try:
            unit_path.unlink()
        except OSError:
            pass
        raise


def remove() -> None:
    unit_path = _unit_path()
    active_status = _run(["is-active", UNIT_NAME], allowed_codes={0, 3, 4})
    # Stop any loaded state, including activating/restarting. is-active uses
    # status 4 only when the unit is not known to this user manager.
    if active_status != 4:
        _run(["stop", UNIT_NAME])
    enabled_status = _run(["is-enabled", UNIT_NAME], allowed_codes={0, 1, 4})
    if enabled_status == 0:
        _run(["disable", UNIT_NAME])
    if unit_path.exists():
        try:
            unit_path.unlink()
        except OSError:
            raise AutostartError("The Linux user service file could not be removed.") from None
        _run(["daemon-reload"])
