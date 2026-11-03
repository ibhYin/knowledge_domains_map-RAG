import hashlib
import json
import logging
import threading
import time
from copy import copy
from pathlib import Path

from graphrag.config import fresh_llm_config, settings
from graphrag.graph.meta import MetaKeys
from graphrag.graph.store import GraphStore
from graphrag.llm.client import build_llm
from graphrag.loaders.document_loader import SUPPORTED_EXTS, load_document
from graphrag.pipeline.build import BuildSession, extraction_fingerprint
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
        self.store.load(extraction_loader=self.chunks.load_extraction)
        self._finish_deletions()

    def list_documents(self) -> list[dict]:
        deleted = set(self.store.meta.get(MetaKeys.DELETED_DOCUMENTS, []))
        return [d for d in self.chunks.list_documents() if d["doc_id"] not in deleted]

    def _finish_deletions(self) -> None:
        for doc_id in self.store.meta.get(MetaKeys.DELETED_DOCUMENTS, []):
            try:
                self.chunks.delete_document(doc_id)
            except OSError:
                logger.warning("文档已逻辑删除，物理清理将在重启时重试: %s", doc_id)

    def delete_document(self, doc_id: str) -> bool:
        if doc_id not in {d["doc_id"] for d in self.list_documents()}:
            return False
        deleted = set(self.store.meta.get(MetaKeys.DELETED_DOCUMENTS, [])) | {doc_id}
        fingerprint = self.store.meta.get(MetaKeys.EXTRACTION_FINGERPRINT, "")
        meta = {MetaKeys.EXTRACTION_FINGERPRINT: fingerprint, MetaKeys.DELETED_DOCUMENTS: sorted(deleted),
                MetaKeys.PROCESSED_CHUNKS: {}}
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
                if cid in self.store.meta.get(MetaKeys.PROCESSED_CHUNKS, {}):
                    raise ValueError("剩余文档缺少有效抽取缓存，无法安全删除，请先重新构建。")
                continue
            extractions[cid] = ext
            meta[MetaKeys.PROCESSED_CHUNKS][cid] = digest
        # 删除记录与新图同一快照提交（复用发布路径，版本号保持不变语义）；
        # 清理中断后仍屏蔽旧分块，并在启动时重试。
        self._publish_snapshot(extractions, meta)
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
            meta[MetaKeys.GRAPH_VERSION] = self.store.meta.get(MetaKeys.GRAPH_VERSION, 0)
        snapshot = GraphStore()
        snapshot.meta = meta
        snapshot.rebuild(extractions)
        snapshot.meta[MetaKeys.BUILT_AT] = time.strftime("%Y-%m-%d %H:%M:%S")
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
        # 指纹计算留在 service 层：测试按模块路径 patch fresh_llm_config。
        config = fresh_llm_config()
        fingerprint = extraction_fingerprint(config)
        return BuildSession(self, config=config, fingerprint=fingerprint,
                            doc_ids=doc_ids, progress=progress).run()

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
            MetaKeys.GRAPH_VERSION: store.meta.get(MetaKeys.GRAPH_VERSION, 0),
        }


service = RagService()
