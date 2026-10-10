#!/usr/bin/env bash
# CampusHub Sync — first-time installer / upgrader for laserver01-nz (nzlab.online).
#
#   scp the release tarball to /tmp, extract it into /var/www/schedule, then:
#       sed -i 's/\r$//' /var/www/schedule/deploy/install.sh
#       bash /var/www/schedule/deploy/install.sh
#
# Idempotent: re-running it upgrades the code and restarts the service, but it
# never overwrites an existing .env (that is where your secrets live).
set -euo pipefail

APP=/var/www/schedule
SERVICE=campushub-sync
SNIPPET=/etc/nginx/snippets/campushub-sync.conf
SITE=/etc/nginx/sites-available/default

cd "$APP"

echo "==> [1/6] python venv"
if [ ! -x "$APP/venv/bin/python" ]; then
    python3 -m venv "$APP/venv" || {
        echo "    python3-venv missing, installing it"
        apt-get update -qq && apt-get install -y -qq python3-venv
        python3 -m venv "$APP/venv"
    }
fi
"$APP/venv/bin/pip" install --upgrade pip -q
"$APP/venv/bin/pip" install -r "$APP/backend/requirements.txt" -q
echo "    $( "$APP/venv/bin/python" -V ) with $( "$APP/venv/bin/pip" list --format=freeze | wc -l ) packages"

echo "==> [2/6] data directory"
mkdir -p "$APP/data"
chmod 700 "$APP/data"

echo "==> [3/6] .env"
if [ -f "$APP/.env" ]; then
    echo "    keeping the existing .env ($( grep -c . "$APP/.env" ) lines)"
else
    ADMIN_TOKEN=$(openssl rand -hex 24)
    SUBSCRIBE_TOKEN=$(openssl rand -hex 24)
    INVITE_CODE=$(openssl rand -hex 4)
    # NOTE: no inline comments below — systemd's EnvironmentFile takes the whole
    # right-hand side literally, unlike python-dotenv.
    cat > "$APP/.env" <<EOF
APP_NAME=CampusHub Sync
DEBUG=false
DATA_DIR=$APP/data
TIMEZONE=Asia/Shanghai

ADMIN_TOKEN=$ADMIN_TOKEN
SUBSCRIBE_TOKEN=$SUBSCRIBE_TOKEN
PUBLIC_BASE_URL=https://nzlab.online/schedule

ENABLE_SCHEDULER=true
SYNC_ON_STARTUP=true
SYNC_INTERVAL_MINUTES=20
EVENT_RETENTION_DAYS=30
HORIZON_DAYS=120
HTTP_TIMEOUT_SECONDS=20
HTTP_MAX_RETRIES=3

ENABLE_ACCOUNTS=true
ALLOW_OPEN_REGISTRATION=false
REGISTRATION_INVITE_CODE=$INVITE_CODE
FIRST_USER_IS_ADMIN=true
PASSWORD_MIN_LENGTH=8
SESSION_TTL_HOURS=336
SESSION_COOKIE_NAME=campushub_session
SESSION_COOKIE_PATH=/
SESSION_COOKIE_SECURE=true
SESSION_SECRET=

MS_CLIENT_ID=
MS_CLIENT_SECRET=
MS_TENANT=common
MS_SCOPES=Tasks.ReadWrite offline_access
MS_INCLUDE_COMPLETED=false
MS_INCLUDE_UNDUE=false

TJU_MODE=demo
TJU_ICS_PATH=timetable.ics
SEMESTER_NAME=2026 秋季学期
SEMESTER_START_DATE=2026-09-07
SEMESTER_TOTAL_WEEKS=16

DEMO_MODE=true
EOF
    chmod 600 "$APP/.env"
    echo "    wrote $APP/.env (0600)"
    echo "    ADMIN_TOKEN=$ADMIN_TOKEN"
    echo "    SUBSCRIBE_TOKEN=$SUBSCRIBE_TOKEN"
    echo "    REGISTRATION_INVITE_CODE=$INVITE_CODE"
fi

echo "==> [4/6] systemd unit"
install -m 644 "$APP/deploy/systemd/$SERVICE.service" "/etc/systemd/system/$SERVICE.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
sleep 2
systemctl is-active "$SERVICE" && echo "    $SERVICE is active on 127.0.0.1:8010"

echo "==> [5/6] nginx snippet + include"
install -d /etc/nginx/snippets
install -m 644 "$APP/deploy/nginx/nzlab.online.schedule.conf" "$SNIPPET"

if ! grep -q 'campushub-sync.conf' "$SITE"; then
    cp "$SITE" "$SITE.bak.$(date +%Y%m%d%H%M%S)"
    python3 - "$SITE" <<'PY'
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    text = handle.read()
snippet = "\n    # CampusHub Sync 日程表 /schedule/ —— 由 deploy/install.sh 插入\n    include /etc/nginx/snippets/campushub-sync.conf;\n"
index = text.rstrip().rfind("}")          # closing brace of the 443 server block
if index == -1:
    raise SystemExit("could not find the server block")
with open(path, "w", encoding="utf-8") as handle:
    handle.write(text[:index] + snippet + text[index:])
print("    include line added to", path)
PY
else
    echo "    include already present"
fi

echo "==> [6/6] nginx reload"
nginx -t
systemctl reload nginx
echo
echo "done.  https://nzlab.online/schedule/  (API on 127.0.0.1:8010)"
