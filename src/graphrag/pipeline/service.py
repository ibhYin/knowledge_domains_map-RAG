import hashlib
import json
import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from graphrag.config import fresh_llm_config, settings
from graphrag.graph.store import GraphStore
from graphrag.llm.client import build_llm
from graphrag.llm.extractor import EXTRACTION_SYSTEM_PROMPT, EntityExtractor
from graphrag.schemas.extraction import ChunkExtraction
from graphrag.loaders.document_loader import SUPPORTED_EXTS, load_document
from graphrag.pipeline.chunk_store import ChunkStore, chunk_id_of, content_hash
from graphrag.retrieval.context_formatter import format_subgraph_context
from graphrag.retrieval.graph_search import GraphSearch
from graphrag.splitting.text_splitter import split_documents

logger = logging.getLogger(__name__)

ANSWER_SYSTEM_PROMPT = (
    "你是基于知识图谱的中文问答助手。请依据【图谱上下文】中的实体与关系回答用户问题，"
    "用中文、结构清晰。只依据给定上下文，不要使用图谱之外的知识；"
    "若上下文不足以回答，直接说明缺少哪些信息，不要编造。"
)


class RagService:
    def __init__(self):
        self.chunks = ChunkStore()
        self.store = GraphStore()
        self.search = GraphSearch(self.store)
        self._lock = threading.Lock()

    def load(self) -> None:
        self.store.load()
        self._finish_deletions()

    def list_documents(self) -> list[dict]:
        deleted = set(self.store.meta.get("deleted_documents", []))
        return [d for d in self.chunks.list_documents() if d["doc_id"] not in deleted]

    def _finish_deletions(self) -> None:
        for doc_id in self.store.meta.get("deleted_documents", []):
            try:
                self.chunks.delete_document(doc_id)
            except OSError:
                logger.warning("文档已逻辑删除，物理清理将在重启时重试: %s", doc_id)

    def delete_document(self, doc_id: str) -> bool:
        if doc_id not in {d["doc_id"] for d in self.list_documents()}:
            return False
        deleted = set(self.store.meta.get("deleted_documents", [])) | {doc_id}
        snapshot = GraphStore()
        snapshot.meta["processed_chunks"] = {}
        snapshot.meta["graph_version"] = self.store.meta.get("graph_version", 0)
        fingerprint = self.store.meta.get("extraction_fingerprint", "")
        snapshot.meta["extraction_fingerprint"] = fingerprint
        extractions = {}
        # ponytail: 删除时 O(全部剩余分块) 本地重放；规模触顶后再做增量撤销。
        for record in self.chunks.iter_chunks():
            source = record["metadata"]["doc_id"]
            if source in deleted:
                continue
            cid = chunk_id_of(source, record["chunk_index"])
            digest = content_hash(record["content"])
            ext = self.chunks.load_extraction(cid, digest, fingerprint)
            if ext is None:
                if cid in self.store.meta.get("processed_chunks", {}):
                    raise ValueError("剩余文档缺少有效抽取缓存，无法安全删除，请先重新构建。")
                continue
            extractions[cid] = ext
            snapshot.meta["processed_chunks"][cid] = digest
        snapshot.rebuild(extractions)
        snapshot.meta["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        # 删除记录与新图同一文件提交；清理中断后仍屏蔽旧分块，并在启动时重试。
        snapshot.meta["deleted_documents"] = sorted(deleted)
        snapshot.save()
        with self._lock:
            self.store.G, self.store.resolver, self.store.meta = snapshot.G, snapshot.resolver, snapshot.meta
            self.store._extractions = snapshot._extractions
        self._finish_deletions()
        return True

    # ---------- ingest ----------

    def ingest(self, files: list[tuple[str, bytes]]) -> list[dict]:
        results = []
        settings.documents_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in files:
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_EXTS:
                raise ValueError(f"不支持的文档格式: {ext}（支持 {sorted(SUPPORTED_EXTS)}）")
            digest = hashlib.sha256(f"{filename}:{time.time()}".encode()).hexdigest()[:12]
            doc_id = f"{digest}"
            path = settings.documents_dir / f"{doc_id}{ext}"
            path.write_bytes(content)
            docs = load_document(path, doc_id)
            chunks = split_documents(docs, doc_id)
            self.chunks.save_chunks(doc_id, chunks)
            self.chunks.register(doc_id, filename, len(content), len(chunks))
            results.append({"doc_id": doc_id, "filename": filename, "chunk_count": len(chunks)})
        return results

    # ---------- build ----------

    def build_graph(
        self,
        doc_ids: list[str] | None = None,
        progress=None,
    ) -> dict:
        records = self.chunks.iter_chunks(doc_ids)
        deleted = set(self.store.meta.get("deleted_documents", []))
        records = [r for r in records if r["metadata"]["doc_id"] not in deleted]
        config = fresh_llm_config()
        fingerprint = content_hash(json.dumps({
            "config": {k: v for k, v in config.items() if k not in {"openai_api_key", "temperature_answer"}},
            "prompt": EXTRACTION_SYSTEM_PROMPT, "schema": ChunkExtraction.model_json_schema(),
        }, sort_keys=True, ensure_ascii=False))
        processed = self.store.meta.get("processed_chunks", {})
        reset = bool(processed) and (
            self.store.meta.get("extraction_fingerprint") != fingerprint
            or any(processed.get(chunk_id_of(r["metadata"]["doc_id"], r["chunk_index"]))
                   not in (None, content_hash(r["content"])) for r in records)
            or any(processed.get(chunk_id_of(r["metadata"]["doc_id"], r["chunk_index"])) is not None
                   and self.chunks.load_extraction(chunk_id_of(r["metadata"]["doc_id"], r["chunk_index"]),
                                                   content_hash(r["content"]), fingerprint) is None
                   for r in records)
        )
        if reset:
            records = [r for r in self.chunks.iter_chunks() if r["metadata"]["doc_id"] not in deleted]
            processed = {}
        todo = []
        for record in records:
            doc_id = record.get("metadata", {}).get("doc_id", "")
            cid = chunk_id_of(doc_id, record["chunk_index"])
            h = content_hash(record["content"])
            if processed.get(cid) == h and self.chunks.load_extraction(cid, h, fingerprint) is not None:
                continue
            todo.append((cid, record["content"], h))

        total = len(todo)
        if progress:
            progress({"status": "running", "processed": 0, "total": total, "failed": 0,
                      "graph_version": self.store.meta.get("graph_version", 0), "error": None})

        # ponytail: 小语料按批次复制整图保存检查点；大图时改用事务存储。
        working_store = deepcopy(self.store) if todo else None
        extractions = dict(self.store._extractions)
        if working_store is not None:
            if reset:
                extractions = {}
                version = working_store.meta.get("graph_version", 0)
                working_store.clear()
                working_store.meta["processed_chunks"] = {}
                working_store.meta["graph_version"] = version
                working_store.meta["deleted_documents"] = sorted(deleted)
            working_store.meta["extraction_fingerprint"] = fingerprint
        saved_success_count = 0
        checkpoint_processed = 0

        def extract_task(item):
            cid, text, h = item
            ext = self.chunks.load_extraction(cid, h, fingerprint)
            if ext is None:
                ext = EntityExtractor(config=config).extract(text)
                if ext is not None:
                    self.chunks.save_extraction(cid, h, fingerprint, ext)
            return cid, h, ext

        with ThreadPoolExecutor(max_workers=settings.extraction_concurrency) as pool:
            pending = {pool.submit(extract_task, item) for item in todo}
            done = 0
            failed = 0
            last_published = time.monotonic()
            while pending:
                finished, pending = wait(pending, timeout=min(1.0, settings.build_publish_interval),
                                         return_when=FIRST_COMPLETED)
                for future in finished:
                    cid, h, ext = future.result()
                    if ext is not None:
                        extractions[cid] = ext
                        working_store.meta.setdefault("processed_chunks", {})[cid] = h
                    else:
                        failed += 1
                    done += 1
                published = False
                if done - failed > saved_success_count and (
                    saved_success_count == 0
                    or done - failed - saved_success_count >= settings.build_checkpoint_interval
                    or time.monotonic() - last_published >= settings.build_publish_interval
                    or not pending
                ):
                    # ponytail: 每次发布 O(已完成分块) 重放以消除别名顺序影响；大图再做增量索引。
                    snapshot = deepcopy(working_store)
                    snapshot.rebuild(extractions)
                    snapshot.meta["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    snapshot.save()
                    with self._lock:
                        self.store.G = snapshot.G
                        self.store.resolver = snapshot.resolver
                        self.store.meta = snapshot.meta
                        self.store._extractions = snapshot._extractions
                    working_store.meta["graph_version"] = snapshot.meta["graph_version"]
                    working_store.G = snapshot.G
                    saved_success_count = done - failed
                    checkpoint_processed = done
                    last_published = time.monotonic()
                    published = True
                if progress and (finished or published):
                    progress({
                        "status": "running", "processed": done, "total": total,
                        "failed": failed, "error": None,
                        "nodes": working_store.G.number_of_nodes(),
                        "edges": working_store.G.number_of_edges(),
                        "checkpoint_processed": checkpoint_processed,
                        "graph_version": self.store.meta.get("graph_version", 0),
                    })

        error = None
        if total and failed == total:
            status = "error"
            error = "全部分块抽取失败，请检查模型配置或后端日志后重试。当前图谱未更新。"
            message = error
        elif failed:
            status = "partial"
            message = "已保存成功抽取的结果；再次点击构建可重试失败分块。"
        else:
            status = "done"
            if not records:
                message = "没有可构建的分块，请先上传有效文档。"
            elif not total:
                message = "所有分块均已处理，无需重复构建。"
            else:
                message = "构建结果已保存。"

        result = {
            "status": status,
            "processed": done,
            "total": total,
            "failed": failed,
            "error": error,
            "message": message,
            "checkpoint_processed": checkpoint_processed,
            **self.store.stats(),
        }
        if progress:
            progress(result)
        return result

    # ---------- query ----------

    def answer(
        self,
        question: str,
        hops: int = 2,
        max_nodes: int = 40,
        max_edges: int = 80,
        seed_override: list[str] | None = None,
    ) -> dict:
        result = self.search.search(
            question, hops=hops, max_nodes=max_nodes, max_edges=max_edges, seed_override=seed_override
        )
        subgraph = result["subgraph"]
        edges = result["edges"]

        if subgraph.number_of_nodes() == 0:
            context = ""
            answer_text = "图谱中没有检索到与问题相关的实体，无法回答。请尝试换个问法，或先上传文档并构建图谱。"
        else:
            context = format_subgraph_context(self.store, subgraph, edges, question)
            prompt = ChatPromptTemplate.from_messages(
                [("system", ANSWER_SYSTEM_PROMPT), ("human", "{context}")]
            )
            llm = build_llm(temperature=settings.temperature_answer)
            answer_text = llm.invoke(prompt.format_messages(context=context)).content

        used_docs = sorted(
            {
                d.split(":", 1)[0]
                for _, _, _, edata in edges
                for d in edata.get("source_chunks", [])
            }
        )
        return {
            "answer": answer_text,
            "matched_entities": result["matched_entities"],
            "context": context,
            "subgraph": self.store.subgraph_viz(subgraph, edges),
            "node_count": subgraph.number_of_nodes(),
            "edge_count": len(edges),
            "used_docs": used_docs,
        }


service = RagService()
