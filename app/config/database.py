from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config.settings import get_settings

settings = get_settings()


def _engine_url_and_connect_args(raw_url: str) -> tuple[str, dict]:
    """Build a PyMySQL-safe URL + connect_args.

    Azure MySQL requires TLS. Passing ``?ssl=true`` in the URL makes SQLAlchemy
    hand PyMySQL the string ``"true"``, which crashes with:
    ``AttributeError: 'str' object has no attribute 'get'``.

    We strip boolean-style ``ssl`` query params and enable SSL via connect_args
    (empty dict is enough for Azure Flexible Server).
    """
    parsed = urlparse(raw_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    ssl_requested = False

    ssl_val = query.pop("ssl", None)
    if ssl_val is not None:
        ssl_requested = str(ssl_val).lower() in ("1", "true", "yes", "required")

    # Keep real SSL file/options if present; only remove the broken boolean form.
    connect_args: dict = {}
    host = (parsed.hostname or settings.db_host or "").lower()
    needs_ssl = ssl_requested or "database.azure.com" in host or "mysql.database.azure.com" in host
    if needs_ssl and "ssl_ca" not in query and "ssl" not in query:
        # Empty dict enables TLS without a custom CA bundle on App Service.
        connect_args["ssl"] = {}

    clean_query = urlencode(query)
    clean_url = urlunparse(parsed._replace(query=clean_query))
    return clean_url, connect_args


_db_url, _connect_args = _engine_url_and_connect_args(settings.effective_database_url)

engine = create_engine(
    _db_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    echo=settings.app_debug,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """FastAPI dependency — yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
