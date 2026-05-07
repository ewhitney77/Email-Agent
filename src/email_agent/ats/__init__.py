"""ATS clients. Each module exposes `fetch_jobs(handle, **kwargs) -> list[JobPosting]`."""

from . import ashby, greenhouse, lever, workday

__all__ = ["ashby", "greenhouse", "lever", "workday"]
