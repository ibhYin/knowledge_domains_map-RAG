from typing import Optional

from langchain_openai import ChatOpenAI

from graphrag.config import fresh_llm_config


def build_llm(model: Optional[str] = None, temperature: Optional[float] = None, *, for_extraction: bool = False) -> ChatOpenAI:
    cfg = fresh_llm_config()
    return ChatOpenAI(
        model=model or cfg["openai_model"],
        api_key=cfg["openai_api_key"],
        base_url=cfg["openai_base_url"],
        temperature=temperature if temperature is not None else cfg["temperature_extract"],
        max_retries=3,
        timeout=120,
        extra_body={"thinking": {"type": cfg["extraction_thinking"]}}
        if for_extraction and cfg["extraction_thinking"] else None,
    )
