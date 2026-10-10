#!/usr/bin/env bash
# 凭据加密（credential vault）线上自检 —— 在**服务器上**跑：
#
#   scp -i ~/.ssh/<key> deploy/verify-vault.sh root@<host>:/var/www/schedule/tools/
#   ssh -i ~/.ssh/<key> root@<host> 'bash /var/www/schedule/tools/verify-vault.sh'
#
# 检查四层，任何一层不对都能直接看出是哪层：①数据库里是不是密文形态；
# ②应用层（KVStore）能不能解回原值；③接口层；④真链路：用加密存的教务密码登录 CAS 抓课表。
# 只打印前缀/长度/键名，从不打印口令或令牌内容。
set -u
APP_DIR="${APP_DIR:-/var/www/schedule}"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
PY="${PY:-$APP_DIR/venv/bin/python}"
PORT="${PORT:-8010}"
cd "$APP_DIR/backend" || { echo "找不到 $APP_DIR/backend"; exit 2; }
export DATA_DIR
TOKEN=$(grep -m1 '^ADMIN_TOKEN=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'\r')

echo "===== 1. 数据库里存的样子（前缀/长度；PLAIN! 就是还没加密）====="
$PY - <<'PY'
import os, sqlite3
db = os.path.join(os.environ.get("DATA_DIR", "./data"), "campushub.db")
con = sqlite3.connect(db)
rows = plain = 0
for key, value in con.execute("select key, value from kv order by key"):
    if not any(t in key for t in ("credential", "token", "invite_code", "device_flow")):
        continue
    rows += 1
    sealed = value.startswith('"enc1:')
    plain += 0 if sealed else 1
    print(f"  {'SEALED' if sealed else 'PLAIN!'}  {key:26s} len={len(value):5d}  head={value[:11]}")
print(f"  凭据行: {rows}   未加密: {plain}")
PY

echo "===== 2. 应用层解密（KVStore 读回来的内容 = 用户实际看到的）====="
$PY - <<'PY'
from app.config import get_settings
from app.db import init_db, KVStore
init_db(get_settings())
kv = KVStore()
jw = kv.get("tju.jw_credentials") or {}
print(f"  教务凭据: 学号={'有' if jw.get('username') else '无'} 密码=<{len(jw.get('password') or '')} 字符>")
tok = kv.get("tju.token")
print(f"  微北洋 token: {'已解出' if tok else '无'}")
ms = kv.get("ms.tokens") or {}
print(f"  微软令牌: {sorted(ms.keys()) if isinstance(ms, dict) and ms else '无'}")
PY

echo "===== 3. 接口层（管理员令牌；学号已打码）====="
if [ -n "$TOKEN" ]; then
  echo -n "  /api/tju/jw/status  : "
  curl -s -H "X-Admin-Token: $TOKEN" "http://127.0.0.1:$PORT/api/tju/jw/status" | sed -E 's/[0-9]{6,}/<id>/g' | head -c 260; echo
  echo -n "  /api/auth/ms/status : "
  curl -s -H "X-Admin-Token: $TOKEN" "http://127.0.0.1:$PORT/api/auth/ms/status" | sed -E 's/[0-9]{6,}/<id>/g' | head -c 160; echo
else
  echo "  （.env 里没有 ADMIN_TOKEN，跳过接口检查）"
fi

echo "===== 4. 真链路：用加密存的教务密码登 CAS 抓课表 ====="
if [ -f "$APP_DIR/tools/jw_import_try.py" ]; then
  $PY "$APP_DIR/tools/jw_import_try.py" 6 2>&1 | grep -iE "课|course|slot|event|week|ok|fail|error|学期" | tail -8
else
  echo "  （缺 $APP_DIR/tools/jw_import_try.py，跳过）"
fi

echo "===== 5. 服务与日志 ====="
systemctl is-active campushub-sync 2>/dev/null | sed 's/^/  服务: /'
echo -n "  近 10 分钟含 error/decrypt/key mismatch 的日志行数: "
journalctl -u campushub-sync --since "10 min ago" --no-pager 2>/dev/null | grep -icE "error|traceback|cannot decrypt|key mismatch"
echo "  （注意：microsoft_todo#N failed: no refresh token 是「某用户还没完成微软授权」，与加密无关）"
