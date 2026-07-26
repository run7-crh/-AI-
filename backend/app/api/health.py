# backend/app/api/health.py
from fastapi import APIRouter
from app.models.schemas import HealthResponse
from app.config import settings

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        model=settings.MODEL_FLASH,
        vector_db="chroma",
        embedding_model=settings.EMBEDDING_MODEL,
    )
