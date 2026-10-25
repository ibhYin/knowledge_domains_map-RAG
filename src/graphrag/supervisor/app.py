import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_PORT = 8002
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
LOG_DIR = ROOT_DIR / "data" / "logs"
BACKEND_LOG = LOG_DIR / "backend.log"
SUPERVISOR_PORT = 8001
SOURCE_DIR = ROOT_DIR / "src"
BACKEND_MODULE = "graphrag.api.main"
# 控制服务自身的代码不由 watcher 重启（需要重启 supervisor 才生效）。
WATCH_EXCLUDE = ("/supervisor/",)


class _SupervisorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore")
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    chunk_size: int = 600
    chunk_overlap: int = 100
    extraction_concurrency: int = 4
    structured_output_method: str = "json_mode"
    # 后端源码变更后自动重载；构建进行中会延后到任务结束。
    backend_autoreload: bool = True
    backend_autoreload_interval: float = 2.0


_settings = _SupervisorSettings()
AUTORELOAD_ENABLED = _settings.backend_autoreload
AUTORELOAD_INTERVAL = max(0.5, _settings.backend_autoreload_interval)


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def write_env(overrides: dict[str, str]) -> None:
    env_path = ROOT_DIR / ".env"
    content: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                content[k.strip()] = v.strip()
    content.update(overrides)
    env_path.write_text("".join(f"{k}={v}\n" for k, v in content.items()), encoding="utf-8")


