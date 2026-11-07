"""Logging configuration with sensitive data masking."""

import logging
import re
from typing import List, Set

_sensitive_patterns: List[re.Pattern] = [
    # Telegram Bot Token: digits:string
    re.compile(r"\b\d{8,12}:[a-zA-Z0-9_-]{35,}\b"),
    # Common password parameters in URLs or commands
    re.compile(r"(-p|--password=|\bpassword=|\bpass=|\bPGPASSWORD=|\bMYSQL_PWD=)(\S+)", re.IGNORECASE),
]

_sensitive_exact_values: Set[str] = set()


def register_secret(secret: str) -> None:
    """Register a secret value to be masked in log messages."""
    if secret and len(secret) >= 4:
        _sensitive_exact_values.add(secret)


class SensitiveDataFilter(logging.Filter):
    """Filter to redact bot tokens, passwords and other secrets from logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Format message with args first, then sanitize the entire string
            msg = record.getMessage()
            record.msg = self.sanitize(msg)
            record.args = ()
        except Exception:
            pass
        return True

    @classmethod
    def sanitize(cls, text: str) -> str:
        if not isinstance(text, str):
            return text

        for secret in _sensitive_exact_values:
            text = text.replace(secret, "********")

        for pattern in _sensitive_patterns:
            text = pattern.sub(r"\1********" if pattern.groups == 2 else "********", text)

        return text


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure application logging with secret masking."""
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("backupbot")
    logger.setLevel(level)

    # Avoid adding duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveDataFilter())
        logger.addHandler(handler)

    return logger
