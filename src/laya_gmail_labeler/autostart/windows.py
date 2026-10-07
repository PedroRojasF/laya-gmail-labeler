"""Windows Task Scheduler integration for the current user."""

from __future__ import annotations

import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import AutostartError

TASK_NAME = "Laya Gmail Labeler"
TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _task_xml(command: list[str], account: str) -> bytes:
    """Build a per-user interactive task with an unlimited, battery-safe run."""
    ET.register_namespace("", TASK_NAMESPACE)
    task = ET.Element(f"{{{TASK_NAMESPACE}}}Task", {"version": "1.2"})
    registration = ET.SubElement(task, f"{{{TASK_NAMESPACE}}}RegistrationInfo")
    ET.SubElement(registration, f"{{{TASK_NAMESPACE}}}Description").text = (
        "Local Gmail label classification for the current user."
    )
    triggers = ET.SubElement(task, f"{{{TASK_NAMESPACE}}}Triggers")
    logon = ET.SubElement(triggers, f"{{{TASK_NAMESPACE}}}LogonTrigger")
    ET.SubElement(logon, f"{{{TASK_NAMESPACE}}}Enabled").text = "true"
    ET.SubElement(logon, f"{{{TASK_NAMESPACE}}}UserId").text = account
    principals = ET.SubElement(task, f"{{{TASK_NAMESPACE}}}Principals")
    principal = ET.SubElement(principals, f"{{{TASK_NAMESPACE}}}Principal", {"id": "Author"})
    ET.SubElement(principal, f"{{{TASK_NAMESPACE}}}UserId").text = account
    ET.SubElement(principal, f"{{{TASK_NAMESPACE}}}LogonType").text = "InteractiveToken"
    ET.SubElement(principal, f"{{{TASK_NAMESPACE}}}RunLevel").text = "LeastPrivilege"
    settings = ET.SubElement(task, f"{{{TASK_NAMESPACE}}}Settings")
    setting_values = (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("AllowHardTerminate", "true"),
        ("StartWhenAvailable", "true"),
        ("AllowStartOnDemand", "true"),
        ("Enabled", "true"),
        ("Hidden", "false"),
        ("RunOnlyIfIdle", "false"),
        ("WakeToRun", "false"),
        ("ExecutionTimeLimit", "PT0S"),
        ("Priority", "7"),
    )
    for name, value in setting_values:
        ET.SubElement(settings, f"{{{TASK_NAMESPACE}}}{name}").text = value
    actions = ET.SubElement(task, f"{{{TASK_NAMESPACE}}}Actions", {"Context": "Author"})
    execute = ET.SubElement(actions, f"{{{TASK_NAMESPACE}}}Exec")
    ET.SubElement(execute, f"{{{TASK_NAMESPACE}}}Command").text = command[0]
    ET.SubElement(execute, f"{{{TASK_NAMESPACE}}}Arguments").text = subprocess.list2cmdline(command[1:])
    ET.SubElement(execute, f"{{{TASK_NAMESPACE}}}WorkingDirectory").text = str(Path(command[0]).parent)
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def _run(arguments: list[str], *, allow_failure: bool = False) -> int:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        raise AutostartError("Windows Task Scheduler could not be reached.") from None
    if result.returncode and not allow_failure:
        raise AutostartError("Windows Task Scheduler could not complete the requested operation.")
    return result.returncode


def install(command: list[str]) -> None:
    username = os.environ.get("USERNAME")
    if not username:
        raise AutostartError("Could not identify the current Windows user for automatic startup.")
    domain = os.environ.get("USERDOMAIN")
    account = f"{domain}\\{username}" if domain else username
    query_status = _run(["schtasks.exe", "/Query", "/TN", TASK_NAME], allow_failure=True)
    if query_status == 0:
        _run(["schtasks.exe", "/End", "/TN", TASK_NAME], allow_failure=True)
        _run(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"])
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="laya-gmail-labeler-", suffix=".xml", delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(_task_xml(command, account))
        _run(["schtasks.exe", "/Create", "/TN", TASK_NAME, "/XML", str(temporary_path), "/F"])
    except OSError:
        raise AutostartError("The Windows startup task could not be prepared.") from None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def remove() -> None:
    query_status = _run(["schtasks.exe", "/Query", "/TN", TASK_NAME], allow_failure=True)
    if query_status:
        raise AutostartError("The current user's Laya Gmail Labeler task could not be found or queried.")
    # /End returns a failure when the task is registered but not currently running.
    _run(["schtasks.exe", "/End", "/TN", TASK_NAME], allow_failure=True)
    _run(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"])
