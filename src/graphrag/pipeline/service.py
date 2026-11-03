import hashlib
import json
import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import copy, deepcopy
from pathlib import Path

from graphrag.config import fresh_llm_config, settings
from graphrag.graph.store import GraphStore
from graphrag.llm.client import build_llm
from graphrag.llm.extractor import EXTRACTION_SYSTEM_PROMPT, EntityExtractor
from graphrag.schemas.extraction import ChunkExtraction
from graphrag.loaders.document_loader import SUPPORTED_EXTS, load_document
from graphrag.pipeline.chunk_store import ChunkStore, chunk_id_of, content_hash
from graphrag.retrieval.context_formatter import format_subgraph_context
from graphrag.retrieval.evidence import answer_with_evidence, collect_sources
from graphrag.retrieval.graph_search import GraphSearch
from graphrag.splitting.text_splitter import split_documents

logger = logging.getLogger(__name__)

class RagService:
    def __init__(self):
        self.chunks = ChunkStore()
        self.store = GraphStore()
        self.search = GraphSearch(self.store)
        self._lock = threading.Lock()
        self._answer_llm_cache: tuple[str, object] | None = None  # (配置指纹, ChatOpenAI)

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

    def _publish_snapshot(self, extractions: dict, meta: dict) -> None:
        """发布线程体：全量重放抽取、落盘、原子换图。

        由单线程执行器串行调用；版本号在执行时取当前已提交图谱的版本，
        保证随发布单调递增（payload 捕获时的版本可能落后于上一拍发布）。
        """
        with self._lock:
            meta["graph_version"] = self.store.meta.get("graph_version", 0)
        snapshot = GraphStore()
        snapshot.meta = meta
        snapshot.rebuild(extractions)
        snapshot.meta["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        snapshot.save()
        with self._lock:
            self.store.G = snapshot.G
            self.store.resolver = snapshot.resolver
            self.store.meta = snapshot.meta
            self.store._extractions = snapshot._extractions

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
        # 指纹一致时 _extractions 即经校验的有效抽取（启动加载/发布换图时同步维护），
        # 单次遍历完成 reset 判定与 todo 收集，不再重复读盘、重复计算内容哈希。
        cached = self.store._extractions if self.store.meta.get("extraction_fingerprint") == fingerprint else {}
        reset = bool(processed) and self.store.meta.get("extraction_fingerprint") != fingerprint
        todo = []
        if not reset:
            for record in records:
                doc_id = record.get("metadata", {}).get("doc_id", "")
                cid = chunk_id_of(doc_id, record["chunk_index"])
                h = content_hash(record["content"])
                state = processed.get(cid)
                if state is not None and state != h:
                    reset = True  # 分块内容与成功记录不符，旧抽取全部失效
                    break
                if state == h:
                    if cid not in cached:
                        reset = True  # 已处理分块缺少有效抽取缓存，全量重建更安全
                        break
                    continue  # 已处理且缓存有效，跳过
                todo.append((cid, record["content"], h, cached.get(cid)))
        if reset:
            records = [r for r in self.chunks.iter_chunks() if r["metadata"]["doc_id"] not in deleted]
            todo = [(chunk_id_of(r.get("metadata", {}).get("doc_id", ""), r["chunk_index"]),
                     r["content"], content_hash(r["content"]), None) for r in records]

        total = len(todo)
        if progress:
            progress({"status": "running", "processed": 0, "total": total, "failed": 0,
                      "graph_version": self.store.meta.get("graph_version", 0), "error": None})

        # 工作副本只携带 meta（processed_chunks 等），图由发布线程全量重放生成，
        # 不再 deepcopy 整图；发布成本集中在重建与序列化，见 _publish_snapshot。
        working_store = GraphStore() if todo else None
        extractions = dict(self.store._extractions)
        if working_store is not None:
            if reset:
                extractions = {}
                working_store.meta["graph_version"] = self.store.meta.get("graph_version", 0)
                working_store.meta["deleted_documents"] = sorted(deleted)
            else:
                working_store.meta = deepcopy(self.store.meta)
            working_store.meta["extraction_fingerprint"] = fingerprint
        saved_success_count = 0
        checkpoint_processed = 0
        done = 0
        failed = 0
        # 大语料自适应：按总量把发布会次数限制在约 50 次以内，小语料维持原间隔。
        checkpoint_interval = max(settings.build_checkpoint_interval, (total + 49) // 50)

        # 所有 worker 共享同一 extractor：复用 ChatOpenAI/httpx 连接池，避免每分块重复握手。
        extractor = EntityExtractor(config=config)
        try:
            extractor._get_chain()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"模型配置不可用，请检查「模型设置」: {type(exc).__name__}") from exc

        def extract_task(item):
            cid, text, h, cached_ext = item
            ext = cached_ext if cached_ext is not None else self.chunks.load_extraction(cid, h, fingerprint)
            if ext is None:
                ext = extractor.extract(text)
                if ext is not None:
                    self.chunks.save_extraction(cid, h, fingerprint, ext)
            return cid, h, ext

        publisher = ThreadPoolExecutor(max_workers=1, thread_name_prefix="graph-publish")
        publish_future = None
        try:
            with ThreadPoolExecutor(max_workers=settings.extraction_concurrency) as pool:
                pending = {pool.submit(extract_task, item) for item in todo}
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
                        or done - failed - saved_success_count >= checkpoint_interval
                        or time.monotonic() - last_published >= settings.build_publish_interval
                        or not pending
                    ) and (publish_future is None or publish_future.done()):
                        # 发布在后台单线程串行执行（全量重放+落盘+换图），收割循环不再被阻塞；
                        # 上一次未完成时跳过，条件持续满足会在下一轮补发最新状态。
                        publish_future = publisher.submit(
                            self._publish_snapshot, dict(extractions), deepcopy(working_store.meta))
                        saved_success_count = done - failed
                        checkpoint_processed = done
                        last_published = time.monotonic()
                        published = True
                    if publish_future is not None and publish_future.done():
                        exc = publish_future.exception()
                        if exc is not None:
                            raise exc
                    if progress and (finished or published):
                        with self._lock:
                            nodes = self.store.G.number_of_nodes()
                            edges = self.store.G.number_of_edges()
                            version = self.store.meta.get("graph_version", 0)
                        progress({
                            "status": "running", "processed": done, "total": total,
                            "failed": failed, "error": None,
                            "nodes": nodes,
                            "edges": edges,
                            "checkpoint_processed": checkpoint_processed,
                            "graph_version": version,
                        })
            # 收尾发布：最后一批若因上次发布进行中被跳过，在此补发。
            if todo and done - failed > saved_success_count:
                publish_future = publisher.submit(
                    self._publish_snapshot, dict(extractions), deepcopy(working_store.meta))
            if publish_future is not None:
                publish_future.result()
        finally:
            publisher.shutdown(wait=True)

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

    def _get_answer_llm(self):
        """按配置指纹复用问答 LLM；「模型设置」保存后指纹变化即重建，下次调用生效。"""
        cfg = fresh_llm_config()
        fingerprint = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
        if self._answer_llm_cache is None or self._answer_llm_cache[0] != fingerprint:
            self._answer_llm_cache = (fingerprint, build_llm(temperature=cfg["temperature_answer"], config=cfg))
        return self._answer_llm_cache[1]

    def answer(
        self,
        question: str,
        hops: int = 2,
        max_nodes: int = 40,
        max_edges: int = 80,
        seed_override: list[str] | None = None,
    ) -> dict:
        with self._lock:
            store = copy(self.store)
        result = self.search.search(
            question, hops=hops, max_nodes=max_nodes, max_edges=max_edges, seed_override=seed_override, store=store
        )
        subgraph = result["subgraph"]
        edges = result["edges"]

        if subgraph.number_of_nodes() == 0:
            context = ""
            grounded = {"answer": "图谱中没有检索到与问题相关的实体，无法回答。请尝试换个问法，或先上传文档并构建图谱。",
                        "sentences": [], "sources": [], "retrieved_sources": [], "used_docs": [], "verification": "insufficient"}
        else:
            context = format_subgraph_context(store, subgraph, edges, question)
            with self._lock:
                documents = self.list_documents()
                records = self.chunks.iter_chunks([d["doc_id"] for d in documents])
            sources = collect_sources(documents, records, subgraph, edges)
            llm = self._get_answer_llm()
            grounded = answer_with_evidence(llm, question, context, sources)
        return {
            **grounded,
            "matched_entities": result["matched_entities"],
            "context": context,
            "subgraph": store.subgraph_viz(subgraph, edges),
            "node_count": subgraph.number_of_nodes(),
            "edge_count": len(edges),
            "graph_version": store.meta.get("graph_version", 0),
        }


service = RagService()
