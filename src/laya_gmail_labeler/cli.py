"""Command-line entry points for private, local Gmail classification."""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

from .classifier import ClassificationUnavailable
from .gmail import (
    GmailAPIError,
    OAuthSetupError,
    build_gmail_client,
    initialize_account,
)
from .service import EmailService, GmailOperationBlocked, SetupRequired
from .settings import LABELS, AppConfig, load_config
from .state import StateStore

LOGGER = logging.getLogger("laya_gmail_labeler")


def _add_apply_options(command: argparse.ArgumentParser) -> None:
    group = command.add_mutually_exclusive_group()
    group.add_argument("--apply", dest="apply_override", action="store_const", const=True, default=None)
    group.add_argument("--dry-run", dest="apply_override", action="store_const", const=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laya-gmail-labeler",
        description="Classify new Gmail Inbox messages with a local Laya model.",
    )
    parser.add_argument("--config", type=Path, help="Path to a local TOML configuration file.")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="Authorize Gmail and save the first-activation cursor.")
    _add_apply_options(setup)

    once = commands.add_parser("once", help="Process one poll interval.")
    _add_apply_options(once)

    watch = commands.add_parser("watch", help="Poll Gmail every 60 seconds in this user session.")
    _add_apply_options(watch)

    review = commands.add_parser("review-proposals", help="Show pending sender and subject details in this terminal.")
    review.add_argument("--limit", type=int, default=None, help="Optional maximum number of proposals to show.")
    return parser


def _config(args: argparse.Namespace) -> AppConfig:
    override = getattr(args, "apply_override", None)
    return load_config(args.config, apply_override=override)


def _create_runtime(config: AppConfig, *, interactive: bool = False) -> tuple[StateStore, Any]:
    state = StateStore(config.state_dir)
    client = build_gmail_client(config.credentials_file, interactive=interactive)
    return state, client


def _format_counts(values: Any) -> str:
    if not values:
        return "none"
    return ", ".join(f"{LABELS[key]}={int(count)}" for key, count in sorted(values.items()) if key in LABELS)


def _report_summary(summary: Any) -> None:
    LOGGER.info(
        "Poll complete: proposed={%s}; applied={%s}; needs_review=%d; transient_errors=%d; skipped=%d",
        _format_counts(summary.proposed_by_category),
        _format_counts(summary.applied_by_category),
        summary.needs_review,
        summary.transient_errors,
        summary.skipped,
    )
    error_codes = getattr(summary, "error_codes", {})
    if error_codes:
        LOGGER.warning("Transient error codes: %s", ", ".join(f"{key}={value}" for key, value in sorted(error_codes.items())))


def _setup(args: argparse.Namespace) -> int:
    config = _config(args)
    state, client = _create_runtime(config, interactive=True)
    initialized = initialize_account(client, state, config.labels or LABELS, config.apply_labels)
    if initialized:
        LOGGER.info("Activation cursor saved. Existing Inbox messages were left untouched.")
    else:
        LOGGER.info("Existing activation cursor retained.")
    if config.apply_labels:
        LOGGER.info("Approved Gmail labels are enabled for future polls.")
    else:
        LOGGER.info("Dry-run setup did not create Gmail labels or change messages.")
    return 0


def _once(args: argparse.Namespace) -> int:
    config = _config(args)
    state, client = _create_runtime(config)
    service = EmailService(client, state, config)
    _report_summary(service.run_once())
    return 0


def _terminal_text(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    visible = "".join(character if unicodedata.category(character)[0] != "C" else " " for character in text)
    return " ".join(visible.split())[:limit]


def _review(args: argparse.Namespace) -> int:
    if not sys.stdout.isatty():
        LOGGER.error("review-proposals requires an interactive terminal; no message details were printed.")
        return 2
    if args.limit is not None and args.limit < 1:
        LOGGER.error("--limit must be at least 1.")
        return 2
    config = _config(args)
    state, client = _create_runtime(config)
    service = EmailService(client, state, config)
    proposals = service.review_proposals(limit=args.limit)
    if not proposals:
        print("No pending proposals.")
        return 0
    print(f"Pending proposals shown: {len(proposals)}")
    for index, proposal in enumerate(proposals, 1):
        category = proposal.get("category")
        label = LABELS.get(category, "Unknown category")
        confidence = proposal.get("confidence")
        percentage = f"{float(confidence):.0%}" if isinstance(confidence, (int, float)) and math.isfinite(float(confidence)) else "unknown"
        sender = _terminal_text(proposal.get("sender")) or "(no sender header)"
        subject = _terminal_text(proposal.get("subject")) or "(no subject)"
        print(f"{index}. {label} | confidence {percentage}")
        print(f"   From: {sender}")
        print(f"   Subject: {subject}")
    return 0


def _watch(args: argparse.Namespace) -> int:
    config = _config(args)
    state, client = _create_runtime(config)
    service = EmailService(client, state, config)
    LOGGER.info("Watching Gmail every %d seconds; apply_labels=%s", config.interval_seconds, config.apply_labels)
    while True:
        try:
            _report_summary(service.run_once())
        except GmailOperationBlocked as error:
            LOGGER.error("Polling stopped; Gmail needs attention (code=%s).", error.safe_code)
            return 2
        except GmailAPIError as error:
            if error.safe_code in {"http_400", "http_401", "http_403", "oauth_refresh_failed"}:
                if error.safe_code == "oauth_refresh_failed":
                    LOGGER.error("Polling stopped; Google authorization expired or was revoked. Run setup again.")
                else:
                    LOGGER.error("Polling stopped; Gmail needs attention (code=%s).", error.safe_code)
                return 2
            LOGGER.warning("Poll failed (code=%s); retrying after the next interval.", error.safe_code)
        except (OAuthSetupError, SetupRequired) as error:
            LOGGER.error("Polling stopped: %s", str(error))
            return 2
        except Exception:
            LOGGER.warning("Poll failed (code=operation_error); retrying after the next interval.")
        time.sleep(config.interval_seconds)


def _error_code(error: Exception) -> str:
    if isinstance(error, GmailOperationBlocked):
        return error.safe_code
    if isinstance(error, GmailAPIError):
        return error.safe_code
    if isinstance(error, OAuthSetupError):
        return "oauth_error"
    if isinstance(error, SetupRequired):
        return "setup_required"
    if isinstance(error, ClassificationUnavailable):
        return "model_error"
    return "operation_error"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "setup":
            return _setup(args)
        if args.command == "once":
            return _once(args)
        if args.command == "watch":
            return _watch(args)
        if args.command == "review-proposals":
            return _review(args)
        LOGGER.error("Unknown command.")
        return 2
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user.")
        return 130
    except Exception as error:
        code = _error_code(error)
        if isinstance(error, (OAuthSetupError, SetupRequired)):
            LOGGER.error("%s", str(error))
        elif code != "operation_error":
            LOGGER.error("Command failed (code=%s).", code)
        else:
            LOGGER.error("Command failed (code=operation_error).")
        return 2
