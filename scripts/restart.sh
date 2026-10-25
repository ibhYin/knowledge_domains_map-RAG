#!/usr/bin/env bash
# GraphRAG 后端重启脚本
#   ./scripts/restart.sh                # 构建中会询问
#   ./scripts/restart.sh --force        # 跳过询问
#   ./scripts/restart.sh --supervisor   # 连同控制服务一起重启（改了 supervisor 代码时用）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

CONTROL_PORT=8001
BACKEND_PORT=8002

FORCE=0
RESTART_SUPERVISOR=0
for arg in "$@"; do
  case "$arg" in
    -f|--force) FORCE=1 ;;
    -s|--supervisor) RESTART_SUPERVISOR=1 ;;
    -h|--help)
      sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "未知参数: $arg"
      exit 2
      ;;
  esac
done

log() { echo -e "$1"; }

CONDA_BASE="$(conda info --base 2>/dev/null || echo /opt/anaconda3)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate langchain
export PYTHONPATH="$SCRIPT_DIR/src"

json_get() {
  python3 -c 'import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
print(data.get(sys.argv[1], "") if isinstance(data, dict) else "")' "$1" 2>/dev/null
}

start_supervisor() {
  if curl -sf "http://127.0.0.1:$CONTROL_PORT/api/status" >/dev/null 2>&1; then
    return 0
  fi
  if lsof -ti :"$CONTROL_PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
    log "❌ 端口 $CONTROL_PORT 被其他进程占用"
    return 1
  fi
  log "▶ 启动控制服务 :$CONTROL_PORT"
  mkdir -p data/logs
  nohup python -m uvicorn src.graphrag.supervisor.app:app --host 127.0.0.1 --port "$CONTROL_PORT" \
    >> data/logs/supervisor.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:$CONTROL_PORT/api/status" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  log "❌ 控制服务启动失败，请查看 data/logs/supervisor.log"
  return 1
}

start_supervisor || exit 1

# 构建进行中默认不重启，避免中断长任务。
current="$(curl -sf --max-time 3 "http://127.0.0.1:$BACKEND_PORT/api/graph/build/current" 2>/dev/null || true)"
build_status="$(printf '%s' "$current" | json_get status)"
if [ "$build_status" = "running" ]; then
  processed="$(printf '%s' "$current" | json_get processed)"
  total="$(printf '%s' "$current" | json_get total)"
  if [ "$FORCE" -eq 0 ]; then
    if [ -t 0 ]; then
      printf "⚠️  构建进行中（%s/%s）。重启会中断当前任务；已发布进度会保留，重新构建可断点续跑。继续？[y/N] " "${processed:-?}" "${total:-?}"
      read -r answer
      case "$answer" in
        y|Y|yes|YES) ;;
        *) log "已取消"; exit 1 ;;
      esac
    else
      log "❌ 构建进行中（${processed:-?}/${total:-?}）；非交互环境需加 --force"
      exit 1
    fi
  fi
fi

if [ "$RESTART_SUPERVISOR" -eq 1 ]; then
  log "▶ 重启控制服务 :$CONTROL_PORT"
  curl -sf -X POST "http://127.0.0.1:$CONTROL_PORT/api/quit" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    lsof -ti :"$CONTROL_PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1 || break
    sleep 0.5
  done
  start_supervisor || exit 1
fi

log "▶ 重启后端 :$BACKEND_PORT"
result="$(curl -s --max-time 120 -X POST "http://127.0.0.1:$CONTROL_PORT/api/restart")"
if [ -z "$result" ]; then
  log "❌ 控制服务无响应"
  tail -20 data/logs/backend.log 2>/dev/null
  exit 1
fi
echo "$result"
ok="$(printf '%s' "$result" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("ok"))' 2>/dev/null)"
if [ "$ok" != "True" ]; then
  log "❌ 重启失败"
  tail -20 data/logs/backend.log 2>/dev/null
  exit 1
fi

health="$(curl -sf --max-time 5 "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null || true)"
pid="$(printf '%s' "$health" | json_get pid)"
started="$(printf '%s' "$health" | json_get started_at)"
if [ -z "$pid" ]; then
  log "❌ 后端重启后健康检查失败"
  tail -20 data/logs/backend.log 2>/dev/null
  exit 1
fi
log "✅ 后端已重启：PID $pid，启动于 ${started:-未知}"
