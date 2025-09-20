# API Reference

The FastAPI service exposes interactive documentation at `/docs` (Swagger UI) and `/redoc`. The tables below summarise the primary endpoint groups registered in `apps/api/main.py`.

## Authentication (`auth`)
| Method | Path | Description |
| --- | --- | --- |
| POST | `/auth/login` | Exchange username/password (optional `org_id`) for access/refresh tokens. |
| POST | `/auth/refresh` | Issue a fresh access token from a valid refresh token. |

## Account (`account`)
| Method | Path | Description |
| --- | --- | --- |
| GET | `/me` | Return the current user profile, roles, and active organization summary. |

## Bootstrap (`bootstrap`)
| Method | Path | Description |
| --- | --- | --- |
| GET | `/bootstrap/context` | Bundle user, organization, project, and dashboard seed data. |

## Health (`health`)
| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Verify database, Redis/queue, and storage connectivity. |

## Intake (`intake`)
| Method | Path | Description |
| --- | --- | --- |
| POST | `/intake/launch` | Kick off a new intake run for a project. |
| GET | `/intake/status` | Fetch run progress including per-file breakdown. |

## Jobs (`jobs`)
| Method | Path | Description |
| --- | --- | --- |
| POST | `/jobs/submit` | Queue a workflow job (ingest, parsing, exports, etc.). |
| GET | `/jobs/{job_id}/status` | Poll job status/progress. |
| GET | `/jobs/stream` | Server-sent events stream of job updates. |

## CRM (`crm`)
| Method | Path | Description |
| --- | --- | --- |
| GET | `/crm/opportunities` | List opportunities grouped by pipeline lane. |
| PATCH | `/crm/opportunities/{id}` | Update lane/metadata for an opportunity card. |

## Estimator (`estimator`)
| Method | Path | Description |
| --- | --- | --- |
| GET | `/estimator/projects/{id}` | Fetch estimator grid data for the given project. |
| POST | `/estimator/projects/{id}/exports` | Trigger bid package exports. |

## Export (`export`)
| Method | Path | Description |
| --- | --- | --- |
| GET | `/export/estimate.{fmt}` | Download estimator exports (`pdf`, `docx`, `xlsx`). |

## Workflows (`workflows`)
| Method | Path | Description |
| --- | --- | --- |
| POST | `/workflows/full` | Execute the intake → scope → estimate → compliance → bid → CRM → contract → PM orchestration. |

Refer to `apps/api/schemas` for request/response models and `packages/core/services` for orchestration details. When introducing new endpoints, add their tag metadata to `apps/api/main.py` so the OpenAPI explorer stays organised.
