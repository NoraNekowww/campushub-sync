#!/usr/bin/env bash
# 在服务器上跑：验证「普通（非管理员）用户能否连接自己的教务 / 微软待办」。
# 只读 + 只动 e2echeck 自己的空空间；不碰任何真实用户的凭据。
# 用法: ssh host 'bash -s' < tools/verify_user_binding.sh
set -u
BASE=http://127.0.0.1:8010/api
ENVF=/var/www/schedule/.env
JAR=$(mktemp /tmp/e2e_jar.XXXXXX)
BODY=$(mktemp /tmp/e2e_body.XXXXXX)
NAME=e2echeck
PASS='E2eCheck!2026'
AT=$(grep -E '^ADMIN_TOKEN=' "$ENVF" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r ')
FAIL=0

hit() { # hit <label> <expected_codes_regex> <curl args...>
  local label="$1" want="$2"; shift 2
  local c
  c=$(curl -s -o "$BODY" -w '%{http_code}' "$@")
  local short
  short=$(head -c 160 "$BODY" | tr -d '\n')
  if [[ "$c" =~ ^($want)$ ]]; then
    printf '  PASS  %-34s %s  %s\n' "$label" "$c" "$short"
  else
    printf '  FAIL  %-34s %s (期望 %s)  %s\n' "$label" "$c" "$want" "$short"
    FAIL=1
  fi
}

echo "=== 1) 匿名访问（必须仍然被挡） ==="
hit "anon DELETE /tju/credentials" "401" -X DELETE "$BASE/tju/credentials"
hit "anon GET /sync/logs" "401" "$BASE/sync/logs"
hit "anon POST /tju/sync" "401" -X POST "$BASE/tju/sync"

echo "=== 2) 用真实非管理员账号登录 ==="
rm -f "$JAR"
code=$(curl -s -o "$BODY" -c "$JAR" -w '%{http_code}' -H 'Content-Type: application/json' \
       -X POST "$BASE/auth/login" -d "{\"username\":\"$NAME\",\"password\":\"$PASS\"}")
echo "  login -> $code"
sess=$(curl -s -b "$JAR" "$BASE/auth/session")
echo "  session -> $sess"
if echo "$sess" | grep -qiE '"role"[[:space:]]*:[[:space:]]*"?(admin|owner)"?|"is_admin"[[:space:]]*:[[:space:]]*true'; then
  echo "  FAIL  这个账号居然是管理员 —— 测不出问题，换账号"; FAIL=1
else
  echo "  PASS  该账号不是管理员"
fi

echo "=== 3) 普通用户连自己的教务系统 ==="
hit "GET  /tju/status" "200" -b "$JAR" "$BASE/tju/status"
hit "POST /tju/credentials(空凭据)" "200|400|422" -b "$JAR" -H 'Content-Type: application/json' \
    -X POST "$BASE/tju/credentials" -d '{}'
hit "DELETE /tju/credentials(自己空间)" "200" -b "$JAR" -X DELETE "$BASE/tju/credentials"
hit "POST /tju/sync(自己的)" "200" -b "$JAR" -X POST "$BASE/tju/sync"

echo "=== 4) 普通用户连自己的微软待办 ==="
hit "GET  /auth/ms/status" "200" -b "$JAR" "$BASE/auth/ms/status"
hit "POST /auth/ms/device/start" "200" -b "$JAR" -X POST "$BASE/auth/ms/device/start"

echo "=== 5) 作用域隔离：普通用户看到的是自己的空状态 ==="
echo "  e2echeck ms/status: $(curl -s -b "$JAR" "$BASE/auth/ms/status")"
if [ -n "$AT" ]; then
  echo "  管理员令牌视角 ms/status: $(curl -s -H "X-Admin-Token: $AT" "$BASE/auth/ms/status")"
  hit "GET /sync/logs + 管理员令牌(老用法)" "200" -H "X-Admin-Token: $AT" "$BASE/sync/logs"
else
  echo "  (跳过：未取到管理员令牌)"
fi

rm -f "$JAR" "$BODY"
echo "=== 结果: $([ $FAIL -eq 0 ] && echo 全部通过 || echo 有失败项) ==="
exit $FAIL
