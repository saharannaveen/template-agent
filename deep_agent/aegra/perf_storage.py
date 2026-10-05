"""Persistence layer for performance baselines using Postgres."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from deep_agent.utils.pylogger import get_python_logger

logger = get_python_logger()

_DDL = """
CREATE TABLE IF NOT EXISTS perf_baselines (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    branch TEXT,
    commit_hash TEXT,
    snapshot JSONB NOT NULL
);
"""

_METRIC_KEYS = [
    ("ttft.e2e.p50_ms", "TTFT e2e p50", "ms", True),
    ("ttft.e2e.p95_ms", "TTFT e2e p95", "ms", True),
    ("ttft.llm_only.p50_ms", "TTFT LLM p50", "ms", True),
    ("ttft.llm_only.p95_ms", "TTFT LLM p95", "ms", True),
    ("throughput.conversations_started", "Conversations", "", False),
    ("throughput.stream_errors", "Stream errors", "", True),
    ("error_budget.error_rate_pct", "Error rate", "%", True),
]


def _nested_get(d: dict, dotted_key: str) -> Any:
    parts = dotted_key.split(".")
    cur: Any = d
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _git_info() -> tuple[str, str]:
    try:
        branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode()
            .strip()
        )
        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode()
            .strip()
        )
        return branch, commit
    except Exception:
        return "", ""


async def _pg_conn() -> Any:
    import psycopg

    from deep_agent.src.settings import settings

    return await psycopg.AsyncConnection.connect(settings.database_uri)


async def _ensure_table() -> None:
    async with await _pg_conn() as conn:
        await conn.set_autocommit(True)
        await conn.execute(_DDL)


async def save_baseline(label: str, snapshot: dict) -> int:
    """Persist a performance snapshot as a named baseline."""
    await _ensure_table()
    branch, commit = _git_info()
    async with await _pg_conn() as conn:
        cur = await conn.execute(
            "INSERT INTO perf_baselines (label, branch, commit_hash, snapshot) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (label, branch or None, commit or None, json.dumps(snapshot)),
        )
        row = await cur.fetchone()
        await conn.commit()
        return int(row[0])  # type: ignore[index]


async def list_baselines(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent baselines with summary stats."""
    await _ensure_table()
    async with await _pg_conn() as conn:
        cur = await conn.execute(
            "SELECT id, label, created_at, branch, commit_hash, snapshot "
            "FROM perf_baselines ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        rows = await cur.fetchall()
    result = []
    for row in rows:
        snap = row[5] if isinstance(row[5], dict) else json.loads(row[5])
        ttft_p50 = _nested_get(snap, "ttft.e2e.p50_ms") or 0
        convos = _nested_get(snap, "throughput.conversations_started") or 0
        result.append(
            {
                "id": row[0],
                "label": row[1],
                "created_at": row[2].isoformat() if row[2] else "",
                "branch": row[3] or "",
                "commit_hash": row[4] or "",
                "ttft_e2e_p50_ms": round(ttft_p50, 1),
                "conversations": convos,
            }
        )
    return result


async def get_baseline(baseline_id: int) -> dict[str, Any] | None:
    """Fetch a single baseline by id."""
    await _ensure_table()
    async with await _pg_conn() as conn:
        cur = await conn.execute(
            "SELECT id, label, created_at, branch, commit_hash, snapshot "
            "FROM perf_baselines WHERE id = %s",
            (baseline_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    snap = row[5] if isinstance(row[5], dict) else json.loads(row[5])
    return {
        "id": row[0],
        "label": row[1],
        "created_at": row[2].isoformat() if row[2] else "",
        "branch": row[3] or "",
        "commit_hash": row[4] or "",
        "snapshot": snap,
    }


async def delete_baseline(baseline_id: int) -> bool:
    """Remove a baseline by id."""
    await _ensure_table()
    async with await _pg_conn() as conn:
        cur = await conn.execute(
            "DELETE FROM perf_baselines WHERE id = %s", (baseline_id,)
        )
        await conn.commit()
        return bool(cur.rowcount and cur.rowcount > 0)


def compare_baselines(current: dict, baseline: dict) -> dict[str, Any]:
    """Compute per-metric deltas between two snapshots."""
    metrics = []
    for dotted_key, name, unit, lower_is_better in _METRIC_KEYS:
        cur_val = _nested_get(current, dotted_key)
        base_val = _nested_get(baseline, dotted_key)
        if cur_val is None or base_val is None:
            continue
        cur_val = float(cur_val)
        base_val = float(base_val)
        delta = cur_val - base_val
        delta_pct = (delta / base_val * 100) if base_val != 0 else 0.0
        threshold = 10.0
        if lower_is_better:
            if delta_pct > threshold:
                status = "regressed"
            elif delta_pct < -threshold:
                status = "improved"
            else:
                status = "unchanged"
        else:
            if delta_pct < -threshold:
                status = "regressed"
            elif delta_pct > threshold:
                status = "improved"
            else:
                status = "unchanged"
        metrics.append(
            {
                "name": name,
                "current": round(cur_val, 2),
                "baseline": round(base_val, 2),
                "delta": round(delta, 2),
                "delta_pct": round(delta_pct, 1),
                "status": status,
                "unit": unit,
            }
        )
    return {"metrics": metrics}
