"""Re-seal stored credentials with the vault (idempotent).

Run it where the database lives, from ``backend/`` so ``app`` is importable::

    cd /var/www/schedule/backend
    venv/bin/python - --check   < tools/encrypt_kv_secrets.py   # audit, exit 1 if any left
    venv/bin/python - --dry-run < tools/encrypt_kv_secrets.py   # list, change nothing
    venv/bin/python -           < tools/encrypt_kv_secrets.py   # migrate

Rows already carrying the ``enc1:`` marker are left untouched, so re-running is
always safe. Nothing sensitive is printed — only key names and counts.
"""

from __future__ import annotations

import json
import re
import sys

from sqlmodel import select

from app.db import KV, init_db, session_scope
from app.config import get_settings
from app.secretbox import PREFIX, encrypt_value, is_encrypted, is_secret_key, self_check

#: ``u12:`` — multi-tenant namespace prefix, stripped to get the logical key.
_NAMESPACE = re.compile(r"^u\d+:")


def logical_key(stored: str) -> str:
    return _NAMESPACE.sub("", stored, count=1)


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    dry_run = check_only or "--dry-run" in argv

    init_db(get_settings())
    probe = self_check()
    print(f"vault key id : {probe['key_id'] or '(unavailable)'}")
    print(f"self-check   : {'ok' if probe['ok'] else 'FAILED ' + str(probe.get('error'))}")
    if not probe["ok"]:
        return 2

    scanned = sealed = 0
    pending: list[str] = []

    with session_scope() as session:
        for row in session.exec(select(KV)).all():
            if not is_secret_key(logical_key(row.key)):
                continue
            scanned += 1
            try:
                value = json.loads(row.value)
            except json.JSONDecodeError:
                print(f"  ! {row.key}: value is not JSON, skipped")
                continue
            if is_encrypted(value):
                sealed += 1
                continue
            pending.append(row.key)
            if not dry_run:
                row.value = json.dumps(encrypt_value(value), ensure_ascii=False, default=str)
                session.add(row)

    verb = "would seal" if dry_run else "sealed"
    print(f"credential rows: {scanned}   already sealed: {sealed}   pending: {len(pending)}")
    for key in pending:
        print(f"  {verb}: {key}")

    if check_only and pending:
        print("RESULT: FAIL — rerun without --check to migrate")
        return 1
    print("RESULT: OK" + (" (dry run, nothing written)" if dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
