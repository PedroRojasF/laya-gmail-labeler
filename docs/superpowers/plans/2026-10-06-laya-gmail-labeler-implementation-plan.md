# Gmail Local Labeler Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Build a Windows Python app that automatically labels new Gmail messages with locally run Laya and publish a public repository containing no private data.

**Architecture:** A local polling service uses the Gmail API to find messages received after activation, extracts a bounded plain-text sample, classifies it with Laya's multilingual checkpoint, and adds one user label. SQLite stores message IDs and statuses locally; OAuth tokens go to Windows Credential Manager; dry-run is the default and apply mode only adds labels.

**Tech Stack:** Python 3.10+, Laya 0.3.x, Gmail API client, Google OAuth, keyring, SQLite, PowerShell Task Scheduler setup documentation.

**Spec:** docs/superpowers/specs/2026-10-06-gmail-local-labeler-design.md

## Global Constraints

- Run only on Windows and keep model inference on the user's machine.
- Process new Inbox messages after activation; do not backfill existing mail on first run.
- Poll every 60 seconds while the user session is active.
- Apply at most one of IA/Acción, IA/Recibos, IA/Boletines, IA/Trabajo, IA/Personal, or IA/Spam.
- IA/Spam is a review label only; never change Gmail's Spam status.
- Do not delete, archive, send, reply, forward, or otherwise change message content.
- Leave low-confidence and invalid model results unchanged; retry transient failures only.
- Dry-run is the default. Label changes require explicit apply mode.
- Do not log or persist message content. Keep all OAuth secrets, tokens, state, logs, and downloaded weights out of Git.
- Explain that gmail.modify is broader than label-only access and Google still hosts the mailbox.
- Do not add a license until the user chooses one.

## File Map

- pyproject.toml: package metadata, supported Python version, and runtime dependencies.
- .gitignore: credentials, state, logs, local config, virtual environments, and generated model artifacts.
- config.example.toml: safe defaults and label descriptions, without account-specific values.
- src/laya_gmail_labeler/settings.py: config loading and validation.
- src/laya_gmail_labeler/gmail.py: OAuth, Gmail API calls, label setup, message retrieval, and incremental history.
- src/laya_gmail_labeler/message_content.py: MIME parsing and bounded plain-text extraction.
- src/laya_gmail_labeler/classifier.py: local Laya Router and fixed label decision.
- src/laya_gmail_labeler/state.py: SQLite watermark and message status persistence.
- src/laya_gmail_labeler/service.py: poll, classify, and apply-label orchestration.
- src/laya_gmail_labeler/cli.py and __main__.py: setup, one-shot, watch, dry-run, and apply commands.
- README.md: install, Google OAuth setup, privacy boundaries, scheduling, troubleshooting, revoke access.
- scripts/install-task.ps1 and scripts/remove-task.ps1: register and remove the current-user Windows scheduled task.
- docs/superpowers/specs/...: approved design.
- docs/superpowers/plans/...: this implementation plan.

## Review Focus

- First activation must leave historical Inbox messages untouched; the saved cursor must catch up messages received while the app was offline.
- MIME parsing must handle multipart, missing bodies, unusual charsets, and HTML-only messages without fetching remote resources or attachments.
- A low-confidence, invalid, or prompt-injection-like message must never trigger anything except an allowed label addition, and uncertain mail must remain unchanged.
- Expired OAuth or Gmail history must fail clearly and recover without a bulk backfill.
- Secrets and private message data must be absent from tracked files, logs, and the public GitHub repository.

## Task 1: Scaffold a public-safe Python package

**Files:**
- Create: pyproject.toml
- Create: .gitignore
- Create: config.example.toml
- Create: src/laya_gmail_labeler/__init__.py
- Create: src/laya_gmail_labeler/__main__.py
- Create: README.md

**Steps:**

- [ ] Create the package skeleton and declare Python 3.10+ with compatible ranges for laya 0.3.x, google-api-python-client, google-auth-oauthlib, and keyring.
- [ ] Add ignore rules for credentials.json, token and cache files, local configuration, SQLite state, logs, virtual environments, downloaded model weights, and local test fixtures.
- [ ] Define the six labels, dry-run default, 60-second polling interval, and bounded email excerpt limit in a public-safe example config.
- [ ] Draft README privacy summary and the Gmail OAuth permission warning; state clearly that inference is local but Gmail remains the mailbox provider.
- [ ] Inspect the staged file list and run git diff --check; do not stage local config, credentials, or state.
- [ ] Commit as feat: scaffold local Gmail labeler.

## Task 2: Build safe message parsing and local state

**Files:**
- Create: src/laya_gmail_labeler/message_content.py
- Create: src/laya_gmail_labeler/state.py
- Create: src/laya_gmail_labeler/settings.py

**Steps:**

