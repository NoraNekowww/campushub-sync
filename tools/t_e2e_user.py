"""E2E 临时账号：让「已登录」状态下的设置页能被真浏览器验证。

用法（必须 cd backend，否则读不到 .env）：
    ssh host 'cd /var/www/schedule/backend && /var/www/schedule/venv/bin/python -' < tools/t_e2e_user.py
    ssh host 'cd /var/www/schedule/backend && /var/www/schedule/venv/bin/python - --cleanup' < tools/t_e2e_user.py

只创建/删除本脚本自己那个账号，不碰任何真实用户。
"""

from __future__ import annotations

import inspect
import sys

from app import accounts
from app.db import session_scope

USERNAME = "e2echeck"
PASSWORD = "E2eCheck!2026"
CLEANUP = "--cleanup" in sys.argv


def _kwargs_for(func, candidates: dict) -> dict:
    params = inspect.signature(func).parameters
    return {k: v for k, v in candidates.items() if k in params}


def main() -> int:
    with session_scope() as session:
        existing = accounts.get_by_username(session, USERNAME)

        if CLEANUP:
            if not existing:
                print("cleanup: 没有临时账号，无需处理")
                return 0
            session.delete(existing)
            session.commit()
            print(f"cleanup: 已删除临时账号 {USERNAME} (#{existing.id})")
            return 0

        if existing:
            print(f"已存在临时账号 {USERNAME} (#{existing.id})")
            return 0

        sig = inspect.signature(accounts.create_user)
        kwargs = _kwargs_for(
            accounts.create_user,
            {
                "username": USERNAME,
                "password": PASSWORD,
                "display_name": "E2E Check",
                "is_admin": False,
                "active": True,
                "is_active": True,
            },
        )
        user = accounts.create_user(session, **kwargs)
        print(f"已创建临时账号 {USERNAME} (#{user.id}) | create_user{sig}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
