"""Shared fixtures.

Environment variables are set *before* any application module is imported so the
cached ``Settings`` (and the SQLAlchemy engine) point at a scratch directory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="campushub-tests-"))

os.environ.update(
    {
        "DATA_DIR": str(_TMP_ROOT),
        "ENABLE_SCHEDULER": "false",
        "SYNC_ON_STARTUP": "false",
        "DEMO_MODE": "true",
        "ADMIN_TOKEN": "test-admin",
        "SUBSCRIBE_TOKEN": "test-sub",
        "MS_CLIENT_ID": "",
        "TJU_MODE": "disabled",
        "TJU_ICS_PATH": "",
        "LOG_LEVEL": "WARNING",
    }
)


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_state():
    """Fresh database + caches for every test."""
    from app import db
    from app.config import get_settings
    from app.services.scheduler import reset_scheduler
    from app.services.sync_engine import reset_sync_engine

    reset_scheduler()
    reset_sync_engine()
    get_settings.cache_clear()
    db.reset_engine()
    for suffix in ("", "-wal", "-shm"):
        target = _TMP_ROOT / f"campushub.db{suffix}"
        if target.exists():
            try:
                target.unlink()
            except OSError:  # pragma: no cover - windows file locks
                pass
    db.init_db()
    yield
    reset_scheduler()
    reset_sync_engine()
    db.reset_engine()
    get_settings.cache_clear()


@pytest.fixture()
def settings():
    from app.config import get_settings

    return get_settings()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "test-admin"}


@pytest.fixture()
def sample_ics() -> bytes:
    return b"""BEGIN:VCALENDAR
PRODID:-//TJU//Timetable//CN
VERSION:2.0
BEGIN:VTIMEZONE
TZID:Asia/Shanghai
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:+0800
TZOFFSETTO:+0800
TZNAME:CST
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:course-math@tju
SUMMARY:\xe9\xab\x98\xe7\xad\x89\xe6\x95\xb0\xe5\xad\xa6
LOCATION:26 \xe6\x95\x99\xe5\xad\xa6\xe6\xa5\xbc 301
DTSTART;TZID=Asia/Shanghai:20260907T083000
DTEND;TZID=Asia/Shanghai:20260907T100500
RRULE:FREQ=WEEKLY;INTERVAL=1;COUNT=16
END:VEVENT
BEGIN:VEVENT
UID:course-physics@tju
SUMMARY:\xe5\xa4\xa7\xe5\xad\xa6\xe7\x89\xa9\xe7\x90\x86
DTSTART;TZID=Asia/Shanghai:20260908T102500
DTEND;TZID=Asia/Shanghai:20260908T120000
RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20270111T160000Z
END:VEVENT
END:VCALENDAR
"""
