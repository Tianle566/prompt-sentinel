from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from backend.app.api.routes import router
from backend.app.core.auth import bootstrap_users, jwt_secret
from backend.app.core.config import ROOT, get_config
from backend.app.db.models import Base, EvaluationJob
from backend.app.db.session import SessionLocal, engine


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    jwt_secret()
    with SessionLocal() as db:
        bootstrap_users(db)
        for job in db.scalars(select(EvaluationJob).where(EvaluationJob.status.in_(["queued", "running"]))):
            job.status = "failed"
            job.message = "服务重启，中断的任务请重新执行"
            job.error = "ServiceRestarted"
        db.commit()
    yield


config = get_config()
app = FastAPI(title=config["app"]["name"], description="提示词注入攻击检测与多层防护系统。所有模型推理均在本地进行，研究评测不调用第三方模型。", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config["app"]["cors_origins"], allow_credentials=False, allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])
app.include_router(router)


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/docs")
