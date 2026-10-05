"""Performance baseline metrics and baseline persistence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deep_agent.aegra.perf_collector import get_collector

router = APIRouter(tags=["performance"])


@router.get("/perf/metrics")
def perf_metrics() -> dict:
    """Return current performance baseline metrics for the UI dashboard."""
    return get_collector().snapshot()


@router.get("/perf/traces")
def perf_traces() -> dict:
    """Return recent request traces for the trace explorer."""
    snap = get_collector().snapshot()
    return {
        "traces": snap.get("recent_requests", []),
        "jaeger_url": snap.get("jaeger_url", "http://localhost:16686"),
    }


class SaveBaselineRequest(BaseModel):
    label: str


@router.post("/perf/baselines")
async def save_baseline(body: SaveBaselineRequest) -> dict:
    """Save the current metrics snapshot as a named baseline."""
    from deep_agent.aegra.perf_storage import save_baseline as _save

    snapshot = get_collector().snapshot()
    baseline_id = await _save(body.label, snapshot)
    return {"id": baseline_id, "label": body.label}


@router.get("/perf/baselines")
async def list_baselines() -> dict:
    """List saved baselines."""
    from deep_agent.aegra.perf_storage import list_baselines as _list

    baselines = await _list()
    return {"baselines": baselines}


@router.get("/perf/baselines/{baseline_id}")
async def get_baseline(baseline_id: int) -> dict:
    """Get a specific baseline by ID."""
    from deep_agent.aegra.perf_storage import get_baseline as _get

    result = await _get(baseline_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return result


@router.delete("/perf/baselines/{baseline_id}")
async def delete_baseline(baseline_id: int) -> dict:
    """Delete a baseline."""
    from deep_agent.aegra.perf_storage import delete_baseline as _delete

    deleted = await _delete(baseline_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return {"deleted": True}


@router.get("/perf/baselines/{baseline_id}/compare")
async def compare_baseline(baseline_id: int) -> dict:
    """Compare current metrics against a saved baseline."""
    from deep_agent.aegra.perf_storage import compare_baselines
    from deep_agent.aegra.perf_storage import get_baseline as _get

    saved = await _get(baseline_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Baseline not found")
    current = get_collector().snapshot()
    comparison = compare_baselines(current, saved["snapshot"])
    comparison["baseline_label"] = saved["label"]
    comparison["baseline_date"] = saved["created_at"]
    return comparison
