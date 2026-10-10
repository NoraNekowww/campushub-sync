#!/bin/bash
# Live verification of the 微北洋 (TJU) connector deployment.
set -u
cd /var/www/schedule

TOKEN=$(grep -m1 '^ADMIN_TOKEN=' .env | cut -d= -f2- | tr -d '"')
SUB=$(grep -m1 '^SUBSCRIBE_TOKEN=' .env | cut -d= -f2- | tr -d '"')

echo "===== 1) /api/tju/status (with campus probe) ====="
curl -s -m 30 -H "X-Admin-Token: $TOKEN" "http://127.0.0.1:8010/api/tju/status?probe=true" | head -c 1100
echo
echo

echo "===== 2) server-side login path (deliberately wrong password) ====="
curl -s -m 30 -X POST -H "X-Admin-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"mode":"password","username":"0000000000","password":"wrong-password"}' \
  -w " [HTTP %{http_code}]" "http://127.0.0.1:8010/api/tju/credentials"
echo
echo

echo "===== 3) public paths + new frontend asset ====="
curl -s -o /dev/null -w "portal        %{http_code}\n" https://nzlab.online/
curl -s -o /dev/null -w "app           %{http_code}\n" https://nzlab.online/schedule/
curl -s -o /dev/null -w "new asset     %{http_code}\n" https://nzlab.online/schedule/assets/index-Dagrr90f.js
curl -s -o /dev/null -w "tju api anon  %{http_code}\n" https://nzlab.online/schedule/api/tju/status
curl -s -o /dev/null -w "ics feed      %{http_code}\n" "https://nzlab.online/schedule/api/subscribe/calendar.ics?token=$SUB"
echo

echo "===== 4) new panel present in the built bundle ====="
grep -c "微北洋直连" frontend/assets/index-Dagrr90f.js || true
grep -c "open.twt.edu.cn" frontend/assets/index-Dagrr90f.js || true
echo

echo "===== 5) service health + recent log ====="
systemctl is-active campushub-sync
journalctl -u campushub-sync -n 12 --no-pager | tail -12
