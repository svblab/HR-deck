"""Файловое логирование и перехват необработанных исключений (EPIC-015, ТЗ §8)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from data.paths import logs_dir

_SENSITIVE_MARKERS = (
    "master_key",
    "password",
    "recovery",
    "keywrap",
    "secret",
    "ciphertext",
    "salt_b64",
    "nonce_b64",
)


def _redact(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return "[redacted: sensitive data]"
    return text


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(str(record.msg))
        return True


def configure_logging() -> Path:
    """Настроить ротируемый лог-файл в каталоге данных пользователя."""
    log_root = logs_dir()
    log_root.mkdir(parents=True, exist_ok=True)
    log_file = log_root / "personnel-availability.log"
    handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(_RedactingFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    return log_file


def install_excepthook() -> None:
    """Записать необработанное исключение в лог перед завершением процесса."""

    def _hook(exc_type, exc_value, exc_tb) -> None:  # noqa: ANN001
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
