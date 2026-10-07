# Laya Gmail Labeler

A local Python command-line app that classifies new Gmail Inbox messages with the Laya model running on your computer. It supports Windows, macOS, and Linux desktop sessions. It can propose or add one of six labels: IA/Acción, IA/Recibos, IA/Boletines, IA/Trabajo, IA/Personal, or IA/Spam.

## Privacy and limits

- Email text is classified by a local Laya model. The app does not send message content to Laya, Jev, or another inference service.
- Gmail remains your email provider. The app reads message data through Google's Gmail API, and Google continues to host your mailbox.
- Google describes `gmail.modify` as permission to read, compose, and send email, and it also permits label changes. This is broader than adding one label. The app uses the scope only to read eligible Inbox mail and add labels; its code does not send, reply, forward, delete, archive, or change Gmail's system Spam status.
- Dry-run is the default. Existing Inbox mail is not backfilled at activation. Only messages that arrive after setup are eligible.
- Message text is not written to local state or logs. Local SQLite state stores Gmail message IDs and processing status. OAuth tokens are stored in the native secure credential store for the operating system.
- Downloaded model weights stay in the local model cache and are not included in this repository.
- The computer and signed-in desktop session must be available for polling to continue.
- Low-confidence or invalid model results stay in the Inbox without an IA label. They are saved as `needs_review` and are not automatically retried.
- The first local inference downloads the selected model checkpoint. Internet access is needed for Gmail API requests and that initial download; inference then runs in the local process.

Laya's documentation describes its confidence as a signal that should be validated on your own data. The multilingual checkpoint may be overconfident, so review dry-run proposals before enabling label changes. A high confidence score does not guarantee a correct category.

## Install

Use Python 3.10 or newer. Create a virtual environment and install the project from this directory.

### Windows

~~~text
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m laya_gmail_labeler --help
~~~

### macOS and Linux

~~~sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m laya_gmail_labeler --help
~~~

For repeated use, activate `.venv` in your terminal, or call its Python executable directly: `.\.venv\Scripts\python.exe -m laya_gmail_labeler ...` on Windows and `.venv/bin/python -m laya_gmail_labeler ...` on macOS and Linux. The project does not require a PowerShell installer.

## Secure credential stores

The app stores OAuth tokens in the operating system's secure credential store:

- Windows Credential Manager.
- macOS Keychain.
- Linux Secret Service or KWallet in a signed-in desktop session.

The app fails with an actionable error if it cannot use one of these approved stores. It never falls back to a plaintext token file. Linux without a graphical user session is not supported.

## Google setup

1. Create a Google Cloud project, enable the Gmail API, and create an OAuth client of type Desktop app.
2. Download the OAuth client JSON and place it in the app data folder as `credentials.json`:

   - Windows: `%LOCALAPPDATA%\LayaGmailLabeler\credentials.json`
   - macOS: `~/Library/Application Support/LayaGmailLabeler/credentials.json`
   - Linux: `$XDG_DATA_HOME/LayaGmailLabeler/credentials.json`, or `~/.local/share/LayaGmailLabeler/credentials.json` when `XDG_DATA_HOME` is unset.

The app creates its data folder when it starts. Place `credentials.json` there, then run setup from the installed environment. It opens Google's local consent flow and saves the refresh token in the OS credential store:

~~~text
laya-gmail-labeler setup
~~~

Setup records the current Gmail history cursor; it does not process older Inbox messages. The example config leaves label changes disabled. If you intentionally want setup to create the six Gmail labels, run `laya-gmail-labeler setup --apply`.

A personal OAuth app with fewer than 100 users may be used without verification, but Google can show an unverified-app warning. If the OAuth project is External and remains in Testing, refresh tokens for Gmail scopes expire after seven days. See [Google's personal-use verification exception](https://support.google.com/cloud/answer/13464323), [Testing status and token expiry](https://developers.google.com/identity/protocols/oauth2#expiration), and [OAuth desktop app setup](https://developers.google.com/identity/protocols/oauth2/native-app).

## Use

Run one poll in dry-run mode and inspect only aggregate category counts:

~~~text
laya-gmail-labeler once
laya-gmail-labeler review-proposals
~~~

The interactive proposal review requires a terminal. It fetches sender and subject only when you run that command. They are shown on screen and are not saved to logs or state. Press Ctrl+C to stop the foreground watch command.

To apply labels, first review proposals, then pass the explicit apply option:

~~~text
laya-gmail-labeler once --apply
laya-gmail-labeler watch --apply
~~~

Apply mode may create a missing IA label and add one approved IA label to an Inbox message. It does not perform other message actions. A proposal created during dry-run is applied as recorded; it is not rescored.

For continuous foreground polling, run `laya-gmail-labeler watch` and stop it with Ctrl+C.

## Start automatically at user logon

The same Python commands install and remove automatic startup on all three desktop systems. The installer uses the current user's native startup mechanism: Task Scheduler on Windows, a LaunchAgent on macOS, or a `systemd --user` service on Linux. No administrator privileges are needed.

~~~text
laya-gmail-labeler install-autostart
~~~

This registers a poller that runs in dry-run mode. After reviewing proposals, use `laya-gmail-labeler install-autostart --apply` to allow it to add labels. If you use a custom TOML config, pass its path before the command, for example `laya-gmail-labeler --config /path/to/config.toml install-autostart`.

Stop the poller and remove its startup registration with:

~~~text
laya-gmail-labeler remove-autostart
~~~

Keep the computer and user session available for polling. Linux automatic startup requires a running per-user systemd manager, a desktop that activates `graphical-session.target`, and an available desktop keyring. It starts after that target is active; if the keyring is not ready, systemd retries after 30 seconds.

## Local files and revocation

Configuration, OAuth client JSON, and SQLite state are stored under the operating system's per-user data directory listed above. Logs, virtual environments, and downloaded model caches stay local and are ignored by Git. An explicit absolute `app.state_dir` or `app.credentials_file` path in a local TOML config can override the defaults. Keep the project and virtual environment at the same path after installing automatic startup; moving them requires reinstalling it.

Stop foreground polling with Ctrl+C, or remove automatic startup with `laya-gmail-labeler remove-autostart`. Revoke the OAuth grant from your Google Account's third-party app access page. Removing local app data does not delete messages from Gmail. A different computer or operating system needs its own Gmail authorization because OS keychain entries are not portable.

The project does not include a license yet.

## References

- [Laya Python quickstart](https://laya-ai.com/guides/install-laya)
- [Laya platform requirements](https://laya-ai.com/guides/laya-requirements)
- [Gmail API OAuth scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Python keyring documentation](https://keyring.readthedocs.io/en/stable/)
- [platformdirs documentation](https://platformdirs.readthedocs.io/en/stable/platforms.html)
- [Laya source and API documentation](https://github.com/NandhaKishorM/laya)
