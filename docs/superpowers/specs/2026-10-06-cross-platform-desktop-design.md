# Cross-Platform Desktop Support Design

## Status

Proposal extending the approved local Gmail labeler design. This document keeps the existing Gmail behavior and privacy requirements while adding Windows, macOS, and Linux desktop support.

## Objective

Run the local Laya Gmail labeler on Windows, macOS, and Linux desktop systems. The project remains a Python command-line application. No email content is sent to a hosted inference service, and OAuth refresh tokens remain in the operating system's secure credential store.

## Supported environments

- Windows, macOS, and Linux with a signed-in desktop user session.
- Python 3.10 or newer.
- Linux without a graphical user session, a desktop that does not activate `graphical-session.target`, headless servers, and system-wide services are out of scope.
- Gmail remains accessed through Google's API. The app continues to use local Laya inference.

## Behavior that stays the same

- The app polls new Inbox messages and classifies them into the six existing IA labels.
- Dry-run remains the default Gmail behavior. Applying labels requires an explicit option.
- The first setup records an activation boundary and does not backfill the existing Inbox.
- IA/Spam is a user review label. The app does not change Gmail's built-in Spam status.
- The app does not send, reply to, forward, archive, delete, or otherwise modify messages beyond adding an approved user label.
- Message content is not saved in local state or logs. SQLite stores only message IDs, processing status, and polling state.

## Data locations

Use `platformdirs` to resolve the per-user application data directory. Keep all current Windows files under `%LOCALAPPDATA%\LayaGmailLabeler` so existing configuration, OAuth client JSON, and SQLite state remain in place. On macOS and Linux, use the conventional per-user application data directory for that platform. Continue to allow an explicit configured path override.

Downloaded Laya model files remain in the model library's local cache. They are not copied into the project or its public repository.

## OAuth credential storage

Use the existing `keyring` dependency through an explicit allowlist of secure operating-system backends:

- Windows Credential Manager.
- macOS Keychain.
- Linux Secret Service or KWallet in a desktop session.

Keep the current keyring service and account identifiers on Windows to reuse its saved authorization. Do not silently fall back to a plaintext or file-based backend. If no approved secure backend is available or usable, setup and polling must stop with a short actionable error and must not save the token elsewhere.

OAuth continues to use Google's local desktop consent flow. Tokens stay in the OS keychain. A new computer or operating system needs its own Gmail authorization; tokens are not copied between systems. OAuth client JSON stays in the per-user app data directory and is never tracked by Git.

## Automatic startup

Provide one cross-platform Python CLI interface for user-level automatic startup:

- `laya-gmail-labeler install-autostart` registers a poller for the current user. The registered poller runs Gmail in dry-run mode by default.
- `laya-gmail-labeler install-autostart --apply` registers a poller that can add the approved labels.
- `laya-gmail-labeler remove-autostart` stops the poller if it is running and removes the current user's registration.

The CLI dispatches to small platform-specific backends while keeping the user-facing commands and documentation consistent:

- Windows Task Scheduler, triggered at the current user's logon.
- A per-user macOS LaunchAgent.
- A per-user Linux `systemd --user` service tied to `graphical-session.target`; it retries transient startup failures and stores its unit under an absolute `XDG_CONFIG_HOME` or `~/.config`.

No administrator privileges are required. The computer and user session must remain available for polling. Linux automatic startup requires the user manager, a desktop that activates `graphical-session.target`, and an approved keyring backend. Retire the standalone PowerShell installer and remover once the CLI commands replace them.

## Documentation and repository

Update the README for Windows, macOS, and Linux. Document installation, local OAuth setup, data locations, keyring requirements, foreground polling, automatic startup, removal, and revocation. Keep OS-specific details grouped under each platform, with shared Gmail behavior described once.

The public repository must continue to exclude OAuth files and tokens, message data, model weights, local logs, virtual environments, and machine-specific paths. Do not add a license or credential-bearing CI workflow as part of this change.

## Failure and privacy requirements

- No credential fallback to plaintext, environment dumps, config files, or logs.
- No email content in logs, SQLite, or generated startup files.
- Startup files contain only the interpreter path, project/module invocation, and explicit dry-run/apply mode.
- If startup registration or secure keyring access fails, report the affected operation without exposing tokens, email content, or full API responses.

## Out of scope

- Headless Linux, servers, containers, system-wide services, or unattended service accounts.
- Multiple Gmail accounts, cloud inference, model training, or Gmail push notifications.
- Changing Gmail's system Spam handling or adding any message action beyond the existing approved labels.
- Moving or migrating the current Windows app data directory.

## Acceptance criteria

1. The package and its shared CLI have no Windows-only path or credential-store assumptions.
2. Default data paths resolve per user on all three desktop operating systems, while the existing Windows path and keyring identifiers remain stable.
3. Windows, macOS, and Linux desktop use only their approved native secure credential stores; unsupported stores fail closed.
4. Setup can perform local-browser OAuth on each supported desktop operating system.
5. The same autostart install and remove commands dispatch to the appropriate per-user platform mechanism.
6. An installed poller uses dry-run mode unless the user explicitly selects apply mode.
7. The README explains support boundaries and setup for each platform.
8. Existing Gmail safety behavior, message retention limits, and public-repository hygiene remain intact.
