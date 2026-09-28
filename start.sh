#!/usr/bin/env bash
# 一键启动知识图谱 RAG 系统
# 用法:
#   ./start.sh            # 生产模式：单端口 http://localhost:8001
#   ./start.sh dev        # 开发模式：前端 :5173 + 后端 :8001
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-prod}"
BACKEND_PORT=8001
FRONTEND_PORT=5173
BACKEND_PID=""
VITE_PID=""

# ---------- conda 环境 ----------
CONDA_BASE="$(conda info --base 2>/dev/null || echo /opt/anaconda3)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate langchain
PYTHONPATH="$SCRIPT_DIR/src"
export PYTHONPATH

# ---------- 工具函数 ----------
log() { echo -e "$1"; }

# 清理本项目自身的旧进程（按命令行特征识别，避免误杀用户其他服务）
kill_stale() {
  local port="$1" name="$2" pattern="$3"
  local pid
  pid="$(lsof -ti :"$port" -sTCP:LISTEN -P -n 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    if ps -p "$pid" -o command= 2>/dev/null | grep -q "$pattern"; then
      log "  ⚠️  检测到旧的 $name 实例 (PID $pid)，已自动清理"
      kill "$pid" 2>/dev/null
      sleep 1
    else
      log "  ❌ 端口 $port 被其他进程监听（非本项目）：PID $pid"
      log "     $(ps -p "$pid" -o command= 2>/dev/null)"
      log "     请先处理该进程，或修改 start.sh 中的端口后重试"
      exit 1
    fi
  fi
}

open_browser() {
  local url="$1"
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi
}

# 轮询等待服务就绪（后端首次导入 torch 较慢）
wait_ready() {
  local url="$1" timeout="${2:-60}"
  for _ in $(seq 1 "$timeout"); do
    if curl -sf "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

cleanup() {
  log "\n正在停止服务..."
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$VITE_PID" ] && kill "$VITE_PID" 2>/dev/null || true
  wait 2>/dev/null
  log "已停止。再见 👋"
  exit 0
}
trap cleanup INT TERM

# ---------- 启动 ----------
if [ "$MODE" = "dev" ]; then
  log "▶ 开发模式：前端 :$FRONTEND_PORT + 后端 :$BACKEND_PORT"
  kill_stale "$BACKEND_PORT" "后端" "graphrag.api.main"
  kill_stale "$FRONTEND_PORT" "前端" "web"
  PYTHONPATH="$PYTHONPATH" uvicorn src.graphrag.api.main:app --reload --port "$BACKEND_PORT" &
  BACKEND_PID=$!
  (cd web && npm run dev) &
  VITE_PID=$!
  wait_ready "http://localhost:$BACKEND_PORT/api/health" || log "  ⚠️  后端就绪等待超时，请查看上方日志"
  wait_ready "http://localhost:$FRONTEND_PORT/" || log "  ⚠️  前端就绪等待超时，请查看上方日志"
  log "✅ 前端已启动:  http://localhost:$FRONTEND_PORT"
  log "   （API 代理到后端 :$BACKEND_PORT）"
  open_browser "http://localhost:$FRONTEND_PORT"
else
  log "▶ 生产模式：单端口 http://localhost:$BACKEND_PORT"
  kill_stale "$BACKEND_PORT" "后端" "graphrag.api.main"
  if [ ! -f web/dist/index.html ]; then
    log "  未检测到前端构建产物，正在执行 npm run build ..."
    (cd web && npm run build) || { log "❌ 前端构建失败"; exit 1; }
  fi
  PYTHONPATH="$PYTHONPATH" uvicorn src.graphrag.api.main:app --port "$BACKEND_PORT" &
  BACKEND_PID=$!
  wait_ready "http://localhost:$BACKEND_PORT/api/health" || { log "❌ 后端启动失败，请查看上方日志"; exit 1; }
  log "✅ 系统已启动:  http://localhost:$BACKEND_PORT"
  log "   （前端已内嵌于后端，单端口访问）"
  open_browser "http://localhost:$BACKEND_PORT"
fi

log ""
log "按 Ctrl+C 停止全部服务"
wait
