import json
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from graphrag.config import fresh_llm_config, settings, write_env
from graphrag.pipeline.service import service
from graphrag.schemas.api import BuildRequest, QueryRequest

router = APIRouter(prefix="/api")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_HISTORY_FILE = settings.data_dir / "history.json"
_HISTORY_LIMIT = 100


def _load_history() -> list[dict]:
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_history(history: list[dict]) -> None:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(
        json.dumps(history[-_HISTORY_LIMIT:], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _start_build_job(doc_ids: Optional[list[str]]) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "processed": 0, "total": 0, "error": None}

    def _run():
        def progress(state: dict):
            with _jobs_lock:
                _jobs[job_id].update(state)

        try:
            service.build_graph(doc_ids=doc_ids, progress=progress)
        except Exception as exc:  # noqa: BLE001
            with _jobs_lock:
                _jobs[job_id].update({"status": "error", "error": str(exc)})

    threading.Thread(target=_run, daemon=True).start()
    return job_id


@router.get("/health")
def health():
    stats = service.store.stats()
    return {
        "status": "ok",
        "model": service.store.meta.get("model") or "openai-compatible",
        "graph_loaded": service.store.G.number_of_nodes() > 0,
        "nodes": stats["nodes"],
        "edges": stats["edges"],
    }


@router.post("/documents/ingest")
async def ingest_documents(files: list[UploadFile]):
    results = []
    for f in files:
        content = await f.read()
        results.append((f.filename or "unnamed", content))
    try:
        return {"ingested": service.ingest(results)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/documents")
def list_documents():
    return {"documents": service.chunks.list_documents()}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str):
    if not service.chunks.delete_document(doc_id):
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    return {"deleted": doc_id}


@router.post("/graph/build")
def build_graph(body: BuildRequest):
    job_id = _start_build_job(body.doc_ids)
    return {"job_id": job_id}


@router.get("/graph/build/status/{job_id}")
def build_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    return job


@router.get("/graph/stats")
def graph_stats():
    return service.store.stats()


@router.get("/graph/viz")
def graph_viz():
    return service.store.to_viz_data()


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
    service.store.clear()
    service.store.save()
    return {"cleared": True}


@router.get("/overview")
def overview():
    docs = service.chunks.list_documents()
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
def history():
    return {"history": list(reversed(_load_history()))}


@router.delete("/history")
def clear_history():
    if _HISTORY_FILE.exists():
        _HISTORY_FILE.write_text("[]", encoding="utf-8")
    return {"cleared": True}


@router.post("/query")
def query(body: QueryRequest):
    result = service.answer(
        question=body.question,
        hops=body.hops,
        max_nodes=body.max_nodes,
        max_edges=body.max_edges,
        seed_override=body.seed_override,
    )
    history_list = _load_history()
    history_list.append(
        {
            "question": body.question,
            "answer": result["answer"],
            "matched": [m["name"] for m in result["matched_entities"]],
            "node_count": result["node_count"],
            "edge_count": result["edge_count"],
            "context": result["context"],
            "subgraph": result["subgraph"],
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    _save_history(history_list)
    return result
