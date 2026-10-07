# Cross-Platform Desktop Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing local Gmail labeler usable on Windows, macOS, and Linux desktop systems through one Python CLI, secure native token storage, and consistent autostart commands.

**Architecture:** Use `platformdirs` for user data paths and validate `keyring`'s selected backend against a strict native-backend allowlist. Add a shared autostart CLI with small Windows Task Scheduler, macOS LaunchAgent, and Linux systemd user adapters.

**Tech Stack:** Python 3.10+, platformdirs, keyring, argparse, plistlib, subprocess, pathlib.

**Spec:** `docs/superpowers/specs/2026-10-06-cross-platform-desktop-design.md`

## Global Constraints

- Supported: Windows, macOS, and Linux with a signed-in desktop user session.
- Python 3.10 or newer.
- Linux without a graphical user session, a desktop that does not activate `graphical-session.target`, headless servers, and system-wide services are out of scope.
- Windows app data remains `%LOCALAPPDATA%\LayaGmailLabeler` and the existing keyring identifiers stay unchanged.
- Secure stores are Windows Credential Manager, macOS Keychain, and Linux Secret Service or KWallet; unsupported stores fail closed.
- Never store OAuth tokens as plaintext or fall back to a file-based credential backend.
- The autostart poller defaults to `--dry-run`; `--apply` must be explicit.
- Existing Gmail safety, local inference, and message-retention behavior remain unchanged.
- Do not add or run tests for this task; perform source and diff review only.

## Review Focus

- A keyring config or environment variable selects an insecure third-party backend: reject it before reading or writing OAuth credentials.
- A missing/unavailable Linux session keyring: return a short safe error without writing a token.
- A Windows user with existing data: keep the current data path and keyring service/account identifiers.
- A project or interpreter path containing spaces: preserve each startup command argument correctly.
- A custom `--config` option: include it in the installed startup command so it uses the same local settings.

---

### Task 1: Cross-platform user data and credential storage

**Files:**
- Create: `src/laya_gmail_labeler/credential_store.py`
- Modify: `src/laya_gmail_labeler/settings.py`
- Modify: `src/laya_gmail_labeler/gmail.py`
- Modify: `pyproject.toml`
- Modify: `config.example.toml`

**Interfaces:**
- Produces: `credential_backend() -> keyring.backend.KeyringBackend`, returning only an approved native backend or raising a sanitized `CredentialStoreError`.
- Consumes: current OAuth service/account identifiers and token serialization in `gmail.py`.

- [x] Add `platformdirs>=4,<5` and resolve `local_data_dir()` through `user_data_path("LayaGmailLabeler", appauthor=False)` so the existing Windows path remains the same.
- [x] Add strict backend checks for Windows `WinVaultKeyring`, macOS `Keyring`, and Linux `SecretService.Keyring` or `kwallet.DBusKeyring`; reject all other backend classes.
- [x] Route token reads and writes through that backend, verify writes by reading the value back, and convert backend failures to safe errors without exposing the token.
- [x] Remove `${LOCALAPPDATA}` path overrides from the public example config so defaults work on all supported operating systems.
- [x] Review the affected source and configuration for remaining Windows-only path or credential assumptions.

### Task 2: One cross-platform autostart interface

**Files:**
- Create: `src/laya_gmail_labeler/autostart/__init__.py`
- Create: `src/laya_gmail_labeler/autostart/windows.py`
- Create: `src/laya_gmail_labeler/autostart/macos.py`
- Create: `src/laya_gmail_labeler/autostart/linux.py`
- Modify: `src/laya_gmail_labeler/cli.py`
- Delete: `scripts/install-task.ps1`
- Delete: `scripts/remove-task.ps1`

**Interfaces:**
- Produces: `install_autostart(*, apply_labels: bool, config_path: Path | None) -> None` and `remove_autostart() -> None`.
- CLI commands: `install-autostart [--apply]` and `remove-autostart`.
- Startup command: current `sys.executable -m laya_gmail_labeler`, preserving a supplied global `--config`, followed by `watch --dry-run` by default or `watch --apply` only when requested.

- [x] Dispatch by `platform.system()` and reject unsupported platforms with a safe message.
- [x] Register a current-user logon task on Windows with Task Scheduler, without requiring administrator privileges; preserve unlimited runtime and battery operation.
- [x] Write and load/unload a current-user macOS LaunchAgent plist.
- [x] Write and enable/disable a current-user Linux `systemd --user` unit tied to `graphical-session.target`, honor absolute `XDG_CONFIG_HOME`, and report missing user-session integration safely.
- [x] Stop a running poller before removing its registration; keep removal scoped to this app's fixed task/service identifier.
- [x] Add both CLI commands and keep startup command arguments safe when paths contain spaces.
- [x] Delete the standalone PowerShell scripts after the shared CLI replaces their behavior.
- [x] Review subprocess arguments, generated service files, error handling, and OS dispatch without printing captured command output.

### Task 3: Cross-platform user documentation

**Files:**
- Modify: `README.md`

- [x] Replace Windows-only install and OAuth instructions with distinct Windows, macOS, and Linux desktop instructions.
- [x] Document native keyring requirements, per-user data locations, foreground polling, `install-autostart`, `remove-autostart`, revocation, and headless Linux being unsupported.
- [x] Preserve the Gmail scope warning, local inference explanation, dry-run default, and message privacy limitations.
- [x] Review the complete diff for accidental credentials, private data, local machine paths, and stale PowerShell-script references.
- [x] Run `git diff --check` and inspect `git status`; do not run tests or build commands.
