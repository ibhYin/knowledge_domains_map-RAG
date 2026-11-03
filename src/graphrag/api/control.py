"""supervisor（:8001 引导服务）代理端点。

业务页面不直接访问 8001；这里的端点供「模型设置」页查询运行状态与
启停后端。supervisor 未运行时统一 503 并给出恢复指引。
"""

import httpx
from fastapi import APIRouter, HTTPException

_SUPERVISOR_URL = "http://127.0.0.1:8001"

# 挂载于 routes 的主 router（已带 /api 前缀），此处不再重复声明前缀
router = APIRouter()


def proxy_supervisor(path: str, method: str = "GET", body: dict | None = None):
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.request(method, f"{_SUPERVISOR_URL}{path}", json=body)
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"控制服务未运行（{exc}）。系统停止后，请双击「启动GraphRAG.command」或打开 http://localhost:8001 重新启动。",
        ) from exc


@router.get("/control/status")
def control_status():
    return proxy_supervisor("/api/status")


@router.get("/control/logs")
def control_logs(n: int = 80):
    return proxy_supervisor(f"/api/logs?n={n}")


@router.post("/control/start")
def control_start():
    return proxy_supervisor("/api/start", "POST", {})


@router.post("/control/stop")
def control_stop():
    return proxy_supervisor("/api/stop", "POST", {})


@router.post("/control/restart")
def control_restart():
    return proxy_supervisor("/api/restart", "POST", {})
