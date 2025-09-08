import json
from pathlib import Path
from typing import Tuple, List

import joblib
import numpy as np
import pandas as pd
from shap import TreeExplainer
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import GradientBoostingRegressor

from sqlalchemy.orm import Session

from . import models

MODEL_DIR = Path('models')
MODEL_DIR.mkdir(exist_ok=True)


def load_projects(db: Session) -> pd.DataFrame:
    projects = db.query(models.Project).all()
    df = pd.DataFrame([
        {
            'id': p.id,
            'region': p.region,
            'client': p.client,
            'scope_size': p.scope_size,
            'materials': p.materials,
            'duration': p.duration,
            'awarded_value': p.awarded_value,
            'final_value': p.final_value,
            'win_flag': p.win_flag,
        }
        for p in projects
    ])
    return df


def train_model(df: pd.DataFrame) -> Tuple[Pipeline, dict, List[str]]:
    df = df.dropna(subset=['scope_size', 'final_value'])
    df['multiplier'] = df['final_value'] / df['scope_size']

    feature_cols = [
        'region', 'client', 'scope_size', 'materials', 'duration', 'awarded_value', 'win_flag'
    ]
    X = df[feature_cols]
    y = df['multiplier']

    categorical = ['region', 'client']
    numeric = ['scope_size', 'materials', 'duration', 'awarded_value', 'win_flag']
    preprocessor = ColumnTransformer(
        transformers=[
            ('cat', OneHotEncoder(handle_unknown='ignore'), categorical),
            ('num', 'passthrough', numeric)
        ]
    )

    model = GradientBoostingRegressor()
    pipe = Pipeline(steps=[('preprocess', preprocessor), ('model', model)])
    pipe.fit(X, y)
    preds = pipe.predict(X)
    metrics = {
        'r2': float(r2_score(y, preds)),
        'mae': float(mean_absolute_error(y, preds))
    }

    # feature importances after preprocessing
    model_features = pipe.named_steps['preprocess'].get_feature_names_out()
    importances = pipe.named_steps['model'].feature_importances_.tolist()
    return pipe, metrics, model_features.tolist(), importances


def save_model(db: Session, pipe: Pipeline, metrics: dict, features: List[str], importances: List[float]):
    existing = (
        db.query(models.ModelRegistry)
        .filter(models.ModelRegistry.name == 'baseline')
        .order_by(models.ModelRegistry.version.desc())
        .first()
    )
    version = 1 if not existing else existing.version + 1
    model_path = MODEL_DIR / f'baseline_{version}.joblib'
    joblib.dump({'model': pipe, 'features': features}, model_path)

    registry = models.ModelRegistry(
        name='baseline',
        version=version,
        path=str(model_path),
        params={},
        metrics={'r2': metrics['r2'], 'mae': metrics['mae'], 'feature_importances': importances, 'features': features}
    )
    db.add(registry)
    db.commit()
    db.refresh(registry)
    return registry


def latest_model(db: Session):
    registry = (
        db.query(models.ModelRegistry)
        .filter(models.ModelRegistry.name == 'baseline')
        .order_by(models.ModelRegistry.version.desc())
        .first()
    )
    if not registry:
        return None, None
    data = joblib.load(registry.path)
    return registry, data['model'], data['features']


def infer(pipe: Pipeline, features: List[str], X: pd.DataFrame) -> Tuple[float, List[float]]:
    multiplier = float(pipe.predict(X)[0])
    explainer = TreeExplainer(pipe.named_steps['model'])
    # For shap values we need transformed features
    transformed = pipe.named_steps['preprocess'].transform(X)
    shap_values = explainer.shap_values(transformed)[0].tolist()
    return multiplier, shap_values
