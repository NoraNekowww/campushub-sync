"""Engine/session plumbing and the small KV store used by connectors."""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional, Sequence

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from .config import Settings, get_settings
from .models import KV
from .timeutil import as_stored, utcnow

log = logging.getLogger("campushub.db")

_engine = None
_engine_lock = threading.Lock()

_KEYS = ("kv", "events", "sync_runs", "connector_logs")


def get_engine(settings: Optional[Settings] = None):
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            settings = settings or get_settings()
            settings.ensure_dirs()
            url = settings.db_url
            kwargs: dict[str, Any] = {"echo": False, "future": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            engine = create_engine(url, **kwargs)

            if url.startswith("sqlite"):

                @event.listens_for(engine, "connect")
                def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.close()

            _engine = engine
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (used by tests that swap the database)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def init_db(settings: Optional[Settings] = None) -> None:
    engine = get_engine(settings)
    SQLModel.metadata.create_all(engine)
    applied = ensure_columns(settings)
    if applied:
        log.info("schema migrated: %s", ", ".join(applied))
    log.debug("database initialised at %s", engine.url)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background jobs and connectors.

    ``expire_on_commit=False`` keeps already-loaded attributes readable after the
    session closes, which is what lets the service layer hand model instances back
    to the API/audit trail without lazy-load surprises.
    """
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


#: 当前请求的 KV 作用域，形如 ``u3:``（多租户）。``security.bind_user_scope``
#: 负责设置它，之后所有 ``KVStore()`` 都自动落在该账号自己的键上。
_CURRENT_SCOPE: ContextVar[str] = ContextVar("kv_scope", default="")


def bind_scope(user_id: Optional[int]) -> None:
    """把当前请求/任务的 KV 作用域设为该账号（``None`` = 全局空间）。"""
    _CURRENT_SCOPE.set(f"u{user_id}:" if user_id is not None else "")


class KVStore:
    """JSON key/value facade over the ``kv`` table.

    ``namespace`` is how multi-tenancy works: ``KVStore("u3:")`` turns every key
    into ``u3:ms.tokens``, so each account gets its own Microsoft tokens and its
    own 教务 credentials. Connectors only ever touch ``self.store`` and therefore
    need no notion of users at all.
    """

    def __init__(self, namespace: Optional[str] = None, *, global_: bool = False) -> None:
        """``namespace=None`` 时跟随「当前登录账号」的作用域。

        多租户的关键：请求进来时 ``bind_user_scope`` 会把作用域放进 contextvar，
        于是**所有** ``KVStore()``（连接器、教务导入、凭据接口）都自动落到自己
        账号的键前缀上，没有一行代码需要知道用户是谁。传 ``""`` 或
        ``global_=True`` 才是全局空间（注册设置这类全站配置用）。
        """
        if namespace is None:
            namespace = "" if global_ else _CURRENT_SCOPE.get()
        self.namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self.namespace}{key}"

    def get(self, key: str, default: Any = None) -> Any:
        with session_scope() as session:
            row = session.get(KV, self._key(key))
            if row is None:
                return default
            try:
                return json.loads(row.value)
            except json.JSONDecodeError:
                return default

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        full = self._key(key)
        with session_scope() as session:
            row = session.get(KV, full)
            if row is None:
                session.add(KV(key=full, value=payload, updated_at=utcnow()))
            else:
                row.value = payload
                row.updated_at = utcnow()
                session.add(row)

    def delete(self, key: str) -> None:
        with session_scope() as session:
            row = session.get(KV, self._key(key))
            if row is not None:
                session.delete(row)

    def keys(self, prefix: str = "") -> list[str]:
        with session_scope() as session:
            stmt = select(KV.key)
            if prefix:
                stmt = stmt.where(KV.key.startswith(self._key(prefix)))  # type: ignore[attr-defined]
            elif not self.namespace:
                pass
            else:
                stmt = stmt.where(KV.key.startswith(self.namespace))  # type: ignore[attr-defined]
            found = list(session.exec(stmt).all())
        return [key[len(self.namespace) :] for key in found] if self.namespace else found


def adopt_legacy_keys(namespace: str, prefixes: Sequence[str]) -> int:
    """Copy pre-multi-tenant global keys into ``namespace`` (idempotent).

    The originals are left alone: they are useless to the running app (every
    reader is namespaced now) but keeping them means a botched migration can be
    redone without re-running the whole device-code flow.
    """
    moved = 0
    with session_scope() as session:
        for row in session.exec(select(KV)).all():
            if row.key.startswith("u") and ":" in row.key:
                continue  # already namespaced
            if not any(row.key == item or row.key.startswith(item) for item in prefixes):
                continue
            if session.get(KV, f"{namespace}{row.key}") is not None:
                continue  # already adopted
            session.add(KV(key=f"{namespace}{row.key}", value=row.value, updated_at=utcnow()))
            moved += 1
    return moved


def ensure_columns(settings: Optional[Settings] = None) -> list[str]:
    """Tiny SQLite migration: ``create_all`` never adds a column to a live table."""
    engine = get_engine(settings)
    additions = (("events", "user_id", "INTEGER"),)
    applied: list[str] = []
    with engine.begin() as conn:
        for table, column, ddl in additions:
            existing = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
            if not existing or column in existing:
                continue
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table}({column})")
            applied.append(f"{table}.{column}")
    return applied



def healthcheck() -> dict[str, Any]:
    try:
        with session_scope() as session:
            session.exec(select(KV.key).limit(1)).all()
        return {"ok": True, "database": str(get_engine().url)}
    except Exception as exc:  # pragma: no cover - only on broken volumes
        return {"ok": False, "error": str(exc)}
