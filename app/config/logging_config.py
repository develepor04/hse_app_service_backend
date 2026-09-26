import logging
import logging.handlers
import os
import time
from app.config.settings import get_settings


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that tolerates a locked log file on Windows.

    os.rename() fails with PermissionError if another process (a stale run,
    antivirus, a log viewer) still has app.log open. Without this, every
    subsequent emit() re-triggers the same failing rollover, flooding stderr
    with one traceback per log line. Skip rollover and retry later instead.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._retry_after = 0.0

    def shouldRollover(self, record):
        if time.monotonic() < self._retry_after:
            return False
        return super().shouldRollover(record)

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            self._retry_after = time.monotonic() + 60


def configure_logging() -> None:
    settings = get_settings()
    os.makedirs(settings.log_dir, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler ──────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)

    # ── Rotating file handler (all logs) ─────────────────────────────────────
    app_file = SafeRotatingFileHandler(
        filename=os.path.join(settings.log_dir, "app.log"),
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    app_file.setLevel(level)
    app_file.setFormatter(fmt)

    # ── Rotating file handler (errors only) ──────────────────────────────────
    err_file = SafeRotatingFileHandler(
        filename=os.path.join(settings.log_dir, "error.log"),
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    err_file.setLevel(logging.ERROR)
    err_file.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(app_file)
    root.addHandler(err_file)

    # Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.app_debug else logging.WARNING
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
