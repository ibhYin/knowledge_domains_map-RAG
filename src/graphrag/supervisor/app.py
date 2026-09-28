import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

BACKEND_PORT = 8002
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
LOG_DIR = ROOT_DIR / "data" / "logs"
BACKEND_LOG = LOG_DIR / "backend.log"
SUPERVISOR_PORT = 8001


class _SupervisorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore")
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    chunk_size: int = 600
    chunk_overlap: int = 100
    extraction_concurrency: int = 4
    structured_output_method: str = "json_mode"


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

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _health_ok(self) -> bool:
        import urllib.request

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/api/health", timeout=1)
            return True
        except Exception:  # noqa: BLE001
            return False

    def start(self) -> dict:
        if self.running:
            return {"ok": True, "message": "系统已在运行"}
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_file = open(BACKEND_LOG, "ab")
        env = {**os.environ, "PYTHONPATH": str(ROOT_DIR / "src")}
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.graphrag.api.main:app",
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
        if not self.running:
            return {"ok": True, "message": "系统未在运行"}
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:  # noqa: PERF203
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
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        return {"ok": True, "message": "系统已停止"}

    def status(self) -> dict:
        running = self.running
        return {
            "backend_running": running,
            "backend_pid": self.proc.pid if running else None,
            "backend_port": BACKEND_PORT,
            "backend_ready": self._health_ok() if running else False,
            "app_url": f"http://localhost:{BACKEND_PORT}",
        }

    def tail_log(self, n: int = 80) -> str:
        if not BACKEND_LOG.exists():
            return ""
        lines = BACKEND_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])


manager = BackendManager()
app = FastAPI(title="GraphRAG 控制台")


class SettingsUpdate(BaseModel):
    openai_base_url: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def index():
    page = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


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
    manager.stop()
    return manager.start()


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
