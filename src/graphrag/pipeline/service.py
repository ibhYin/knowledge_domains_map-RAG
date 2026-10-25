import hashlib
import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from graphrag.config import settings
from graphrag.graph.store import GraphStore
from graphrag.llm.client import build_llm
from graphrag.llm.extractor import EntityExtractor
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
        processed = self.store.meta.get("processed_chunks", {})
        todo = []
        for record in records:
            doc_id = record.get("metadata", {}).get("doc_id", "")
            cid = chunk_id_of(doc_id, record["chunk_index"])
            h = content_hash(record["content"])
            if processed.get(cid) == h:
                continue
            todo.append((cid, record["content"], h))

        total = len(todo)
        if progress:
            progress({"status": "running", "processed": 0, "total": total, "failed": 0,
                      "graph_version": self.store.meta.get("graph_version", 0), "error": None})

        # ponytail: 小语料按批次复制整图保存检查点；大图时改用事务存储。
        working_store = deepcopy(self.store) if todo else None
        saved_success_count = 0
        checkpoint_processed = 0

        def extract_task(item):
            cid, text, h = item
            ext = EntityExtractor().extract(text)
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
                        working_store.add_extraction(ext, cid)
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
                    snapshot = deepcopy(working_store)
                    snapshot.meta["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    snapshot.save()
                    with self._lock:
                        self.store.G = snapshot.G
                        self.store.resolver = snapshot.resolver
                        self.store.meta = snapshot.meta
                    working_store.meta["graph_version"] = snapshot.meta["graph_version"]
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
