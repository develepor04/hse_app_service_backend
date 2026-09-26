import ssl
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config.settings import get_settings

settings = get_settings()


def _engine_url_and_connect_args(raw_url: str) -> tuple[str, dict]:
    """Build a PyMySQL-safe URL + connect_args.

    Azure MySQL requires TLS (``require_secure_transport=ON``).

    Passing ``?ssl=true`` in the URL makes SQLAlchemy hand PyMySQL the string
    ``"true"``, which crashes with:
    ``AttributeError: 'str' object has no attribute 'get'``.

    An empty ``ssl={}`` dict also failed to negotiate TLS on App Service
    (``OperationalError: 3159 Connections using insecure transport…``).

    Fix: strip boolean ``ssl`` query params and pass a real ``ssl.SSLContext``.
    """
    parsed = urlparse(raw_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    ssl_requested = False

    ssl_val = query.pop("ssl", None)
    if ssl_val is not None:
        ssl_requested = str(ssl_val).lower() in ("1", "true", "yes", "required")

    # Drop other boolean-style ssl flags that confuse the dialect.
    for key in list(query):
        if key.lower() in ("ssl_mode", "ssl-mode"):
            query.pop(key, None)

    connect_args: dict = {}
    host = (parsed.hostname or settings.db_host or "").lower()
    needs_ssl = (
        ssl_requested
        or "database.azure.com" in host
        or "mysql.database.azure.com" in host
    )
    if needs_ssl and "ssl_ca" not in query:
        # Real SSLContext forces TLS; system CAs cover Azure DigiCert roots.
        ctx = ssl.create_default_context()
        connect_args["ssl"] = ctx

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
