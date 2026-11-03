import os
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from graphrag.api.history import HistoryStore
from graphrag.api.jobs import JobConflict, JobManager
from graphrag.config import fresh_llm_config, settings, write_env
from graphrag.llm.extractor import QueryExtractionError
from graphrag.pipeline.service import service
from graphrag.schemas.api import BuildRequest, QueryRequest

router = APIRouter(prefix="/api")

job_manager = JobManager()
history_store = HistoryStore()

# 进程启动时记录，用于在页面上确认后端加载的是哪一版代码。
_STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
_SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _latest_code_mtime() -> str:
    latest = 0.0
    for path in _SOURCE_ROOT.rglob("*.py"):
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest)) if latest else ""


_CODE_MTIME = _latest_code_mtime()


@router.get("/health")
def health():
    stats = service.store.stats()
    return {
        "status": "ok",
        "model": service.store.meta.get("model") or "openai-compatible",
        "graph_loaded": service.store.G.number_of_nodes() > 0,
        "nodes": stats["nodes"],
        "edges": stats["edges"],
        "pid": os.getpid(),
        "started_at": _STARTED_AT,
        "code_mtime": _CODE_MTIME,
    }


@router.post("/documents/ingest")
async def ingest_documents(files: list[UploadFile]):
    results = []
    for f in files:
        content = await f.read()
        results.append((f.filename or "unnamed", content))

    def _do_ingest():
        with _jobs_lock:
            return {"ingested": service.ingest(results)}

    try:
        # PDF/DOCX 解析与落盘是同步重活，移入线程池执行，上传期间事件循环不再冻结。
        return await run_in_threadpool(_do_ingest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/documents")
def list_documents():
    return {"documents": service.list_documents()}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str):
    # 全量重放耗时长，只在一瞬间注册 deleting 占位（与构建/清空互斥），
    # 重放本身在任务锁外执行，构建状态轮询不再被阻塞。
    try:
        placeholder = job_manager.register_deleting()
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        try:
            if not service.delete_document(doc_id):
                raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        job_manager.release(placeholder)
    return {"deleted": doc_id, "graph_updated": True}


@router.post("/graph/build")
def build_graph(body: BuildRequest):
    try:
        job_id = job_manager.start_build(
            lambda progress: service.build_graph(doc_ids=body.doc_ids, progress=progress))
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id}


@router.get("/graph/build/status/{job_id}")
def build_status(job_id: str):
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    return job


@router.get("/graph/build/current")
def current_build():
    return job_manager.current() or {"job_id": None}


@router.get("/graph/stats")
def graph_stats():
    with service._lock:
        return service.store.stats()


@router.get("/graph/viz")
def graph_viz(limit: int = Query(300, ge=1, le=1000)):
    with service._lock:
        return service.store.to_viz_data(limit=limit)


@router.get("/graph/export")
def graph_export(fmt: str = "graphml"):
    if fmt == "graphml":
        return PlainTextResponse(
            service.store.export_graphml(),
            media_type="application/xml",
            headers={"Content-Disposition": 'attachment; filename="graph.graphml"'},
        )
    if fmt == "json":
        from graphrag.config import settings

        return PlainTextResponse(
            settings.graph_file.read_text(encoding="utf-8"),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="graph.json"'},
        )
    raise HTTPException(status_code=400, detail=f"不支持的导出格式: {fmt}")


@router.post("/graph/clear")
def clear_graph():
    if job_manager.has_active():
        raise HTTPException(status_code=409, detail="有任务进行中，请等待结束后再清空图谱。")
    with service._lock:
        deleted = service.store.meta.get("deleted_documents", [])
        service.store.clear()
        service.store.meta["deleted_documents"] = deleted
        service.store.save()
    return {"cleared": True}


@router.get("/overview")
def overview():
    docs = service.list_documents()
    stats = service.store.stats()
    return {
        "documents": len(docs),
        "chunks": sum(d.get("chunk_count", 0) for d in docs),
        **stats,
    }


@router.get("/entities/search")
def entity_search(q: str = "", limit: int = 20):
    return {"results": service.store.search_entities(q, limit=min(limit, 50))}


@router.get("/entities/{key}")
def entity_detail(key: str):
    detail = service.store.entity_detail(key)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"实体不存在: {key}")
    return detail


@router.get("/path")
def path_between(from_: str = Query(..., alias="from"), to: str = Query(..., alias="to")):
    result = service.store.find_path(from_, to)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到两个实体之间的路径")
    return result


@router.get("/settings")
def get_settings():
    cfg = fresh_llm_config()
    return {
        "openai_base_url": cfg["openai_base_url"],
        "openai_model": cfg["openai_model"],
        "api_key_set": bool(cfg["openai_api_key"]),
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "extraction_concurrency": settings.extraction_concurrency,
        "structured_output_method": cfg["structured_output_method"],
    }


@router.post("/settings")
def save_settings(body: dict):
    updates = {}
    if body.get("openai_base_url") and str(body["openai_base_url"]).strip():
        updates["OPENAI_BASE_URL"] = str(body["openai_base_url"]).strip()
    if body.get("openai_model") and str(body["openai_model"]).strip():
        updates["OPENAI_MODEL"] = str(body["openai_model"]).strip()
    if body.get("openai_api_key") and str(body["openai_api_key"]).strip():
        updates["OPENAI_API_KEY"] = str(body["openai_api_key"]).strip()
    if not updates:
        return {"ok": True, "message": "没有需要保存的更改"}
    write_env(updates)
    return {"ok": True, "message": "配置已保存，新的 LLM 配置会在下次调用时生效"}


@router.get("/history")
def history(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    # 列表只回摘要（不含 context/subgraph/sentences/sources 等大字段），详情按需取。
    return history_store.page(offset, limit)


@router.get("/history/{index}")
def history_detail(index: int):
    active = {d["doc_id"] for d in service.list_documents()}
    item = history_store.detail(index, active)
    if item is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return item


@router.delete("/history")
def clear_history():
    history_store.clear()
    return {"cleared": True}


_SUPERVISOR_URL = "http://127.0.0.1:8001"


def _proxy_supervisor(path: str, method: str = "GET", body: Optional[dict] = None):
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
    return _proxy_supervisor("/api/status")


@router.get("/control/logs")
def control_logs(n: int = 80):
    return _proxy_supervisor(f"/api/logs?n={n}")


@router.post("/control/start")
def control_start():
    return _proxy_supervisor("/api/start", "POST", {})


@router.post("/control/stop")
def control_stop():
    return _proxy_supervisor("/api/stop", "POST", {})


@router.post("/control/restart")
def control_restart():
    return _proxy_supervisor("/api/restart", "POST", {})


@router.post("/query")
def query(body: QueryRequest):
    try:
        result = service.answer(
            question=body.question,
            hops=body.hops,
            max_nodes=body.max_nodes,
            max_edges=body.max_edges,
            seed_override=body.seed_override,
        )
    except QueryExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history_store.append({
        "question": body.question,
        "answer": result["answer"],
        "matched": [m["name"] for m in result["matched_entities"]],
        "node_count": result["node_count"],
        "edge_count": result["edge_count"],
        "context": result["context"],
        "subgraph": result["subgraph"],
        **{k: result.get(k) for k in ("sentences", "sources", "retrieved_sources", "verification", "used_docs", "graph_version")},
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return result
