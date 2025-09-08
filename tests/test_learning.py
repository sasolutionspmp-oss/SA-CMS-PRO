import io
import os
import sys
import pandas as pd
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app.main import app

client = TestClient(app)


def synthetic_csv():
    df = pd.DataFrame({
        'region': ['A', 'B', 'A', 'C'],
        'client': ['X', 'Y', 'Z', 'X'],
        'scope_size': [100, 200, 150, 120],
        'materials': [50, 80, 60, 55],
        'duration': [10, 20, 15, 12],
        'awarded_value': [1000, 2500, 1800, 1500],
        'final_value': [1100, 2600, 1700, 1600],
        'win_flag': [1, 0, 1, 1],
    })
    return df


def test_train_and_infer():
    df = synthetic_csv()
    csv_bytes = df.to_csv(index=False).encode('utf-8')
    response = client.post('/api/history/upload', files={'file': ('history.csv', io.BytesIO(csv_bytes), 'text/csv')})
    assert response.status_code == 200

    train_resp = client.post('/api/learn/train')
    assert train_resp.status_code == 200
    data = train_resp.json()
    assert 'r2' in data and 'mae' in data
    assert len(data['feature_importances']) == len(data['features'])

    payload = {
        'features': {
            'region': 'A',
            'client': 'X',
            'scope_size': 100,
            'materials': 50,
            'duration': 10,
            'awarded_value': 1000,
            'win_flag': 1
        }
    }
    infer_resp = client.post('/api/learn/infer', json=payload)
    assert infer_resp.status_code == 200
    infer_data = infer_resp.json()
    assert 'multiplier' in infer_data
    assert len(infer_data['explanations']) == len(infer_data['features'])
