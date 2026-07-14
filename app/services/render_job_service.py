"""
Lightweight local render job queue for single-user SacredClips.

Jobs run in a background thread pool. Status is persisted to outputs/render_jobs.json.
Completed/failed job metadata survives backend restarts.
Running/queued jobs interrupted by restart are marked failed on load.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from .. import config

ProgressCallback = Callable[[str, float], None]

JobStatus = Literal["queued", "running", "completed", "failed"]
JobType = Literal["ai_generate", "manual_video", "render_subtitles", "regenerate"]

_lock = threading.RLock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sacredclips-render")
_jobs: dict[str, dict[str, Any]] = {}

JOBS_FILE = Path(config.BASE_OUTPUT_DIR).resolve() / "render_jobs.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jobs_from_disk() -> None:
    global _jobs
    if not JOBS_FILE.is_file():
        _jobs = {}
        return
    try:
        raw = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            _jobs = {}
            return
        restored: dict[str, dict[str, Any]] = {}
        for job_id, rec in raw.items():
            if not isinstance(rec, dict):
                continue
            status = rec.get("status")
            if status in ("queued", "running"):
                rec = {
                    **rec,
                    "status": "failed",
                    "stage": "interrupted",
                    "error": "Backend restarted while this job was in progress.",
                    "updated_at": _utc_now(),
                }
            restored[str(job_id)] = rec
        _jobs = restored
    except Exception:
        _jobs = {}


def _persist_jobs() -> None:
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_FILE.with_suffix(".json.tmp")
    with _lock:
        payload = dict(_jobs)
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(JOBS_FILE)


def _update_job_unlocked(job_id: str, **fields: Any) -> None:
    rec = _jobs.get(job_id)
    if not rec:
        return
    rec.update(fields)
    rec["updated_at"] = _utc_now()
    _jobs[job_id] = rec


def init_render_jobs() -> None:
    """Call once at app startup."""
    _load_jobs_from_disk()
    _persist_jobs()


def create_job(job_type: JobType) -> str:
    job_id = uuid.uuid4().hex
    now = _utc_now()
    rec = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "error": None,
        "result": None,
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        _jobs[job_id] = rec
    _persist_jobs()
    return job_id


def update_progress(job_id: str, stage: str, progress: float) -> None:
    with _lock:
        _update_job_unlocked(
            job_id,
            status="running",
            stage=stage,
            progress=max(0.0, min(100.0, float(progress))),
        )
    _persist_jobs()


def complete_job(job_id: str, result: Any) -> None:
    with _lock:
        _update_job_unlocked(
            job_id,
            status="completed",
            stage="completed",
            progress=100.0,
            error=None,
            result=result,
        )
    _persist_jobs()


def fail_job(job_id: str, error: str) -> None:
    with _lock:
        _update_job_unlocked(
            job_id,
            status="failed",
            stage="failed",
            error=error,
        )
    _persist_jobs()


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        rec = _jobs.get(job_id)
        return dict(rec) if rec else None


def list_latest_jobs(limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        items = list(_jobs.values())
    items.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return [dict(r) for r in items[: max(1, limit)]]


def submit_job(job_id: str, fn: Callable[[ProgressCallback], Any]) -> None:
    def worker() -> None:
        def progress(stage: str, pct: float) -> None:
            update_progress(job_id, stage, pct)

        try:
            update_progress(job_id, "preparing", 5.0)
            result = fn(progress)
            if hasattr(result, "model_dump"):
                payload = result.model_dump()
            elif isinstance(result, dict):
                payload = result
            else:
                payload = result
            complete_job(job_id, payload)
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"[render-job {job_id}] failed: {exc}\n{tb}")
            fail_job(job_id, str(exc) or exc.__class__.__name__)

    _executor.submit(worker)
