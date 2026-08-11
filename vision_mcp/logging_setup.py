from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from .config import local_dir


class RedactingFilter(logging.Filter):
    patterns = (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?([^\s,;]+)"),
        re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)([^\s,;]+)"),
        re.compile(r"\b(?:sk-|key-)[A-Za-z0-9_-]{8,}\b"),
        re.compile(r"data:(?:image|video)/[^;]+;base64,[A-Za-z0-9+/=]+"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        return True


def redact_text(value: object, limit: int = 2000) -> str:
    message = str(value)
    for pattern in RedactingFilter.patterns:
        message = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", message)
    return message[:limit]


def setup_logging(component: str) -> None:
    folder = local_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / f"{component}.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
