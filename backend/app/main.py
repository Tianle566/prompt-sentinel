from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from backend.app.api.routes import router
from backend.app.core.auth import bootstrap_users, jwt_secret
from backend.app.core.config import ROOT, get_config
from backend.app.db.models import Base, EvaluationJob
from backend.app.db.migrations import initialize_database
from backend.app.db.session import SessionLocal, engine


@asynccontextmanager
async def lifespan(app):
    initialize_database(engine)
    jwt_secret()
    with SessionLocal() as db:
        bootstrap_users(db)
        for job in db.scalars(select(EvaluationJob).where(EvaluationJob.status.in_(["queued", "running", "cancelling"]))):
            job.status = "cancelled" if job.cancel_requested else "failed"
            job.message = "取消的任务已停止" if job.cancel_requested else "服务重启，中断的任务请重新执行"
            job.error = None if job.cancel_requested else "ServiceRestarted"
        db.commit()
    yield


config = get_config()
app = FastAPI(title=config["app"]["name"], description="提示词注入攻击检测与多层防护系统。默认使用本地模型，支持管理员配置 OpenAI 兼容目标接口；攻击对照及 ASR 研究评测限定本机。", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config["app"]["cors_origins"], allow_credentials=False, allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])
app.include_router(router)


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/docs")
