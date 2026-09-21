#!/usr/bin/env bash
# 一键启动：后端 8008 + 前端 5174
#
# 用法（在项目根目录）：
#   bash start.sh
#
# Python 解释器查找顺序：
#   1) 环境变量 PYTHON 指定的路径
#   2) backend/.venv（推荐：自己建的项目内虚拟环境）
#   3) 本机已装好的隔离环境（当前开发机使用）
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8008
FRONTEND_PORT=5174

find_python() {
  if [ -n "${PYTHON:-}" ] && [ -x "${PYTHON}" ]; then
    echo "$PYTHON"; return 0
  fi
  for p in \
    "$ROOT/backend/.venv/Scripts/python.exe" \
    "$ROOT/backend/.venv/bin/python" \
    "C:/Users/win11/.workbuddy/binaries/python/envs/sstudent/Scripts/python.exe" \
    "$(command -v python3 2>/dev/null)" \
    "$(command -v python 2>/dev/null)"
  do
    [ -n "$p" ] && [ -x "$p" ] && { echo "$p"; return 0; }
  done
  return 1
}

find_node() {
  for p in \
    "$(command -v node 2>/dev/null)" \
    "C:/Users/win11/.workbuddy/binaries/node/versions/22.22.2/node.exe"
  do
    [ -n "$p" ] && [ -x "$p" ] && { echo "$p"; return 0; }
  done
  return 1
}

port_busy() {
  netstat -ano 2>/dev/null | grep -qE ":$1[[:space:]].*LISTENING"
}

# 端口探测：优先用 bash 内建 /dev/tcp，比 curl 更可靠
# （本机 curl 短超时会误报 exit 28，不能用 -m 2 这种短超时做就绪判断）
probe() {
  ( echo > "/dev/tcp/127.0.0.1/$1" ) >/dev/null 2>&1 && return 0
  port_busy "$1"
}

wait_ready() {
  printf "• 等待 %s 就绪" "$1"
  for _ in $(seq 1 30); do
    if probe "$1"; then echo " ✓"; return 0; fi
    printf "."; sleep 1
  done
  echo " ✗ 超时（请查看日志）"
  return 1
}

PY="$(find_python)" || { echo "✗ 找不到可用的 Python，请设置环境变量 PYTHON 指向解释器"; exit 1; }
NODE="$(find_node)"  || { echo "✗ 找不到可用的 Node.js"; exit 1; }

echo "Python : $PY"
echo "Node   : $NODE"

# ---------------- 后端 ----------------
if port_busy "$BACKEND_PORT"; then
  echo "• 后端已在 $BACKEND_PORT 运行，跳过启动"
else
  echo "• 启动后端 (http://127.0.0.1:$BACKEND_PORT) ..."
  ( cd "$ROOT/backend" && nohup "$PY" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$BACKEND_PORT" \
      > "$ROOT/backend/uvicorn.log" 2>&1 & )
fi

# ---------------- 前端 ----------------
if port_busy "$FRONTEND_PORT"; then
  echo "• 前端已在 $FRONTEND_PORT 运行，跳过启动"
else
  [ -d "$ROOT/frontend/node_modules" ] || { echo "• 首次运行，安装前端依赖 ..."; ( cd "$ROOT/frontend" && "$NODE" "$(dirname "$NODE")/npm" install ); }
  echo "• 启动前端 (http://127.0.0.1:$FRONTEND_PORT) ..."
  ( cd "$ROOT/frontend" && nohup "$NODE" node_modules/vite/bin/vite.js \
      --port "$FRONTEND_PORT" --host 127.0.0.1 \
      > "$ROOT/frontend/vite.log" 2>&1 & )
fi

# ---------------- 等待就绪 ----------------
wait_ready "$BACKEND_PORT" || true
wait_ready "$FRONTEND_PORT" || true
echo

echo "================= 启动完成 ================="
HEALTH="$("$PY" -c "
import urllib.request, json
try:
    print(urllib.request.urlopen('http://127.0.0.1:$BACKEND_PORT/health', timeout=10).read().decode())
except Exception as e:
    print('无响应:', e)
" 2>/dev/null)"
echo "后端健康检查 : ${HEALTH:-无响应}"
echo "前端页面     : http://127.0.0.1:$FRONTEND_PORT"
echo "接口文档     : http://127.0.0.1:$BACKEND_PORT/docs"
echo
echo "演示账号（密码统一 123456）：admin / T1001 / 24CS101 / 25SE203 / 26DS105"
echo "日志：backend/uvicorn.log  frontend/vite.log"
echo "============================================"
