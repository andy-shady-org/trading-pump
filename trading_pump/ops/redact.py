"""Credential redaction for URLs written to status files, logs, events and alerts.

Provider URLs often carry API keys (``?api-key=…``, ``/v2/<key>``, ``user:pass@``).
The raw URL stays in memory for making requests; anything persisted or displayed
goes through :func:`redact_url` / :func:`redact_text` first (BUG-102).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from solders.pubkey import Pubkey

MASK = "***"

# Query parameter names that carry credentials (compared case-insensitively,
# ignoring ``-`` and ``_``).
_SECRET_QUERY_KEYS = frozenset(
    {
        "apikey",
        "key",
        "token",
        "accesstoken",
        "authtoken",
        "xtoken",
        "secret",
        "password",
        "auth",
        "signature",
        "sig",
    }
)

# A path segment that looks like a key: long, and made of key-ish characters
# with at least one digit (QuickNode/Alchemy/Infura style ``/v2/<key>``).
_KEY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_\-]{20,}$")
_DIGIT_RE = re.compile(r"\d")

# URLs embedded in free text (log lines, exception strings such as aiohttp's
# ``url='wss://…'``).
_URL_IN_TEXT_RE = re.compile(r"\b(?:https?|wss?|grpcs?)://[^\s'\"<>()\[\]{},]+")


def _normalise_key(name: str) -> str:
    return name.lower().replace("-", "").replace("_", "")


def _is_solana_pubkey(segment: str) -> bool:
    """Mint/wallet addresses in API paths are public, not credentials."""
    if not 32 <= len(segment) <= 44:
        return False
    try:
        Pubkey.from_string(segment)
    except Exception:
        return False
    return True


def _is_key_segment(segment: str) -> bool:
    return (
        bool(_KEY_SEGMENT_RE.match(segment))
        and bool(_DIGIT_RE.search(segment))
        and not _is_solana_pubkey(segment)
    )


def redact_url(url: Any) -> str:
    """Return ``url`` with credentials masked; scheme, host and plain path kept.

    Masks ``user:password@`` userinfo, values of credential query parameters and
    key-like path segments. Non-URL input is returned as ``str(url)`` unchanged;
    a URL without credentials is returned unchanged.
    """
    text = "" if url is None else str(url)
    if "://" not in text:
        return text
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    if not parts.netloc:
        return text

    changed = False
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{MASK}@{netloc.rsplit('@', 1)[1]}"
        changed = True

    segments = parts.path.split("/")
    masked_segments = [MASK if _is_key_segment(s) else s for s in segments]
    if masked_segments != segments:
        changed = True
    path = "/".join(masked_segments)

    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        masked_pairs = [
            (k, MASK if _normalise_key(k) in _SECRET_QUERY_KEYS and v else v)
            for k, v in pairs
        ]
        if masked_pairs != pairs:
            query = urlencode(masked_pairs, safe="*")
            changed = True

    if not changed:
        return text
    return urlunsplit((parts.scheme, netloc, path, query, parts.fragment))


def redact_text(text: Any) -> str:
    """Redact every URL found in a free-text message."""
    message = "" if text is None else str(text)
    if "://" not in message:
        return message

    def _replace(match: re.Match[str]) -> str:
        # Sentence punctuation after a URL is not part of it.
        url = match.group(0)
        stripped = url.rstrip(".;:!?")
        return redact_url(stripped) + url[len(stripped) :]

    return _URL_IN_TEXT_RE.sub(_replace, message)


__all__ = ["MASK", "redact_text", "redact_url"]
