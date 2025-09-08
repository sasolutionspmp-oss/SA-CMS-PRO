from typing import Optional, List
from pydantic import BaseModel


class ProjectBase(BaseModel):
    region: Optional[str] = None
    client: Optional[str] = None
    scope_size: Optional[float] = None
    materials: Optional[float] = None
    duration: Optional[float] = None
    awarded_value: Optional[float] = None
    final_value: Optional[float] = None
    win_flag: Optional[bool] = None


class ProjectCreate(ProjectBase):
    pass


class Project(ProjectBase):
    id: int

    class Config:
        orm_mode = True


class TrainResult(BaseModel):
    r2: float
    mae: float
    feature_importances: List[float]
    features: List[str]


class InferenceRequest(BaseModel):
    projectId: Optional[int] = None
    features: Optional[ProjectBase] = None


class InferenceResponse(BaseModel):
    multiplier: float
    explanations: List[float]
    features: List[str]
