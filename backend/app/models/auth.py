from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    id: str
    username: str
    role: Literal["user", "admin"]
    is_active: bool
    created_at: datetime


class Credentials(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
