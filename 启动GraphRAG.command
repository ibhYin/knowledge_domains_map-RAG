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

# 1) 确保控制服务（8001）在运行
if ! curl -sf http://127.0.0.1:8001/api/status >/dev/null 2>&1; then
  nohup python -m uvicorn src.graphrag.supervisor.app:app --host 127.0.0.1 --port 8001 \
    >> "$PROJECT_DIR/data/logs/supervisor.log" 2>&1 &
  for _ in $(seq 1 20); do
    curl -sf http://127.0.0.1:8001/api/status >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

# 2) 确保问答系统（8002）在运行（已在运行则不打断，自动重载会处理代码变更）
if ! curl -sf http://127.0.0.1:8002/api/health >/dev/null 2>&1; then
  echo "正在启动问答系统，请稍候…"
  curl -sf -X POST http://127.0.0.1:8001/api/start -H "Content-Type: application/json" -d '{}' >/dev/null 2>&1
  for _ in $(seq 1 90); do
    curl -sf http://127.0.0.1:8002/api/health >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 3) 打开系统页面，并如实报告当前运行的是哪个进程/哪版代码
if curl -sf http://127.0.0.1:8002/api/health >/dev/null 2>&1; then
  python3 - <<'PY'
import json
import urllib.request


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


health = get("http://127.0.0.1:8002/api/health")
status = get("http://127.0.0.1:8001/api/status")
print(f"  后端 PID：{health.get('pid', '未知')}    启动于 {health.get('started_at', '未知')}")
print(f"  代码版本：{health.get('code_mtime', '未知')}")
if status.get("autoreload_enabled"):
    pending = "（有代码变更，等待构建结束后重载）" if status.get("pending_reload") else ""
    print(f"  自动重载：已开启{pending}")
else:
    print("  自动重载：已关闭")
if status.get("port_busy"):
    print(f"  ⚠️  当前后端（PID {status.get('port_pid')}）不由控制服务管理；首次代码变更时会自动接管，")
    print("     也可运行 ./start.sh restart 立即接管。")
PY
  open http://localhost:8002
  echo "已打开 http://localhost:8002 。后端源码变更会自动重载，本窗口可关闭。"
else
  echo "系统启动失败。请检查 data/logs/supervisor.log 与 data/logs/backend.log。"
  echo "可尝试：./start.sh restart --force"
fi
sleep 3
