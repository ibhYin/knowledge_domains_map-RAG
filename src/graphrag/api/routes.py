import threading
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from graphrag.pipeline.service import service
from graphrag.schemas.api import BuildRequest, QueryRequest

router = APIRouter(prefix="/api")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


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


@router.post("/query")
def query(body: QueryRequest):
    return service.answer(
        question=body.question,
        hops=body.hops,
        max_nodes=body.max_nodes,
        max_edges=body.max_edges,
        seed_override=body.seed_override,
    )
