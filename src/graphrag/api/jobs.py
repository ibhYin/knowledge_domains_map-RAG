"""构建/删除任务注册表：状态机与后台执行。

状态流转：running → done/partial/error；删除用临时 deleting 占位与构建互斥，
占位在重放结束后立即移除。任务字典同时承担「最近一次任务」的查询来源，
因此完成的任务保留在内存中（随进程生命周期）。
"""

import threading
import uuid

STATUS_RUNNING = "running"
STATUS_DELETING = "deleting"


class JobConflict(Exception):
    """任务互斥冲突（构建中删除、删除中构建等），message 面向用户展示。"""


class JobManager:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start_build(self, run_fn) -> str:
        """启动构建线程并返回 job_id；已有 running 任务则直接返回其 id（幂等），
        deleting 占位期间抛 JobConflict。run_fn(progress) 在后台线程执行。"""
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            for existing_id, state in self._jobs.items():
                if state["status"] == STATUS_RUNNING:
                    return existing_id
            if any(state["status"] == STATUS_DELETING for state in self._jobs.values()):
                raise JobConflict("正在删除文档，请等待删除完成后重新构建。")
            self._jobs[job_id] = {"status": STATUS_RUNNING, "processed": 0, "total": 0, "error": None}

        def progress(state: dict):
            with self._lock:
                self._jobs[job_id].update(state)

        def run():
            try:
                run_fn(progress)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._jobs[job_id].update({"status": "error", "error": str(exc)})

        threading.Thread(target=run, daemon=True).start()
        return job_id

    def register_deleting(self) -> str:
        """注册 deleting 占位（与构建/其他删除互斥），重放结束后必须 release。"""
        key = f"delete-{uuid.uuid4().hex[:8]}"
        with self._lock:
            if any(state["status"] == STATUS_RUNNING for state in self._jobs.values()):
                raise JobConflict("构建中不能删除文档，请等待任务结束。")
            if any(state["status"] == STATUS_DELETING for state in self._jobs.values()):
                raise JobConflict("正在删除文档，请稍后再试。")
            self._jobs[key] = {"status": STATUS_DELETING, "processed": 0, "total": 0, "error": None}
        return key

    def release(self, key: str) -> None:
        with self._lock:
            self._jobs.pop(key, None)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return dict(job) if job else None

    def current(self) -> dict | None:
        """最近一次可展示的任务：优先 running，其次是最后一个非 deleting 任务。"""
        with self._lock:
            jobs = [(key, state) for key, state in self._jobs.items() if state["status"] != STATUS_DELETING]
            current = next(((key, state) for key, state in reversed(jobs) if state["status"] == STATUS_RUNNING),
                           jobs[-1] if jobs else None)
        return {**current[1], "job_id": current[0]} if current else None

    def has_active(self) -> bool:
        with self._lock:
            return any(state["status"] in (STATUS_RUNNING, STATUS_DELETING) for state in self._jobs.values())
