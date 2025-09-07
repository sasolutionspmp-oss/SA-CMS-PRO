"""In-memory job utilities."""
from dataclasses import dataclass
from typing import Any, Callable, List


@dataclass
class Job:
    func: Callable[..., Any]
    args: tuple
    kwargs: dict


def queue_job(job: Job, jobs: List[Job]) -> None:
    jobs.append(job)


def run_jobs(jobs: List[Job]) -> List[Any]:
    results = []
    while jobs:
        job = jobs.pop(0)
        results.append(job.func(*job.args, **job.kwargs))
    return results
