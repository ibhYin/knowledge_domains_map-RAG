"""问答历史存储：文件持久化 + 摘要分页 + 单条详情。

列表只回摘要（不含 context/subgraph/sentences/sources 等大字段），
详情按需取；证据快照随记录持久化，删除文档后仍可核对。
"""

import json
import threading

from graphrag.config import settings
from graphrag.graph.persistence import _write_json

HISTORY_LIMIT = 100
SUMMARY_FIELDS = ("question", "answer", "matched", "node_count", "edge_count",
                  "verification", "used_docs", "ts")


class HistoryStore:
    def __init__(self, path=None):
        self.path = path if path is not None else settings.data_dir / "history.json"
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self, history: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(history[-HISTORY_LIMIT:], self.path)

    def page(self, offset: int, limit: int) -> dict:
        """新记录在前的摘要分页，items 携带原始位置 index 供详情查询。"""
        with self._lock:
            items = self._load()
        ordered = list(enumerate(items))[::-1]
        window = ordered[offset:offset + limit]
        return {
            "total": len(items),
            "items": [{**{k: item.get(k) for k in SUMMARY_FIELDS}, "index": index}
                      for index, item in window],
        }

    def detail(self, index: int, active_ids: set[str]) -> dict | None:
        with self._lock:
            items = self._load()
        if not 0 <= index < len(items):
            return None
        item = items[index]
        for source in [*(item.get("sources") or []), *(item.get("retrieved_sources") or [])]:
            source["deleted"] = source["doc_id"] not in active_ids
        return {**item, "index": index}

    def append(self, entry: dict) -> None:
        with self._lock:
            history = self._load()
            history.append(entry)
            self._save(history)

    def clear(self) -> None:
        with self._lock:
            self._save([])
