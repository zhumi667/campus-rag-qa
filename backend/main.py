"""backend/main.py — FastAPI 应用入口

运行方式（从项目根 D:\\campus-rag 启动）：
    $env:PYTHONIOENCODING='utf-8'
    D:\\Miniconda3\\envs\\campus-rag\\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

后端目录以包（backend/__init__.py）形式从项目根导入；从项目根用 `python -m uvicorn`
启动时项目根已在 sys.path，`import config`、`from src import ...` 均可直接使用。
"""
import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

# 项目根入 path（保险：即便从非项目根启动也能 import config / src）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

import config  # noqa: E402
from src import utils  # noqa: E402
from backend import db  # noqa: E402
from backend.routers import admin, chat, sessions, auth, corpus  # noqa: E402

logger = utils.get_logger("backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    seeded = db.seed_default_users()
    purged = db.purge_expired_tokens()
    admin_exists = db.get_user_by_username("admin") is not None
    student_exists = db.get_user_by_username("student") is not None
    print(f"[启动] 用户: admin={admin_exists} student={student_exists} (本次新建 {seeded})  清理过期令牌 {purged} 个")
    from src.pipeline import QAPipeline
    h = QAPipeline().health()
    print(f"[启动] 模型={config.OLLAMA_MODEL}  索引块数={h['index']['size']}  语料文档数={h['corpus']['docs']}")
    yield


app = FastAPI(title="校园领域智能问答系统", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(admin.router)
app.include_router(corpus.router)


@app.get("/api/health")
def health():
    from src.pipeline import QAPipeline
    return QAPipeline().health()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error("未捕获异常: %s %s\n%s", request.method, request.url, tb)
    return JSONResponse(
        status_code=500,
        content={"error": {"type": type(exc).__name__, "message": str(exc)}},
    )
