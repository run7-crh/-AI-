# backend/app/main.py
from fastapi import FastAPI
from app.api import health
from app.api.errors import register_error_handlers

app = FastAPI(title="学AI必备助手 API", version="1.0.0")
app.include_router(health.router)
register_error_handlers(app)