class BackendManager:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.log_file = None
        self._lock = threading.RLock()
        self.last_restart_at: str | None = None
        self.last_restart_ok: bool | None = None
        self.last_restart_message = ""

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _health_ok(self) -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/api/health", timeout=1)
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _port_pid() -> int | None:
        try:
            out = subprocess.run(
                ["lsof", "-ti", f":{BACKEND_PORT}", "-sTCP:LISTEN", "-P", "-n"],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        for token in out.stdout.split():
            if token.isdigit():
                return int(token)
        return None

    @staticmethod
    def _pid_command(pid: int) -> str:
        try:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout.strip()

    def _wait_port_free(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._port_pid() != pid:
                return True
            time.sleep(0.2)
        return False

    def _terminate_pid(self, pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        if self._wait_port_free(pid, 10):
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        self._wait_port_free(pid, 5)

    def _close_log(self) -> None:
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def start(self) -> dict:
        with self._lock:
            if self.running:
                return {"ok": True, "message": "系统已在运行"}
            if self.proc is not None:
                self.proc = None
                self._close_log()
            orphan = self._port_pid()
            if orphan:
                return {
                    "ok": False,
                    "message": f"端口 {BACKEND_PORT} 已被占用（PID {orphan}），请先重启以接管",
                }
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            self.log_file = open(BACKEND_LOG, "ab")
            env = {**os.environ, "PYTHONPATH": str(ROOT_DIR / "src")}
            self.proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    BACKEND_MODULE + ":app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(BACKEND_PORT),
                ],
                cwd=ROOT_DIR,
                env=env,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            for _ in range(90):
                if self.proc.poll() is not None:
                    return {"ok": False, "message": "系统启动失败，请查看下方日志"}
                if self._health_ok():
                    return {"ok": True, "message": f"系统已启动（http://localhost:{BACKEND_PORT}）"}
                time.sleep(1)
            return {"ok": False, "message": "系统启动超时，请查看下方日志"}

    def stop(self) -> dict:
        with self._lock:
            if self.running:
                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(self.proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.proc.wait(timeout=5)
                self.proc = None
                self._close_log()
                return {"ok": True, "message": "系统已停止"}
            if self.proc is not None:
                self.proc = None
                self._close_log()
            # 兜底：后端不是本控制服务拉起的（控制服务重启过 / 手工启动）。
            orphan = self._port_pid()
            if not orphan:
                return {"ok": True, "message": "系统未在运行"}
            command = self._pid_command(orphan)
            if BACKEND_MODULE not in command:
                return {
                    "ok": False,
                    "message": f"端口 {BACKEND_PORT} 被其他进程占用（PID {orphan}：{command[:80]}），未处理",
                }
            self._terminate_pid(orphan)
            return {"ok": True, "message": f"已接管并停止未托管的旧后端（PID {orphan}）"}

    def restart(self, reason: str = "") -> dict:
        with self._lock:
            stopped = self.stop()
            if not stopped["ok"]:
                self.last_restart_at = time.strftime("%Y-%m-%d %H:%M:%S")
                self.last_restart_ok = False
                self.last_restart_message = stopped["message"]
                return stopped
            started = self.start()
            self.last_restart_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.last_restart_ok = started["ok"]
            self.last_restart_message = started["message"]
            if reason:
                log(f"{reason}：{started['message']}")
            return started

    def status(self) -> dict:
        running = self.running
        port_pid = self._port_pid()
        return {
            "backend_running": running,
            "backend_pid": self.proc.pid if running else None,
            "backend_port": BACKEND_PORT,
            "backend_ready": self._health_ok() if running else False,
            "app_url": f"http://localhost:{BACKEND_PORT}",
            "port_busy": bool(port_pid) and not running,
            "port_pid": port_pid if not running else None,
            "autoreload_enabled": AUTORELOAD_ENABLED,
            "autoreload_interval": AUTORELOAD_INTERVAL,
            "pending_reload": bool(watcher and watcher.pending),
            "watched_change_at": watcher.last_change_at if watcher else None,
            "last_reload_at": self.last_restart_at,
            "last_reload_ok": self.last_restart_ok,
            "last_reload_message": self.last_restart_message,
        }

    def tail_log(self, n: int = 80) -> str:
        if not BACKEND_LOG.exists():
            return ""
        lines = BACKEND_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])


class SourceWatcher(threading.Thread):
    """后端源码变化时自动重载；构建任务运行中则延后到任务结束。"""

    def __init__(self, manager: BackendManager):
        super().__init__(daemon=True, name="source-watcher")
        self.manager = manager
        self.pending = False
        self.last_change_at: str | None = None
        self._snapshot = self._scan()

    def _scan(self) -> dict[str, float]:
        snapshot: dict[str, float] = {}
        if not SOURCE_DIR.exists():
            return snapshot
        for path in SOURCE_DIR.rglob("*.py"):
            text = str(path)
            if any(part in text for part in WATCH_EXCLUDE):
                continue
            try:
                snapshot[text] = path.stat().st_mtime
            except OSError:
                continue
        return snapshot

    @staticmethod
    def _build_state() -> dict | None:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{BACKEND_PORT}/api/graph/build/current", timeout=2
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def _build_running(self) -> bool:
        state = self._build_state()
        return bool(state and state.get("status") == "running")

    def poll_once(self) -> None:
        snapshot = self._scan()
        changed = snapshot != self._snapshot
        if changed:
            self._snapshot = snapshot
            self.last_change_at = time.strftime("%Y-%m-%d %H:%M:%S")
            time.sleep(1.0)  # 等编辑器完成落盘
            self._snapshot = self._scan()
            log("检测到后端源码变更")
        if not changed and not self.pending:
            return
        if self._build_running():
            if not self.pending:
                log("构建进行中，重载延后到任务结束")
            self.pending = True
            return
        reason = "构建已结束，执行延后的重载" if self.pending else "源码变更且当前空闲"
        self.pending = False
        log(f"{reason}，开始重载后端")
        result = self.manager.restart()
        log(f"自动重载结果：{result['message']}")

    def run(self) -> None:
        log(f"自动重载已开启：监听 {SOURCE_DIR}（排除 supervisor），检查间隔 {AUTORELOAD_INTERVAL}s")
        while True:
            time.sleep(AUTORELOAD_INTERVAL)
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                log(f"自动重载检查失败：{type(exc).__name__}: {exc}")


manager = BackendManager()
watcher: SourceWatcher | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global watcher
    if AUTORELOAD_ENABLED and watcher is None:
        watcher = SourceWatcher(manager)
        watcher.start()
    yield


app = FastAPI(title="GraphRAG 控制台", lifespan=lifespan)


class SettingsUpdate(BaseModel):
    openai_base_url: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None


@app.get("/", response_class=PlainTextResponse)
def index():
    return "GraphRAG 控制服务运行中（无独立页面）。请访问 http://localhost:8002 使用问答系统。"


@app.get("/api/status")
def status():
    return manager.status()


@app.get("/api/settings")
def get_settings():
    s = _SupervisorSettings()
    return {
        "openai_base_url": s.openai_base_url,
        "openai_model": s.openai_model,
        "api_key_set": bool(s.openai_api_key),
        "chunk_size": s.chunk_size,
        "chunk_overlap": s.chunk_overlap,
        "extraction_concurrency": s.extraction_concurrency,
        "structured_output_method": s.structured_output_method,
    }


@app.post("/api/settings")
def save_settings(body: SettingsUpdate):
    updates: dict[str, str] = {}
    if body.openai_base_url and body.openai_base_url.strip():
        updates["OPENAI_BASE_URL"] = body.openai_base_url.strip()
    if body.openai_model and body.openai_model.strip():
        updates["OPENAI_MODEL"] = body.openai_model.strip()
    if body.openai_api_key and body.openai_api_key.strip():
        updates["OPENAI_API_KEY"] = body.openai_api_key.strip()
    if not updates:
        return {"ok": True, "message": "没有需要保存的更改"}
    write_env(updates)
    return {"ok": True, "message": "配置已保存，新的 LLM 配置会在下次调用时生效"}


@app.post("/api/start")
def start():
    return manager.start()


@app.post("/api/stop")
def stop():
    return manager.stop()


@app.post("/api/restart")
def restart():
    return manager.restart(reason="手动重启")


@app.get("/api/logs")
def logs(n: int = 80):
    return {"logs": manager.tail_log(n)}


@app.post("/api/quit")
def quit_supervisor():
    def _quit():
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=_quit, daemon=True).start()
    return {"ok": True, "message": "控制台即将退出"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=SUPERVISOR_PORT)
