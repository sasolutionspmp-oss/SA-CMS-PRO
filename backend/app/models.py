"""Database models."""
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, DateTime, Enum as SQLEnum, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Role(str, Enum):
    ADMIN = "Admin"
    PM = "PM"
    ESTIMATOR = "Estimator"
    VIEWER = "Viewer"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    role = Column(SQLEnum(Role), default=Role.VIEWER, nullable=False)
    token = Column(String(128), nullable=False)


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
