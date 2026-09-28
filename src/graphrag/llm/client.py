from typing import Optional

from langchain_openai import ChatOpenAI

from graphrag.config import settings


def build_llm(model: Optional[str] = None, temperature: Optional[float] = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=temperature if temperature is not None else settings.temperature_extract,
        max_retries=3,
        timeout=120,
    )
