# SA-CMS-PRO

Prototype continuous learning API with FastAPI.

## Endpoints
- `POST /api/history/upload` – upload historical project data via CSV.
- `POST /api/learn/train` – train baseline model predicting unit-cost multipliers.
- `POST /api/learn/infer` – predict multipliers for a project or feature set.

## Tests
Run `pytest` to execute the test suite.
