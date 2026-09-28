#!/bin/bash
# 双击运行：启动 GraphRAG 控制台并打开浏览器
# 控制台 http://localhost:8001，系统 http://localhost:8002
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

CONDA_BASE="$(conda info --base 2>/dev/null || echo /opt/anaconda3)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate langchain
export PYTHONPATH="$PROJECT_DIR/src"
mkdir -p "$PROJECT_DIR/data/logs"

# 仅当 8002 上的后端不健康时才清理（健康运行则保留）
pid="$(lsof -ti :8002 -sTCP:LISTEN -P -n 2>/dev/null || true)"
if [ -n "$pid" ]; then
  if curl -sf http://localhost:8002/api/health >/dev/null 2>&1; then
    echo "问答系统正在运行，保持现状"
  elif ps -p "$pid" -o command= 2>/dev/null | grep -q "graphrag.api.main"; then
    echo "清理异常的 RAG 系统进程 (PID $pid)"
    kill "$pid" 2>/dev/null
    sleep 1
  fi
fi

# 若控制台已在运行，直接打开浏览器
if lsof -ti :8001 -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  open http://localhost:8001
  echo "控制台已在运行，已打开页面，本窗口可关闭"
  sleep 2
  exit 0
fi

# 后台启动控制台，不占用本终端窗口
nohup python -m uvicorn src.graphrag.supervisor.app:app --host 127.0.0.1 --port 8001 \
  > "$PROJECT_DIR/data/logs/supervisor.log" 2>&1 &
sleep 3
open http://localhost:8001
echo "控制台已启动：http://localhost:8001 （本窗口可关闭）"
sleep 2
