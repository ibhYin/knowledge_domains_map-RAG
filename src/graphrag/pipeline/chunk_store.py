import hashlib
import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path

from langchain_core.documents import Document

from graphrag.config import settings
from graphrag.graph.persistence import _write_json
from graphrag.schemas.extraction import ChunkExtraction

logger = logging.getLogger(__name__)


def chunk_id_of(doc_id: str, chunk_index: int) -> str:
    return f"{doc_id}:{chunk_index}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChunkStore:
    """分块存储。JSONL 落盘之外维护惰性内存索引：iter_chunks 直接走索引，
    问答/构建不再每次重读全部语料。索引由本进程独占维护（外部改动需重启后端）。"""

    def __init__(self):
        self._index: dict[str, list[dict]] | None = None
        self._index_lock = threading.Lock()

    def _ensure_index(self) -> dict[str, list[dict]]:
        with self._index_lock:
            if self._index is None:
                index: dict[str, list[dict]] = {}
                for path in sorted(settings.chunks_dir.glob("*.jsonl")):
                    records = []
                    with path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                records.append(json.loads(line))
                    index[path.stem] = records
                self._index = index
            return self._index

    def _extraction_file(self, chunk_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+:[0-9]+", chunk_id):
            raise ValueError("无效的分块 ID")
        doc_id, index = chunk_id.split(":")
        return settings.data_dir / "extractions" / doc_id / f"{index}.json"

    def load_extraction(self, chunk_id: str, digest: str, fingerprint: str) -> ChunkExtraction | None:
        path = self._extraction_file(chunk_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (data["chunk_id"], data["content_hash"], data["fingerprint"]) != (chunk_id, digest, fingerprint):
                return None
            return ChunkExtraction.model_validate(data["extraction"])
        except (ValueError, KeyError, TypeError):
            logger.warning("抽取缓存无效，将重新抽取: %s", chunk_id)
            return None

    def save_extraction(self, chunk_id: str, digest: str, fingerprint: str, extraction: ChunkExtraction) -> None:
        _write_json({"chunk_id": chunk_id, "content_hash": digest, "fingerprint": fingerprint,
                     "extraction": extraction.model_dump(mode="json")}, self._extraction_file(chunk_id))

    def _chunk_file(self, doc_id: str) -> Path:
        return settings.chunks_dir / f"{doc_id}.jsonl"

    def save_chunks(self, doc_id: str, chunks: list[Document]) -> None:
        path = self._chunk_file(doc_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = []
        with path.open("w", encoding="utf-8") as f:
            for chunk in chunks:
                record = {
                    "chunk_index": chunk.metadata.get("chunk_index", 0),
                    "content": chunk.page_content,
                    "metadata": chunk.metadata,
                }
                records.append(record)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        with self._index_lock:
            if self._index is not None:
                self._index[doc_id] = records

    def iter_chunks(self, doc_ids: list[str] | None = None) -> list[dict]:
        """返回分块记录。记录为索引内共享引用，调用方只读不得修改。"""
        index = self._ensure_index()
        keys = sorted(index) if doc_ids is None else doc_ids
        out = []
        for doc_id in keys:
            out.extend(index.get(doc_id, []))
        return out

    # ---------- 文档注册表 ----------

    def _load_registry(self) -> dict:
        if not settings.index_file.exists():
            return {}
        return json.loads(settings.index_file.read_text(encoding="utf-8"))

    def _save_registry(self, registry: dict) -> None:
        _write_json(registry, settings.index_file)

    def register(self, doc_id: str, filename: str, size: int, chunk_count: int) -> None:
        registry = self._load_registry()
        registry[doc_id] = {
            "filename": filename,
            "size": size,
            "chunk_count": chunk_count,
            "status": "ingested",
            "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_registry(registry)

    def list_documents(self) -> list[dict]:
        registry = self._load_registry()
        return [
            {"doc_id": doc_id, **meta}
            for doc_id, meta in sorted(registry.items(), key=lambda kv: kv[1].get("uploaded_at", ""))
        ]

    def delete_document(self, doc_id: str) -> bool:
        registry = self._load_registry()
        existed = doc_id in registry
        if existed:
            registry.pop(doc_id)
            self._save_registry(registry)
        doc_files = list(settings.documents_dir.glob(f"{doc_id}.*"))
        for p in [*doc_files, self._chunk_file(doc_id)]:
            if p.exists():
                p.unlink()
        extraction_dir = self._extraction_file(f"{doc_id}:0").parent
        if extraction_dir.exists():
            shutil.rmtree(extraction_dir)
        with self._index_lock:
            if self._index is not None:
                self._index.pop(doc_id, None)
        return existed
