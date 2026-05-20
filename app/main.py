"""static.jaschen.life — 静态站托管服务"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import SITES_DIR
from database import init_db

# 路由
from routes.api_keys import router as api_keys_router
from routes.api_sites import router as api_sites_router
from routes.serve import router as serve_router
from routes.web import router as web_router
from security import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    os.makedirs(SITES_DIR, exist_ok=True)
    await init_db()
    print(f"[INFO] 数据目录: {SITES_DIR}")
    print("[INFO] 服务已启动")
    yield
    # 关闭时
    pass


app = FastAPI(
    title="static.jaschen.life",
    description="极简静态 HTML 托管服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全头
app.add_middleware(SecurityHeadersMiddleware)

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册路由（顺序很重要：API -> Web -> Serve 通配）
app.include_router(api_keys_router)
app.include_router(api_sites_router)
app.include_router(web_router)
app.include_router(serve_router)
