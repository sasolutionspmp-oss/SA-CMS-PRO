"""Pydantic schemas for API requests and responses."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from .models import Role


class UserCreate(BaseModel):
    username: str
    role: Role
    token: str


class UserRead(BaseModel):
    id: int
    username: str
    role: Role
    model_config = ConfigDict(from_attributes=True)


class DocumentCreate(BaseModel):
    content: str


class DocumentRead(DocumentCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
