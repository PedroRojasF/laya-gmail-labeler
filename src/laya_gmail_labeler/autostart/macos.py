"""macOS per-user LaunchAgent integration."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from . import AutostartError

LABEL = "com.laya.gmail-labeler"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launchctl(arguments: list[str], *, allow_failure: bool = False) -> int:
    try:
        result = subprocess.run(
            ["launchctl", *arguments],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise AutostartError("macOS LaunchAgents could not be reached.") from None
    if result.returncode and not allow_failure:
        raise AutostartError("macOS could not complete the automatic-startup operation.")
    return result.returncode


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _loaded() -> bool:
    return _launchctl(["print", f"{_domain()}/{LABEL}"], allow_failure=True) == 0


def install(command: list[str]) -> None:
    if _loaded():
        _launchctl(["bootout", f"{_domain()}/{LABEL}"])
    try:
        PLIST_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": command,
                "RunAtLoad": True,
            },
            fmt=plistlib.FMT_XML,
            sort_keys=True,
        )
        PLIST_PATH.write_bytes(payload)
        os.chmod(PLIST_PATH, 0o600)
    except OSError:
        raise AutostartError("The macOS LaunchAgent file could not be written.") from None
    try:
        _launchctl(["bootstrap", _domain(), str(PLIST_PATH)])
    except AutostartError:
        try:
            PLIST_PATH.unlink()
        except OSError:
            pass
        raise


def remove() -> None:
    if _loaded():
        _launchctl(["bootout", f"{_domain()}/{LABEL}"])
    if PLIST_PATH.exists():
        try:
            PLIST_PATH.unlink()
        except OSError:
            raise AutostartError("The macOS LaunchAgent file could not be removed.") from None
