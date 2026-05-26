"""Progress for long-running PDF comparisons (polled by the frontend).

In-memory state is updated for the worker process; the same values are written to
``comparisons.progress_*`` so GET /progress works when another Uvicorn worker or
process handles the request (in-memory alone would show 0%% / "Starting…").
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}

_log = logging.getLogger(__name__)


def _persist_progress_row(comparison_id: str, percent: int, message: str) -> None:
    try:
        from database_connection import SessionLocal
        from models.database import Comparison

        p = max(0, min(100, int(percent)))
        db = SessionLocal()
        try:
            row = db.query(Comparison).filter(Comparison.id == comparison_id).first()
            if row:
                row.progress_percent = p
                row.progress_message = message or ""
                db.commit()
        finally:
            db.close()
    except Exception as e:
        _log.warning("persist progress failed for %s: %s", comparison_id, e, exc_info=True)


def set_progress(comparison_id: str, percent: int, message: str = "") -> None:
    p = max(0, min(100, int(percent)))
    now = time.time()
    with _lock:
        cur = _state.get(comparison_id, {})
        # Track start time on first progress update
        if "start_time" not in cur:
            cur["start_time"] = now
        start_time = cur.get("start_time", now)
        msg = message or cur.get("message", "")
        
        # Calculate ETA with smoothing to handle non-linear progress
        eta_msg = ""
        if p > 10 and p < 95:  # Only show ETA in meaningful range
            elapsed = now - start_time
            # Use previous ETA estimates to smooth out jumps
            prev_eta = cur.get("last_eta", None)
            estimated_total = (elapsed / p) * 100
            remaining = estimated_total - elapsed
            
            # Smooth the estimate with previous value (70% old, 30% new)
            if prev_eta is not None and remaining > 0:
                remaining = prev_eta * 0.7 + remaining * 0.3
            
            if remaining > 0:
                cur["last_eta"] = remaining
                mins = int(remaining / 60)
                secs = int(remaining % 60)
                if mins > 0:
                    eta_msg = f" (ETA: {mins}m {secs}s)"
                else:
                    eta_msg = f" (ETA: {secs}s)"
        
        full_msg = msg + eta_msg
        cur.update({"percent": p, "message": full_msg, "done": False, "error": None})
        _state[comparison_id] = cur
    _persist_progress_row(comparison_id, p, full_msg)


def mark_done(comparison_id: str) -> None:
    with _lock:
        cur = _state.get(comparison_id, {})
        cur.update({"percent": 100, "done": True, "error": None})
        _state[comparison_id] = cur
    _persist_progress_row(comparison_id, 100, "Complete")


def mark_error(comparison_id: str, err: str) -> None:
    with _lock:
        pct = _state.get(comparison_id, {}).get("percent", 0)
        _state[comparison_id] = {
            "percent": pct,
            "message": "Failed",
            "done": True,
            "error": err[:2000],
        }
    _persist_progress_row(comparison_id, pct, "Failed")


def snapshot(comparison_id: str) -> dict[str, Any] | None:
    with _lock:
        s = _state.get(comparison_id)
        return dict(s) if s else None


def clear(comparison_id: str) -> None:
    with _lock:
        _state.pop(comparison_id, None)


def make_callback(comparison_id: str) -> Callable[[int, str], None]:
    def cb(percent: int, message: str = "") -> None:
        set_progress(comparison_id, percent, message)

    return cb
