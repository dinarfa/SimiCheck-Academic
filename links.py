"""Normalisasi tautan sumber untuk UI dan ekspor."""

from urllib.parse import quote, urlsplit


def safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme == "https" and parts.hostname and not (parts.username or parts.password):
            return value if not any(ord(char) <= 32 for char in value) else ""
    except ValueError:
        pass
    return ""


def source_link(source: dict) -> str:
    doi = source.get("doi") or ""
    if doi.startswith("10.") and "/" in doi and not any(char.isspace() for char in doi):
        return "https://doi.org/" + quote(doi, safe="/:._-()")
    return safe_url(doi) or safe_url(source.get("source_url") or "")
