#!/usr/bin/env bash
# 清掉「加密之前」留在库文件/WAL 里的明文残留 —— 在**服务器上**跑：
#
#   scp -i ~/.ssh/<key> deploy/purge-plaintext-residue.sh root@<host>:/tmp/
#   ssh -i ~/.ssh/<key> root@<host> 'bash /tmp/purge-plaintext-residue.sh'
#
# 为什么需要它：KVStore 的 UPDATE 只写了新页，旧的口令行可能还留在 SQLite 的空白页
# 和 WAL 里（实测迁移后 db 里 2 处、WAL 里 16 处 `"password":` 字面量）。VACUUM +
# wal_checkpoint(TRUNCATE) 之后才是 0/0。
#
# 脚本只按「JSON 键名」这类标记计数，从不打印口令、token 或任何凭据内容。
set -u
DATA_DIR="${DATA_DIR:-/var/www/schedule/data}"
PY="${PY:-/var/www/schedule/venv/bin/python}"
DB="$DATA_DIR/campushub.db"
cd "$DATA_DIR" || { echo "找不到 $DATA_DIR"; exit 1; }

echo "== ① 整理前的明文残留（'\`\"password\"\`' 字面量出现次数；不是口令本身）=="
printf "   db=%s  wal=%s\n" \
  "$(grep -ac '"password"' "$DB")" \
  "$(grep -ac '"password"' "$DB-wal" 2>/dev/null || echo 0)"

echo "== ② VACUUM + 截断 WAL =="
"$PY" - "$DB" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1], timeout=30)
con.execute("PRAGMA busy_timeout=20000")
con.execute("VACUUM")
print("   VACUUM ok")
print("   wal_checkpoint(TRUNCATE) ->", con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
con.close()
PY

echo "== ③ 整理后 =="
printf "   db=%s  wal=%s   （期望 0 / 0）\n" \
  "$(grep -ac '"password"' "$DB")" \
  "$(grep -ac '"password"' "$DB-wal" 2>/dev/null || echo 0)"

echo "== ④ 完整性 + 行数（确认 VACUUM 没弄坏数据）=="
"$PY" - "$DB" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
print("   integrity_check:", con.execute("PRAGMA integrity_check").fetchone()[0])
for t in ("events", "kv", "users", "connector_logs"):
    try:
        print("   %-16s %d 行" % (t, con.execute("select count(*) from %s" % t).fetchone()[0]))
    except sqlite3.Error as exc:
        print("   %-16s 跳过（%s）" % (t, exc))
PY

echo "== ⑤ 服务日志里漏过口令吗（按标记计数）=="
printf "   命中: %s 行\n" "$(journalctl -u campushub-sync --since '30 days ago' --no-pager 2>/dev/null | grep -icE '"password"|jw_credentials')"
echo "== ⑥ 服务状态：$(systemctl is-active campushub-sync) =="
