# Laya Gmail Labeler

A Windows command-line app that classifies new Gmail inbox messages with the Laya model running on your computer. It can propose or add one of six labels: IA/Acción, IA/Recibos, IA/Boletines, IA/Trabajo, IA/Personal, or IA/Spam.

## Privacy and limits

- Email text is classified by a local Laya model. The app does not send message content to Laya, Jev, or another inference service.
- Gmail remains your email provider. The app reads message data through Google's Gmail API, and Google still hosts your mailbox.
- Google describes `gmail.modify` as permission to read, compose, and send email, and it also permits label changes. This is broader than adding one label. The app uses the scope only to read eligible Inbox mail and add labels; its code does not send, reply, forward, delete, archive, or change Gmail's system Spam status.
- Dry-run is the default. Existing inbox mail is not backfilled at activation. Only messages that arrive after setup are eligible.
- Message text is not written to local state or logs. Local SQLite state stores Gmail message IDs and processing status. OAuth tokens are stored in Windows Credential Manager.
- Downloaded model weights stay in the local model cache and are not included in this repository.
- The computer and signed-in Windows session must be available for polling to continue.
- Low-confidence or invalid model results stay in the Inbox without an IA label. They are saved as needs_review and are not automatically retried.
- The first local inference downloads the selected model checkpoint. Internet access is needed for Gmail API requests and that initial download; inference then runs in the local process.

Laya's documentation describes its confidence as a signal that should be validated on your own data. The multilingual checkpoint may be overconfident, so review dry-run proposals before enabling label changes. A high confidence score does not guarantee a correct category.

## Install

Use Python 3.10 or newer in PowerShell from this project directory:

~~~powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\Activate.ps1
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\LayaGmailLabeler" | Out-Null
Copy-Item config.example.toml "$env:LOCALAPPDATA\LayaGmailLabeler\config.toml"
~~~

The example config leaves label changes disabled.
In each new PowerShell window, activate the environment again with `.\.venv\Scripts\Activate.ps1` before running `laya-gmail-labeler` commands.

## Google setup

1. Create a Google Cloud project and enable the Gmail API.
2. Configure the OAuth consent screen for personal use and create an OAuth client of type Desktop app.
3. Download the client JSON to `%LOCALAPPDATA%\LayaGmailLabeler\credentials.json`. Do not put that file in the project or GitHub.
4. Run `laya-gmail-labeler setup`. It opens Google's local consent flow and saves the token in Windows Credential Manager. Setup records the current Gmail history cursor; it does not process older Inbox messages.
5. If you intentionally want the app to create the six Gmail labels during setup, run `laya-gmail-labeler setup --apply`. Dry-run setup creates no Gmail labels.

A personal OAuth app with fewer than 100 users may be used without verification, but Google can show an unverified-app warning. If the OAuth project is External and remains in Testing, refresh tokens for Gmail scopes expire after seven days. See [Google's personal-use verification exception](https://support.google.com/cloud/answer/13464323), [Testing status and token expiry](https://developers.google.com/identity/protocols/oauth2#expiration), and [OAuth desktop app setup](https://developers.google.com/identity/protocols/oauth2/native-app).

## Use

Run one poll in dry-run mode and inspect only aggregate category counts:

~~~powershell
laya-gmail-labeler once
laya-gmail-labeler review-proposals
~~~

The interactive proposal review requires a terminal. It fetches sender and subject only when you run that command. They are shown on screen and are not saved to logs or state. Press Ctrl+C to stop the foreground watch command.

To apply labels, first review proposals, then pass the explicit apply option:

~~~powershell
laya-gmail-labeler once --apply
laya-gmail-labeler watch --apply
~~~

Apply mode may create a missing IA label and add one approved IA label to an Inbox message. It does not perform other message actions. A proposal created during dry-run is applied as recorded; it is not rescored.

For continuous foreground polling, run the watch command and stop it with Ctrl+C:

~~~powershell
laya-gmail-labeler watch
~~~

To keep polling at user logon, install a per-user scheduled task:

~~~powershell
.\scripts\install-task.ps1
.\scripts\install-task.ps1 -Apply
.\scripts\remove-task.ps1
~~~

The task runs at user logon in the signed-in session. The default scheduled task passes `--dry-run`, even if local config enables apply mode. Use `-Apply` only after you are comfortable with the proposals and the model's limitations. The PC must be on and awake for polling to run.

## Local files and revocation

Configuration, credentials, SQLite state, logs, virtual environments, and model caches belong on your computer and are ignored by Git. The default state folder is `%LOCALAPPDATA%\LayaGmailLabeler`.

Stop the foreground command with Ctrl+C, or remove the scheduled task with the script above. Revoke the OAuth grant from your Google Account's third-party app access page. You can also remove local state and credentials from the app data folder; this does not delete messages from Gmail.

The project does not include a license yet.

## References

- [Laya Python quickstart](https://laya-ai.com/guides/install-laya)
- [Laya source and API documentation](https://github.com/NandhaKishorM/laya)
- [Gmail API OAuth scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
