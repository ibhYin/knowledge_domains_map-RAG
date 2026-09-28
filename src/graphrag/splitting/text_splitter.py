from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from graphrag.config import settings


def build_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
    )


def split_documents(docs: list[Document], doc_id: str) -> list[Document]:
    splitter = build_splitter()
    chunks = splitter.split_documents(docs)
    for idx, chunk in enumerate(chunks):
        chunk.metadata = {**chunk.metadata, "chunk_index": idx}
    return chunks
