from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM（OpenAI 兼容端点）
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    temperature_extract: float = 0.1
    temperature_answer: float = 0.3
    structured_output_method: str = "json_mode"
    extraction_thinking: Literal["enabled", "disabled"] | None = None

    # 分块
    chunk_size: int = 600
    chunk_overlap: int = 100

    # 图谱与数据目录
    data_dir: Path = ROOT_DIR / "data"
    extraction_concurrency: int = 4
    build_checkpoint_interval: int = Field(default=50, ge=1)

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def chunks_dir(self) -> Path:
        return self.data_dir / "chunks"

    @property
    def index_file(self) -> Path:
        return self.data_dir / "index" / "documents.json"

    @property
    def graph_file(self) -> Path:
        return self.data_dir / "graph" / "graph.json"

    @property
    def graph_meta_file(self) -> Path:
        return self.data_dir / "graph" / "meta.json"


settings = Settings()


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


def fresh_llm_config() -> dict:
    """每次调用时重新读取 .env，使页面保存的 LLM 配置立即生效。"""
    s = Settings()
    return {
        "openai_base_url": s.openai_base_url,
        "openai_api_key": s.openai_api_key,
        "openai_model": s.openai_model,
        "temperature_extract": s.temperature_extract,
        "temperature_answer": s.temperature_answer,
        "structured_output_method": s.structured_output_method,
        "extraction_thinking": s.extraction_thinking,
    }
