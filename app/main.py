from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import pandas as pd

from . import models, schemas
from .database import Base, engine, get_db
from .training import load_projects, train_model, save_model, latest_model, infer

Base.metadata.create_all(bind=engine)

app = FastAPI()


@app.post('/api/history/upload')
async def upload_history(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail='Only CSV files supported')
    df = pd.read_csv(file.file)
    for _, row in df.iterrows():
        project = models.Project(
            region=row.get('region'),
            client=row.get('client'),
            scope_size=row.get('scope_size'),
            materials=row.get('materials'),
            duration=row.get('duration'),
            awarded_value=row.get('awarded_value'),
            final_value=row.get('final_value'),
            win_flag=row.get('win_flag'),
        )
        db.add(project)
    db.commit()
    return {'rows': len(df)}


@app.post('/api/learn/train', response_model=schemas.TrainResult)
def train(db: Session = Depends(get_db)):
    df = load_projects(db)
    if df.empty:
        raise HTTPException(status_code=400, detail='No data to train')
    pipe, metrics, features, importances = train_model(df)
    save_model(db, pipe, metrics, features, importances)
    return schemas.TrainResult(r2=metrics['r2'], mae=metrics['mae'], feature_importances=importances, features=features)


@app.post('/api/learn/infer', response_model=schemas.InferenceResponse)
def infer_route(request: schemas.InferenceRequest, db: Session = Depends(get_db)):
    registry, model, features = latest_model(db)
    if not model:
        raise HTTPException(status_code=400, detail='Model not trained')

    if request.projectId is not None:
        project = db.query(models.Project).filter(models.Project.id == request.projectId).first()
        if not project:
            raise HTTPException(status_code=404, detail='Project not found')
        data = pd.DataFrame([{f: getattr(project, f) for f in ['region','client','scope_size','materials','duration','awarded_value','win_flag']}])
    elif request.features is not None:
        data = pd.DataFrame([request.features.dict()])
    else:
        raise HTTPException(status_code=400, detail='Provide projectId or features')

    multiplier, explanations = infer(model, features, data)
    return schemas.InferenceResponse(multiplier=multiplier, explanations=explanations, features=features)
