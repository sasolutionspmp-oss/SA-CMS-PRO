from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .database import Base


class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, index=True)
    region = Column(String, index=True)
    client = Column(String, index=True)
    scope_size = Column(Float)
    materials = Column(Float)
    duration = Column(Float)
    awarded_value = Column(Float)
    final_value = Column(Float)
    win_flag = Column(Boolean)

    estimates = relationship('Estimate', back_populates='project')
    outcome = relationship('Outcome', uselist=False, back_populates='project')


class Estimate(Base):
    __tablename__ = 'estimates'
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'))

    project = relationship('Project', back_populates='estimates')
    lines = relationship('EstimateLine', back_populates='estimate')


class EstimateLine(Base):
    __tablename__ = 'estimate_lines'
    id = Column(Integer, primary_key=True, index=True)
    estimate_id = Column(Integer, ForeignKey('estimates.id'))
    description = Column(String)
    cost = Column(Float)

    estimate = relationship('Estimate', back_populates='lines')


class Outcome(Base):
    __tablename__ = 'outcomes'
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    awarded_value = Column(Float)
    final_value = Column(Float)
    win_flag = Column(Boolean)

    project = relationship('Project', back_populates='outcome')


class ModelRegistry(Base):
    __tablename__ = 'model_registry'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    version = Column(Integer, index=True)
    path = Column(String)
    params = Column(JSON)
    metrics = Column(JSON)
