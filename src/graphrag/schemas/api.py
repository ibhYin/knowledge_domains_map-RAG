from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str
    hops: int = Field(default=2, ge=1, le=5)
    max_nodes: int = Field(default=40, ge=1, le=200)
    max_edges: int = Field(default=80, ge=1, le=500)
    seed_override: Optional[list[str]] = None


class BuildRequest(BaseModel):
    doc_ids: Optional[list[str]] = None
