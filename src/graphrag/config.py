from pathlib import Path

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

    # 分块
    chunk_size: int = 600
    chunk_overlap: int = 100

    # 图谱与数据目录
    data_dir: Path = ROOT_DIR / "data"
    extraction_concurrency: int = 4

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
