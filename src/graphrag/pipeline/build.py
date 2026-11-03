"""构建会话：计划（reset/todo 判定）→ 抽取收割 → 检查点发布编排。

发布动作委托 RagService._publish_snapshot（换图权威，由单线程执行器串行
调用）；本类只决定「何时发布」，发布条件独立成纯方法便于单测。
"""

import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy

from graphrag.config import settings
from graphrag.graph.meta import MetaKeys
from graphrag.graph.store import GraphStore
from graphrag.llm.extractor import EXTRACTION_SYSTEM_PROMPT, EntityExtractor
from graphrag.pipeline.chunk_store import chunk_id_of, content_hash
from graphrag.schemas.extraction import ChunkExtraction


def extraction_fingerprint(config: dict) -> str:
    """抽取配置指纹：内容/模型/提示词/结构任一变化即失效缓存。"""
    return content_hash(json.dumps({
        "config": {k: v for k, v in config.items() if k not in {"openai_api_key", "temperature_answer"}},
        "prompt": EXTRACTION_SYSTEM_PROMPT, "schema": ChunkExtraction.model_json_schema(),
    }, sort_keys=True, ensure_ascii=False))


class BuildSession:
    def __init__(self, service, config: dict, fingerprint: str,
                 doc_ids: list[str] | None = None, progress=None):
        self.service = service
        self.config = config
        self.fingerprint = fingerprint
        self.doc_ids = doc_ids
        self.progress = progress
        self.records: list[dict] = []
        self.todo: list[tuple] = []
        self.reset = False
        self.total = 0
        self.working_store: GraphStore | None = None
        self.extractions: dict[str, ChunkExtraction] = {}
        self.saved_success_count = 0
        self.checkpoint_processed = 0
        self.done = 0
        self.failed = 0

    # ---------- 计划 ----------

    def plan(self) -> None:
        store = self.service.store
        deleted = set(store.meta.get(MetaKeys.DELETED_DOCUMENTS, []))
        self.records = [r for r in self.service.chunks.iter_chunks(self.doc_ids)
                        if r["metadata"]["doc_id"] not in deleted]
        processed = store.meta.get(MetaKeys.PROCESSED_CHUNKS, {})
        # 指纹一致时 _extractions 即经校验的有效抽取（启动加载/发布换图时同步维护），
        # 单次遍历完成 reset 判定与 todo 收集，不再重复读盘、重复计算内容哈希。
        cached = store._extractions if store.meta.get(MetaKeys.EXTRACTION_FINGERPRINT) == self.fingerprint else {}
        self.reset = bool(processed) and store.meta.get(MetaKeys.EXTRACTION_FINGERPRINT) != self.fingerprint
        todo = []
        if not self.reset:
            for record in self.records:
                doc_id = record.get("metadata", {}).get("doc_id", "")
                cid = chunk_id_of(doc_id, record["chunk_index"])
                h = content_hash(record["content"])
                state = processed.get(cid)
                if state is not None and state != h:
                    self.reset = True  # 分块内容与成功记录不符，旧抽取全部失效
                    break
                if state == h:
                    if cid not in cached:
                        self.reset = True  # 已处理分块缺少有效抽取缓存，全量重建更安全
                        break
                    continue  # 已处理且缓存有效，跳过
                todo.append((cid, record["content"], h, cached.get(cid)))
        if self.reset:
            self.records = [r for r in self.service.chunks.iter_chunks() if r["metadata"]["doc_id"] not in deleted]
            todo = [(chunk_id_of(r.get("metadata", {}).get("doc_id", ""), r["chunk_index"]),
                     r["content"], content_hash(r["content"]), None) for r in self.records]
        self.todo = todo
        self.total = len(todo)

        # 工作副本只携带 meta（processed_chunks 等），图由发布线程全量重放生成。
        if self.todo:
            self.working_store = GraphStore()
            self.extractions = dict(store._extractions)
            if self.reset:
                self.extractions = {}
                self.working_store.meta[MetaKeys.GRAPH_VERSION] = store.meta.get(MetaKeys.GRAPH_VERSION, 0)
                self.working_store.meta[MetaKeys.DELETED_DOCUMENTS] = sorted(deleted)
            else:
                self.working_store.meta = deepcopy(store.meta)
            self.working_store.meta[MetaKeys.EXTRACTION_FINGERPRINT] = self.fingerprint

    # ---------- 发布时机 ----------

    @staticmethod
    def _should_publish(*, has_new_success: bool, first_publish: bool, interval_due: bool,
                        time_due: bool, pending_empty: bool, in_flight: bool) -> bool:
        """有新成功结果，且（首发 / 攒满间隔 / 超时 / 收尾），且上一拍发布已完成。"""
        return has_new_success and (first_publish or interval_due or time_due or pending_empty) and not in_flight

    # ---------- 收割与发布 ----------

    def run(self) -> dict:
        service = self.service
        self.plan()
        if self.progress:
            self.progress({"status": "running", "processed": 0, "total": self.total, "failed": 0,
                           MetaKeys.GRAPH_VERSION: service.store.meta.get(MetaKeys.GRAPH_VERSION, 0), "error": None})

        # 大语料自适应：按总量把发布会次数限制在约 50 次以内，小语料维持原间隔。
        checkpoint_interval = max(settings.build_checkpoint_interval, (self.total + 49) // 50)
        # 所有 worker 共享同一 extractor：复用 ChatOpenAI/httpx 连接池，避免每分块重复握手。
        extractor = EntityExtractor(config=self.config)
        try:
            extractor._get_chain()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"模型配置不可用，请检查「模型设置」: {type(exc).__name__}") from exc

        def extract_task(item):
            cid, text, h, cached_ext = item
            ext = cached_ext if cached_ext is not None else service.chunks.load_extraction(cid, h, self.fingerprint)
            if ext is None:
                ext = extractor.extract(text)
                if ext is not None:
                    service.chunks.save_extraction(cid, h, self.fingerprint, ext)
            return cid, h, ext

        publisher = ThreadPoolExecutor(max_workers=1, thread_name_prefix="graph-publish")
        publish_future = None
        try:
            with ThreadPoolExecutor(max_workers=settings.extraction_concurrency) as pool:
                pending = {pool.submit(extract_task, item) for item in self.todo}
                last_published = time.monotonic()
                while pending:
                    finished, pending = wait(pending, timeout=min(1.0, settings.build_publish_interval),
                                             return_when=FIRST_COMPLETED)
                    for future in finished:
                        cid, h, ext = future.result()
                        if ext is not None:
                            self.extractions[cid] = ext
                            self.working_store.meta.setdefault(MetaKeys.PROCESSED_CHUNKS, {})[cid] = h
                        else:
                            self.failed += 1
                        self.done += 1
                    published = False
                    success_now = self.done - self.failed
                    if self._should_publish(
                        has_new_success=success_now > self.saved_success_count,
                        first_publish=self.saved_success_count == 0,
                        interval_due=success_now - self.saved_success_count >= checkpoint_interval,
                        time_due=time.monotonic() - last_published >= settings.build_publish_interval,
                        pending_empty=not pending,
                        in_flight=publish_future is not None and not publish_future.done(),
                    ):
                        # 发布在后台单线程串行执行（全量重放+落盘+换图），收割循环不再被阻塞；
                        # 上一次未完成时跳过，条件持续满足会在下一轮补发最新状态。
                        publish_future = publisher.submit(
                            service._publish_snapshot, dict(self.extractions), deepcopy(self.working_store.meta))
                        self.saved_success_count = success_now
                        self.checkpoint_processed = self.done
                        last_published = time.monotonic()
                        published = True
                    if publish_future is not None and publish_future.done():
                        exc = publish_future.exception()
                        if exc is not None:
                            raise exc
                    if self.progress and (finished or published):
                        with service._lock:
                            nodes = service.store.G.number_of_nodes()
                            edges = service.store.G.number_of_edges()
                            version = service.store.meta.get(MetaKeys.GRAPH_VERSION, 0)
                        self.progress({
                            "status": "running", "processed": self.done, "total": self.total,
                            "failed": self.failed, "error": None,
                            "nodes": nodes,
                            "edges": edges,
                            "checkpoint_processed": self.checkpoint_processed,
                            MetaKeys.GRAPH_VERSION: version,
                        })
            # 收尾发布：最后一批若因上次发布进行中被跳过，在此补发。
            if self.todo and self.done - self.failed > self.saved_success_count:
                publish_future = publisher.submit(
                    service._publish_snapshot, dict(self.extractions), deepcopy(self.working_store.meta))
            if publish_future is not None:
                publish_future.result()
        finally:
            publisher.shutdown(wait=True)
        return self.finish()

    # ---------- 结果 ----------

    def finish(self) -> dict:
        error = None
        if self.total and self.failed == self.total:
            status = "error"
            error = "全部分块抽取失败，请检查模型配置或后端日志后重试。当前图谱未更新。"
            message = error
        elif self.failed:
            status = "partial"
            message = "已保存成功抽取的结果；再次点击构建可重试失败分块。"
        else:
            status = "done"
            if not self.records:
                message = "没有可构建的分块，请先上传有效文档。"
            elif not self.total:
                message = "所有分块均已处理，无需重复构建。"
            else:
                message = "构建结果已保存。"
        result = {
            "status": status,
            "processed": self.done,
            "total": self.total,
            "failed": self.failed,
            "error": error,
            "message": message,
            "checkpoint_processed": self.checkpoint_processed,
            **self.service.store.stats(),
        }
        if self.progress:
            self.progress(result)
        return result