- [ ] Parse Gmail API MIME payloads without downloading attachments or remote HTML; prefer text/plain, strip markup from HTML-only content with the standard library, decode charsets safely, and cap extracted text at 3,000 characters.
- [ ] Create a SQLite database under %LOCALAPPDATA%\LayaGmailLabeler; persist the Gmail history watermark and message IDs with statuses proposed, applied, needs_review, or transient_error, but never store message bodies.
- [ ] Persist dry-run proposals as message ID, selected category, and confidence so the user can inspect them locally and later apply those same proposals without rescoring email. Mark applied and needs_review terminal; retry transient_error on the next poll.
- [ ] Validate the local configuration, including the six fixed labels, 60-second interval, confidence threshold, state path, and apply flag.
- [ ] Review parser and persistence paths for accidental message or credential logging; commit as feat: add local message and state handling.

## Task 3: Connect Gmail with local OAuth

**Files:**
- Create: src/laya_gmail_labeler/gmail.py
- Modify: src/laya_gmail_labeler/settings.py
- Modify: README.md

**Steps:**

- [ ] Implement desktop OAuth using the user's local credentials.json and the Gmail API gmail.modify scope; save authorized user tokens in Windows Credential Manager through keyring.
- [ ] Add a setup command that opens Google's consent flow and creates the six Gmail user labels only when apply mode is enabled.
- [ ] On first enable, save the current Gmail historyId without processing older Inbox messages.
- [ ] Read messagesAdded changes after the saved historyId, fetch only messages still in INBOX, and retrieve only required headers and body parts.
- [ ] Persist each returned history cursor only after the associated message IDs are safely recorded; on expired history, recover using the last processed internalDate and a Gmail after: search without backfilling older mail.
- [ ] Ensure dry-run performs no Gmail mutations, including label creation; apply mode may only create labels and add one label to a message.
- [ ] Document that a Google OAuth app left in Testing expires authorization after seven days; describe personal-use setup, the unverified-app warning, and token revocation.
- [ ] Review the permission grant and every Gmail API action against the approved spec; commit as feat: connect Gmail with local OAuth.

## Task 4: Classify with local Laya and apply one label

**Files:**
- Create: src/laya_gmail_labeler/classifier.py
- Create: src/laya_gmail_labeler/service.py
- Modify: src/laya_gmail_labeler/gmail.py

**Steps:**

- [ ] Load Laya's multilingual Router locally and send it only sender, subject, and the bounded message excerpt.
- [ ] Ask one fixed choice question with the six approved categories; map internal slugs to Gmail labels and reject any output outside the fixed set.
- [ ] Treat low-confidence or invalid responses as needs_review without changing Gmail; treat operational failures as transient_error for the next poll.
- [ ] Orchestrate history polling, deduplication, classification, and label application; do not pass model output into arbitrary API methods.
- [ ] Keep unattended logs to counts, timestamps, and safe error codes only; never include message IDs, sender, subject, excerpt, or raw response.
- [ ] Start in dry-run mode and require an explicit apply flag/configuration to add labels. Persist proposed label decisions locally; when apply mode is explicitly enabled, apply pending proposals without printing or persisting message text. The review-proposals command lets the user correlate a proposal with a message by fetching its sender and subject on demand.
- [ ] Review every Gmail mutation and classification branch against the six-label allowlist; commit as feat: classify and label Gmail messages locally.

## Task 5: Add unattended Windows operation and user documentation

**Files:**
- Create: src/laya_gmail_labeler/cli.py
- Modify: src/laya_gmail_labeler/__main__.py
- Modify: README.md
- Create: scripts/install-task.ps1
- Create: scripts/remove-task.ps1

**Steps:**

- [ ] Implement setup, one-shot, watch, and review-proposals commands. Normal status output contains no message content; review-proposals retrieves sender and subject on demand and displays them only in the interactive terminal, without writing them to logs or local state.
- [ ] Make the watch loop poll every 60 seconds, catch transient exceptions without logging sensitive data, and recover on restart from the saved history cursor.
- [ ] Add PowerShell scripts to register/remove a Task Scheduler entry for the current Windows user; default the installed job to dry-run and require an explicit Apply switch to schedule label changes.
- [ ] Document that the PC and user session must be available, that the first run does not label historical messages, and that low-confidence messages remain in the Inbox without an IA label.
- [ ] Document OAuth creation, local credentials file placement, local model download, keyring storage, start/stop, removal, and Google permission revocation.
- [ ] Review README and scripts for private paths, account addresses, secrets, and accidental Gmail actions; commit as feat: add Windows polling setup.

## Task 6: Finalize and publish the public repository

**Files:**
- Modify: README.md and .gitignore as needed.

**Steps:**

- [ ] Review the full tracked file list and scan source/docs for OAuth tokens, client secrets, account addresses, email samples, local state, and machine-specific paths.
- [ ] Run git diff --check and inspect the final diff; confirm only intended source and documentation are tracked.
- [ ] Create the public GitHub repository named laya-gmail-labeler under the authenticated user and push the main branch; do not upload local credentials, state, logs, or model weights.
- [ ] Record the public repository URL and local setup steps for the user.

## Execution method

Implement natively in this session with superpowers:executing-plans. The user requested direct execution; no parallel delegation is needed.
