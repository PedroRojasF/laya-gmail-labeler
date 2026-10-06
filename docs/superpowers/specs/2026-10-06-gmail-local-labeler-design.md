# Gmail Local Labeler Design

## Objective

Automatically classify new Gmail inbox messages with the open-source Laya model running locally on Windows, then apply one Gmail user label. Email content must not be sent to hosted Laya, Jev, or another AI inference service.

## Project location and publication

- Local project: a user-selected Windows folder.
- Public GitHub repository: laya-gmail-labeler under the user's authenticated GitHub account.
- The repository contains no private account data, credentials, message data, generated model weights, or machine-specific paths.

## User-facing behavior

The application polls the Gmail inbox once per minute while the user's Windows session is active. It classifies an eligible message into at most one of these labels:

- IA/Acción
- IA/Recibos
- IA/Boletines
- IA/Trabajo
- IA/Personal
- IA/Spam

IA/Spam is a review label only. The application does not move messages to Gmail's Spam folder, mark them as spam, delete, archive, forward, reply to, or send messages. If the model cannot make a decision above the configured confidence threshold, it leaves the message unlabeled and records only the message ID and a needs_review status locally. Such messages are not automatically retried; transient API or model errors remain eligible for retry on the next poll.

On first activation, the application records a Gmail history watermark and processes only messages received after activation; it does not backfill the existing inbox. On restart or after downtime, it catches up on newer unlabelled Inbox messages using the saved watermark and local state. It skips messages already bearing one of the six labels. Messages already recorded as classified or needs_review are not processed again automatically.

## Architecture

- Python 3.10+ command-line application for Windows.
- Gmail API using a desktop OAuth client. Fetch only the message ID and the minimum headers/body needed to classify. Ignore attachments and remote HTML resources.
- Local Laya multilingual checkpoint for inference. The classifier receives sender, subject, and a bounded plain-text body excerpt as data; the model can return only a label from the fixed category set.
- Gmail API users.messages.modify applies the selected label. Classification does not trigger any other Gmail action.
- A polling loop supports foreground operation and a Windows Task Scheduler startup entry. The computer must be on and the user session available for continuous polling.
- Local state stores processed message IDs and classification status, never message text. Logs contain counts, timestamps, and error codes only.
- Model weights may be downloaded from the model publisher during setup; email content is never submitted to the model publisher.

## Privacy and security

- No hosted inference, analytics, telemetry, or external logging. The application still makes normal Gmail API calls and may download model weights.
- Gmail OAuth access is required to read messages and apply labels. The gmail.modify scope is broad; the UI and README must disclose that Gmail grants more ability than label-only access, even though the application code will not send or delete mail.
- Google remains the email provider and has the messages in the Gmail account. Local inference prevents an additional AI provider from receiving message content.
- Store OAuth tokens in Windows Credential Manager. Keep the downloaded OAuth client file, token/cache files, local database, model cache, logs, and configuration out of Git.
- Never ask the user to paste OAuth credentials or tokens into chat or commit them.
- Include a .gitignore, a public-safe example configuration without secrets, and setup instructions that create credentials locally.
- Do not log sender addresses, subjects, body excerpts, or full API responses.

## Classification policy

Use Laya's multilingual checkpoint for Spanish and mixed-language mail. The application validates the returned label against the six allowed values. A low-confidence or malformed response produces no Gmail mutation and is recorded as needs_review without retaining message content. It is not retried automatically to avoid repeating the same uncertain decision every minute. A transient API/model failure is not marked processed and is retried on the next poll. Do not rely on Laya confidence as calibrated without validating it on the user's own examples. Provide a dry-run mode that prints proposed labels without changing Gmail; label application must be explicitly enabled in local configuration.

## Public repository contents

The public repository contains source code, dependency declarations, documentation, and safe examples. It contains no user emails, account addresses, OAuth client files, tokens, generated model weights, personal logs, or machine-specific paths. Exclude CI workflows that could request or store Gmail credentials. Do not include a license until the user chooses one.

## Out of scope

- Changing Gmail's built-in spam decisions.
- Deleting, archiving, forwarding, replying to, or sending mail.
- Training or fine-tuning Laya on the user's inbox.
- Cloud inference, server deployment, mobile app, multi-account support, or Gmail push notifications.

## Acceptance criteria

1. The model loads from the local installation and receives no request to a hosted AI endpoint.
2. A new eligible inbox message receives at most one of the six configured user labels.
3. IA/Spam only labels the message; it never changes Gmail's system Spam status.
4. A low-confidence or invalid model result leaves Gmail unchanged and is not repeatedly processed automatically.
5. Dry-run mode never mutates Gmail; apply mode mutates labels only.
6. The first activation leaves the existing Inbox untouched; restarts resume newer unprocessed messages without duplicate actions.
7. No message content or OAuth secret appears in logs or tracked files.
8. The project documentation explains Google OAuth setup, the required permission, local inference, polling behavior, and how to stop/revoke access.
