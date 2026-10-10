#!/usr/bin/env bash
# 构建前端并原子替换线上 /schedule/ 的静态资源（旧版留 frontend.old，便于回滚）。
# 用法: bash deploy/deploy-frontend.sh
set -euo pipefail
SSH="ssh -i $HOME/.ssh/nzlab_rsa -o StrictHostKeyChecking=accept-new root@nzlab.online"
APP=/var/www/schedule
cd "$(dirname "$0")/../web"

echo "=== 构建（VITE_BASE=/schedule/） ==="
VITE_BASE=/schedule/ npm run build 2>&1 | tail -6
echo "=== 产物 ==="
ls -1 dist/assets

echo "=== 上传 + 原子替换 ==="
tar czf - -C dist . | timeout 240 $SSH "set -e
  rm -rf $APP/frontend.new && mkdir -p $APP/frontend.new
  tar xzf - -C $APP/frontend.new
  rm -rf $APP/frontend.old && mv $APP/frontend $APP/frontend.old
  mv $APP/frontend.new $APP/frontend
  chown -R root:root $APP/frontend
  echo '已替换。当前资源:'; ls -1 $APP/frontend/assets | head -4"

echo "=== 线上 index.html 引用的包 ==="
timeout 60 $SSH "curl -s https://nzlab.online/schedule/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -2"
