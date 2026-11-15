"""مدیریت Secretها و جلوگیری از نشت توکن‌ها در لاگ/پاسخ."""
import re
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\\s+)[A-Za-z0-9\\-_\\.]+", re.IGNORECASE),
    re.compile(r"(ds_session_id[\"']?\\s*[:=]\\s*[\"']?)[A-Za-z0-9\\-_]+", re.IGNORECASE),
    re.compile(r"(cookie[\"']?\\s*[:=]\\s*[\"']?)([^\\s\"',}]+)", re.IGNORECASE),
]

_REDACTION = r"\\1***REDACTED***"


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_REDACTION, out)
    return out


def redact_dict(data: Any) -> Any:
    if isinstance(data, str):
        return redact(data)
    if isinstance(data, dict):
        return {k: redact_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_dict(v) for v in data]
    return data
