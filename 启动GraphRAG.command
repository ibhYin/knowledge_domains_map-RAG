#!/bin/bash
# 双击运行：一键启动 GraphRAG 问答系统并打开浏览器
# 直接进入系统 http://localhost:8002，无独立控制台页面
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

CONDA_BASE="$(conda info --base 2>/dev/null || echo /opt/anaconda3)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate langchain
export PYTHONPATH="$PROJECT_DIR/src"
mkdir -p "$PROJECT_DIR/data/logs"

# 清理 8002 上不健康的后端进程（避免端口被僵尸进程占用导致启动失败）
pid="$(lsof -ti :8002 -sTCP:LISTEN -P -n 2>/dev/null || true)"
if [ -n "$pid" ]; then
  if ! curl -sf http://localhost:8002/api/health >/dev/null 2>&1; then
    echo "清理异常的 RAG 系统进程 (PID $pid)"
    kill "$pid" 2>/dev/null
    sleep 1
  fi
fi

# 1) 确保引导服务（8001）在运行
if ! lsof -ti :8001 -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  nohup python -m uvicorn src.graphrag.supervisor.app:app --host 127.0.0.1 --port 8001 \
    > "$PROJECT_DIR/data/logs/supervisor.log" 2>&1 &
  sleep 3
fi

# 2) 确保问答系统（8002）在运行
if ! curl -sf http://localhost:8002/api/health >/dev/null 2>&1; then
  echo "正在启动问答系统，请稍候…"
  curl -sf -X POST http://localhost:8001/api/start -H "Content-Type: application/json" -d '{}' >/dev/null 2>&1
  for _ in $(seq 1 90); do
    curl -sf http://localhost:8002/api/health >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 3) 打开系统页面
if curl -sf http://localhost:8002/api/health >/dev/null 2>&1; then
  open http://localhost:8002
  echo "已打开问答系统 http://localhost:8002（本窗口可关闭）"
else
  echo "系统启动失败。请检查 data/logs/supervisor.log 与 data/logs/backend.log，或先运行 ./start.sh dev 排查。"
fi
sleep 3
