"""Poll Gmail, classify locally, and add at most one approved user label."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .classifier import ClassificationUnavailable, LayaClassifier
from .gmail import GmailAPIError, GmailHistoryExpired, GmailClient
from .message_content import extract_message_text, get_header
from .settings import AppConfig, LABELS
from .state import StateStore


@dataclass
class PollSummary:
    proposed_by_category: Counter[str] = field(default_factory=Counter)
    applied_by_category: Counter[str] = field(default_factory=Counter)
    needs_review: int = 0
    transient_errors: int = 0
    skipped: int = 0
    error_codes: Counter[str] = field(default_factory=Counter)

    def record_error(self, safe_code: str) -> None:
        self.transient_errors += 1
        self.error_codes[safe_code] += 1


class SetupRequired(RuntimeError):
    pass


class GmailOperationBlocked(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        self.safe_code = safe_code
        super().__init__("Gmail authorization or request needs attention.")


class EmailService:
    def __init__(
        self,
        client: GmailClient,
        state: StateStore,
        config: AppConfig,
        classifier: LayaClassifier | None = None,
    ) -> None:
        self.client = client
        self.state = state
        self.config = config
        self.classifier = classifier or LayaClassifier(config.confidence_threshold)

    def run_once(self) -> PollSummary:
        if not self.state.history_id() or self.state.activated_at_ms() is None:
            raise SetupRequired("Run setup before polling Gmail.")

        labels = dict(self.config.labels or LABELS)
        if labels != LABELS:
            raise SetupRequired("The local label allowlist is invalid.")
        if self.config.apply_labels:
            label_ids = self.client.ensure_user_labels(labels)
        else:
            ids_by_name = self.client.user_labels()
            label_ids = {slug: ids_by_name[name] for slug, name in labels.items() if name in ids_by_name}
        existing_label_ids = set(label_ids.values())

        summary = PollSummary()
        attempted_proposals: set[str] = set()
        if self.config.apply_labels:
            for proposal in self.state.pending_proposals(limit=None):
                message_id = str(proposal["message_id"])
                attempted_proposals.add(message_id)
                self._apply_pending_proposal(proposal, label_ids, existing_label_ids, summary)

        recovery_scan_succeeded = False
        try:
            self._discover_from_history()
            recovery_scan_succeeded = True
        except GmailHistoryExpired:
            try:
                self._recover_expired_history()
                recovery_scan_succeeded = True
            except GmailAPIError as error:
                self._raise_if_blocked(error)
                summary.record_error(error.safe_code)
        except GmailAPIError as error:
            self._raise_if_blocked(error)
            summary.record_error(error.safe_code)

        activation_ms = self.state.activated_at_ms() or 0
        for record in self.state.retryable_messages():
            message_id = str(record["message_id"])
            if message_id in attempted_proposals:
                continue
            self._process_retryable(
                record,
                activation_ms,
                record.get("recovery_floor_ms"),
                label_ids,
                existing_label_ids,
                summary,
            )
        if self.state.recovery_floor_ms() is not None and recovery_scan_succeeded and not self.state.has_recovery_retries():
            self.state.clear_recovery_floor()
        return summary

    def review_proposals(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Fetch sender and subject only for an explicit interactive review command."""
        reviewed: list[dict[str, Any]] = []
        for proposal in self.state.pending_proposals(limit=limit):
            try:
                message = self.client.message_headers(str(proposal["message_id"]))
            except GmailAPIError as error:
                self._raise_if_blocked(error)
                continue
            payload = message.get("payload") or {}
            reviewed.append(
                {
                    "category": proposal.get("category"),
                    "confidence": proposal.get("confidence"),
                    "sender": get_header(payload, "From"),
                    "subject": get_header(payload, "Subject"),
                }
            )
        return reviewed

    def _discover_from_history(self) -> None:
        cursor = self.state.history_id()
        if not cursor:
            raise SetupRequired("Run setup before polling Gmail.")
        page_token: str | None = None
        latest_history_id: str | None = None
        while True:
            response = self.client.list_history_page(cursor, page_token)
            for record in response.get("history", []) or []:
                for added in record.get("messagesAdded", []) or []:
                    message = added.get("message") or {}
                    message_id = message.get("id")
                    if message_id:
                        self.state.ensure_transient(str(message_id))
            latest_history_id = str(response.get("historyId") or latest_history_id or "") or latest_history_id
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        if not latest_history_id:
            latest_history_id = self.client.current_history_id()
        # IDs from every returned page are durable before the cursor moves.
        self.state.set_history_id(latest_history_id)

    def _recovery_floor_ms(self) -> int:
        activation = self.state.activated_at_ms() or 0
        last_processed = self.state.last_internal_date_ms()
        return max(activation, last_processed or activation)

    def _recover_expired_history(self) -> None:
        floor = self.state.recovery_floor_ms()
        if floor is None:
            floor = self._recovery_floor_ms()
            self.state.set_recovery_floor(floor)
        # Capture a fresh cursor before searching. New mail after it will be caught next poll.
        fresh_cursor = self.client.current_history_id()
        message_ids = self.client.search_inbox_after(floor)
        for message_id in message_ids:
            self.state.ensure_transient(message_id, recovery_floor_ms=floor)
        self.state.set_history_id(fresh_cursor)

    def _apply_pending_proposal(
        self,
        proposal: dict[str, Any],
        label_ids: dict[str, str],
        existing_label_ids: set[str],
        summary: PollSummary,
    ) -> None:
        message_id = str(proposal["message_id"])
        category = proposal.get("category")
        confidence = proposal.get("confidence")
        internal_date_ms = proposal.get("internal_date_ms")
        if category not in LABELS or category not in label_ids or not self._valid_confidence(confidence):
            self.state.mark_needs_review(message_id, internal_date_ms, "invalid_proposal")
            summary.needs_review += 1
            return
        try:
            metadata = self.client.message_metadata(message_id)
            label_set = set(metadata.get("labelIds") or [])
            if "INBOX" not in label_set or label_set.intersection(existing_label_ids):
                self.state.discard(message_id)
                summary.skipped += 1
                return
            current_date = self._internal_date(metadata)
            if current_date <= (self.state.activated_at_ms() or 0):
                self.state.discard(message_id)
                summary.skipped += 1
                return
            self.client.add_label(message_id, label_ids[category])
            self.state.mark_applied(message_id, category, float(confidence), current_date)
            summary.applied_by_category[category] += 1
        except GmailAPIError as error:
            self._raise_if_blocked(error)
            if error.safe_code == "invalid_internal_date":
                self.state.mark_needs_review(message_id, internal_date_ms, "invalid_message")
                summary.needs_review += 1
            elif error.safe_code == "http_404":
                self.state.discard(message_id)
                summary.skipped += 1
            else:
                self.state.mark_transient_error(
                    message_id, error.safe_code, internal_date_ms, category, float(confidence)
                )
                summary.record_error(error.safe_code)

    def _process_retryable(
        self,
        record: dict[str, Any],
        activation_ms: int,
        recovery_floor_ms: int | None,
        label_ids: dict[str, str],
        existing_label_ids: set[str],
        summary: PollSummary,
    ) -> None:
        message_id = str(record["message_id"])
        saved_category = record.get("category")
        saved_confidence = record.get("confidence")
        stored_date = record.get("internal_date_ms")
        minimum_date = max(activation_ms, recovery_floor_ms or activation_ms)
        try:
            if saved_category is not None:
                # Retried proposals need metadata only; the stored decision is not rescored.
                message = self.client.message_metadata(message_id)
            else:
                message = self.client.message_for_classification(
                    message_id, existing_label_ids, minimum_date
                )
            label_set = set(message.get("labelIds") or [])
            if "INBOX" not in label_set or label_set.intersection(existing_label_ids):
                self.state.discard(message_id)
                summary.skipped += 1
                return
            internal_date_ms = self._internal_date(message)
            if internal_date_ms <= minimum_date:
                self.state.discard(message_id)
                summary.skipped += 1
                return

            if saved_category is not None:
                if saved_category not in LABELS or not self._valid_confidence(saved_confidence):
                    self.state.mark_needs_review(message_id, internal_date_ms, "invalid_proposal")
                    summary.needs_review += 1
                    return
                if self.config.apply_labels:
                    self._apply_decision(
                        message_id, saved_category, float(saved_confidence), internal_date_ms, label_ids, summary
                    )
                else:
                    self.state.save_proposal(message_id, saved_category, float(saved_confidence), internal_date_ms)
                    summary.proposed_by_category[saved_category] += 1
                return

            payload = message.get("payload")
            if not isinstance(payload, dict):
                self.state.mark_needs_review(message_id, internal_date_ms, "invalid_message")
                summary.needs_review += 1
                return
            body_excerpt = extract_message_text(payload, self.config.max_excerpt_chars)
            sender = get_header(payload, "From")
            subject = get_header(payload, "Subject")
            result = self.classifier.classify(sender, subject, body_excerpt)
            if result.category is None or result.confidence is None:
                self.state.mark_needs_review(message_id, internal_date_ms, result.review_reason or "invalid_response")
                summary.needs_review += 1
                return
            if result.category not in LABELS or not self._valid_confidence(result.confidence):
                self.state.mark_needs_review(message_id, internal_date_ms, "invalid_label")
                summary.needs_review += 1
                return
            if self.config.apply_labels:
                self.state.save_proposal(message_id, result.category, result.confidence, internal_date_ms)
                self._apply_decision(message_id, result.category, result.confidence, internal_date_ms, label_ids, summary)
            else:
                self.state.save_proposal(message_id, result.category, result.confidence, internal_date_ms)
                summary.proposed_by_category[result.category] += 1
        except ClassificationUnavailable:
            self.state.mark_transient_error(message_id, "model_error", stored_date)
            summary.record_error("model_error")
        except GmailAPIError as error:
            self._raise_if_blocked(error)
            if error.safe_code == "invalid_internal_date":
                self.state.mark_needs_review(message_id, stored_date, "invalid_message")
                summary.needs_review += 1
            elif error.safe_code == "http_404":
                self.state.discard(message_id)
                summary.skipped += 1
            else:
                self.state.mark_transient_error(
                    message_id, error.safe_code, stored_date, saved_category, saved_confidence
                )
                summary.record_error(error.safe_code)
        except GmailOperationBlocked:
            raise
        except Exception:
            # Never stringify an unexpected exception; it can contain message content or IDs.
            self.state.mark_transient_error(message_id, "operation_error", stored_date)
            summary.record_error("operation_error")

    @staticmethod
    def _valid_confidence(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and 0.0 <= float(value) <= 1.0
        )

    @staticmethod
    def _raise_if_blocked(error: GmailAPIError) -> None:
        if error.safe_code in {"http_400", "http_401", "http_403", "oauth_refresh_failed"}:
            raise GmailOperationBlocked(error.safe_code) from None

    @staticmethod
    def _internal_date(message: dict[str, Any]) -> int:
        try:
            value = int(message.get("internalDate", 0))
        except (TypeError, ValueError):
            raise GmailAPIError("invalid_internal_date") from None
        if value <= 0:
            raise GmailAPIError("invalid_internal_date")
        return value

    def _apply_decision(
        self,
        message_id: str,
        category: str,
        confidence: float,
        internal_date_ms: int,
        label_ids: dict[str, str],
        summary: PollSummary,
    ) -> None:
        # The model can return only a key; this lookup selects from the fixed allowlist.
        if category not in LABELS or category not in label_ids:
            self.state.mark_needs_review(message_id, internal_date_ms, "invalid_label")
            summary.needs_review += 1
            return
        try:
            self.client.add_label(message_id, label_ids[category])
            self.state.mark_applied(message_id, category, confidence, internal_date_ms)
            summary.applied_by_category[category] += 1
        except GmailAPIError as error:
            self._raise_if_blocked(error)
            self.state.mark_transient_error(
                message_id, error.safe_code, internal_date_ms, category, confidence
            )
            summary.record_error(error.safe_code)
