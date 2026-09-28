from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from graphrag.api.routes import router
from graphrag.config import ROOT_DIR
from graphrag.pipeline.service import service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    service.store.load()
    yield


app = FastAPI(title="GraphRAG", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

_dist = ROOT_DIR / "web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="web")
