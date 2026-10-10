"""一次性迁移到多租户（可重复执行，幂等）。

做三件事：

1. 建表 + 给已存在的表补列（``events.user_id``）—— SQLModel 的 ``create_all``
   不会改老表；
2. 把 ``user_id IS NULL`` 的历史事件判给 owner（第一个管理员账号）；
3. 把多租户之前那份**全局**凭据键（``ms.*`` / ``tju.*``）复制进 owner 的
   命名空间 ``u<id>:`` —— 老的连接照样工作，原件保留以免误删。

服务器上跑::

    cd /var/www/schedule/backend && /var/www/schedule/venv/bin/python /tmp/migrate_tenancy.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/var/www/schedule/backend")

from app.accounts import owner  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import (  # noqa: E402
    KVStore,
    adopt_legacy_keys,
    ensure_columns,
    init_db,
    session_scope,
)
from app.services.events import claim_orphan_events  # noqa: E402

#: 多租户之前这些键是全局的，属于「第一个账号」
LEGACY_PREFIXES = ("ms.", "tju.")


def main() -> int:
    settings = get_settings()
    init_db(settings)
    applied = ensure_columns(settings)
    print("schema:", ", ".join(applied) if applied else "already current")

    with session_scope() as session:
        who = owner(session)
        if who is None:
            print("没有账号 —— 先注册一个（注册页），再重跑本脚本", file=sys.stderr)
            return 1
        claimed = claim_orphan_events(session, who.id)
        uid, uname = who.id, who.username
    print(f"owner: #{uid} {uname}")
    print(f"events adopted: {claimed}")

    copied = adopt_legacy_keys(f"u{uid}:", LEGACY_PREFIXES)
    print(f"legacy kv keys copied into u{uid}:: {copied}")

    store = KVStore(f"u{uid}:")
    print("ms keys  :", store.keys("ms."))
    print("tju keys :", store.keys("tju."))
    with session_scope() as session:
        from sqlmodel import col, func, select

        from app.models import Event

        total = session.exec(select(func.count()).select_from(Event)).one()
        mine = session.exec(
            select(func.count()).select_from(Event).where(col(Event.user_id) == uid)
        ).one()
        orphan = session.exec(
            select(func.count()).select_from(Event).where(col(Event.user_id).is_(None))
        ).one()
    print(f"events: total={total} user#{uid}={mine} unowned={orphan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
