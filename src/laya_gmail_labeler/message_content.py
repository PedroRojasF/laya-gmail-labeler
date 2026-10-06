"""Extract bounded display text from Gmail API MIME payloads."""

from __future__ import annotations

import base64
from email.header import decode_header, make_header
from email.message import Message
from html.parser import HTMLParser
from typing import Any


class _VisibleTextParser(HTMLParser):
    """Collect visible HTML text without loading linked resources."""

    _BLOCKS = {"address", "article", "blockquote", "br", "div", "footer", "h1", "h2", "h3", "h4", "header", "li", "main", "p", "pre", "section", "td", "th", "tr"}
    _HIDDEN = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in self._HIDDEN:
            self._hidden_depth += 1
        elif not self._hidden_depth and tag.lower() in self._BLOCKS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._HIDDEN and self._hidden_depth:
            self._hidden_depth -= 1
        elif not self._hidden_depth and tag in self._BLOCKS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "\n".join(line.strip() for line in "".join(self._chunks).splitlines() if line.strip())


def decode_header_value(value: str) -> str:
    """Decode an RFC 2047 header while tolerating malformed charsets."""
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError, ValueError):
        return value.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _part_charset(part: dict[str, Any]) -> str | None:
    headers = part.get("headers") or []
    content_type = str(part.get("mimeType") or "")
    for header in headers:
        if str(header.get("name", "")).lower() == "content-type":
            content_type = str(header.get("value", content_type))
            break
    message = Message()
    try:
        message["Content-Type"] = content_type
        return message.get_content_charset()
    except (TypeError, ValueError):
        return None


def _decode_part_data(data: str, charset: str | None) -> str:
    padded = data + "=" * (-len(data) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return ""
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            pass
    return raw.decode("utf-8", errors="replace")


def _walk_text_parts(payload: dict[str, Any], plain: list[str], html: list[str]) -> None:
    filename = str(payload.get("filename") or "").strip()
    body = payload.get("body") or {}
    # An attachment body is never downloaded, even when its MIME type is text.
    if filename or body.get("attachmentId"):
        return

    mime_type = str(payload.get("mimeType") or "").lower()
    data = body.get("data")
    if isinstance(data, str) and mime_type in {"text/plain", "text/html"}:
        decoded = _decode_part_data(data, _part_charset(payload))
        if mime_type == "text/plain":
            plain.append(decoded)
        else:
            parser = _VisibleTextParser()
            try:
                parser.feed(decoded)
                parser.close()
                html.append(parser.text())
            except (AssertionError, ValueError):
                # Malformed markup is still treated as data, never interpreted.
                html.append(decoded)

    for child in payload.get("parts") or []:
        if isinstance(child, dict):
            _walk_text_parts(child, plain, html)


def extract_message_text(payload: dict[str, Any], max_chars: int = 3000) -> str:
    """Prefer text/plain, otherwise strip HTML, and cap the result."""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 0:
        raise ValueError("max_chars must be a non-negative integer")
    plain: list[str] = []
    html: list[str] = []
    if isinstance(payload, dict):
        _walk_text_parts(payload, plain, html)
    plain_text = "\n".join(part.strip() for part in plain if part.strip())
    html_text = "\n".join(part.strip() for part in html if part.strip())
    chosen = plain_text if plain_text else html_text
    normalized = "\n".join(line.strip() for line in chosen.splitlines() if line.strip())
    return normalized[:max_chars]


def get_header(payload: dict[str, Any], header_name: str) -> str:
    """Return one decoded Gmail MIME header, if present."""
    wanted = header_name.casefold()
    for header in payload.get("headers") or []:
        if str(header.get("name", "")).casefold() == wanted:
            value = str(header.get("value", ""))
            return decode_header_value(value)
    return ""