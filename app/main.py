import sys
import logging
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.INFO)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from app.database import init_db
from app.api import novels, outlines, chapters, reviews, rag, knowledge, llm_providers
from app.api.knowledge_bases import router as kb_router
from app.api.ordinary_knowledge_bases import router as ordinary_kb_router

app = FastAPI(title="AI小说写作系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(novels.router, prefix="/api/novels", tags=["小说管理"])
app.include_router(outlines.router, prefix="/api/novels", tags=["大纲管理"])
app.include_router(chapters.router, prefix="/api/novels", tags=["章节管理"])
app.include_router(reviews.router, prefix="/api/novels", tags=["审查决策"])
app.include_router(rag.router, prefix="/api/novels", tags=["RAG管理"])
app.include_router(knowledge.router, prefix="/api/novels", tags=["知识管理"])
app.include_router(kb_router, prefix="/api/knowledge-bases", tags=["知识库管理"])
app.include_router(ordinary_kb_router, prefix="/api/ordinary-knowledge-bases", tags=["普通知识库"])
app.include_router(llm_providers.router, prefix="/api/llm-providers", tags=["大模型供应商"])

static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
async def startup():
    await init_db()
    from app.llm.siliconflow import reconfigure_llm_client
    await reconfigure_llm_client()


@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse(str(static_dir / "index.html"))
