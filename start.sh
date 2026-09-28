#!/usr/bin/env bash
# GraphRAG 启动脚本
#   ./start.sh            # 启动控制台 http://localhost:8001（推荐入口，等价双击 .command）
#   ./start.sh dev        # 开发模式：前端 :5173 + 后端 :8002（热更新）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-prod}"
CONTROL_PORT=8001
BACKEND_PORT=8002
FRONTEND_PORT=5173

CONDA_BASE="$(conda info --base 2>/dev/null || echo /opt/anaconda3)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate langchain
PYTHONPATH="$SCRIPT_DIR/src"
export PYTHONPATH

log() { echo -e "$1"; }

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
      exit 1
    fi
  fi
}

open_browser() {
  local url="$1"
  if command -v open >/dev/null 2>&1; then open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1 || true; fi
}

wait_ready() {
  local url="$1" timeout="${2:-60}"
  for _ in $(seq 1 "$timeout"); do
    if curl -sf "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

if [ "$MODE" = "dev" ]; then
  log "▶ 开发模式：前端 :$FRONTEND_PORT + 后端 :$BACKEND_PORT"
  kill_stale "$BACKEND_PORT" "后端" "graphrag.api.main"
  kill_stale "$FRONTEND_PORT" "前端" "web"
  PYTHONPATH="$PYTHONPATH" uvicorn src.graphrag.api.main:app --reload --port "$BACKEND_PORT" &
  BACKEND_PID=$!
  (cd web && npm run dev) &
  VITE_PID=$!
  wait_ready "http://localhost:$BACKEND_PORT/api/health" || log "  ⚠️  后端就绪等待超时，请查看日志"
  wait_ready "http://localhost:$FRONTEND_PORT/" || log "  ⚠️  前端就绪等待超时，请查看日志"
  log "✅ 前端已启动:  http://localhost:$FRONTEND_PORT"
  log "   （API 代理到后端 :$BACKEND_PORT）"
  open_browser "http://localhost:$FRONTEND_PORT"
  log "\n按 Ctrl+C 停止全部服务"
  wait
else
  log "▶ 一键启动问答系统:  http://localhost:$BACKEND_PORT"
  kill_stale "$BACKEND_PORT" "后端" "graphrag.api.main"
  # 确保引导服务在运行
  if ! lsof -ti :"$CONTROL_PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
    PYTHONPATH="$PYTHONPATH" uvicorn src.graphrag.supervisor.app:app --host 127.0.0.1 --port "$CONTROL_PORT" &
    CONTROL_PID=$!
    wait_ready "http://localhost:$CONTROL_PORT/api/status" || { log "❌ 引导服务启动失败，请查看日志"; exit 1; }
  fi
  # 确保后端运行
  if ! curl -sf "http://localhost:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    log "   正在启动问答系统，请稍候…"
    curl -sf -X POST "http://localhost:$CONTROL_PORT/api/start" -H "Content-Type: application/json" -d '{}' >/dev/null 2>&1 || true
    wait_ready "http://localhost:$BACKEND_PORT/api/health" 90 || { log "❌ 系统启动失败，请查看 data/logs/backend.log"; exit 1; }
  fi
  log "✅ 系统已启动:  http://localhost:$BACKEND_PORT"
  open_browser "http://localhost:$BACKEND_PORT"
  log "\n按 Ctrl+C 停止引导服务（问答系统会继续运行）"
  wait
fi
