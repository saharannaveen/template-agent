"""Workflow state store backed by Redis for persistence across restarts.

Falls back to in-memory storage if Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MODULE_WORKFLOWS: dict[str, dict[str, Any]] = {}
_MODULE_LOCK: asyncio.Lock | None = None


class WorkflowStore:
    """Workflow store with Redis persistence and in-memory fallback."""

    def __init__(self) -> None:
        global _MODULE_LOCK
        self._local = _MODULE_WORKFLOWS
        if _MODULE_LOCK is None:
            _MODULE_LOCK = asyncio.Lock()
        self._lock = _MODULE_LOCK
        self._redis = None
        self._redis_key_prefix = "loop-eng:workflows:"

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            return self._redis
        except Exception:
            self._redis = None
            return None

    def _serialize(self, wf: dict) -> str:
        d = dict(wf)
        if isinstance(d.get("started_at"), datetime):
            d["started_at"] = d["started_at"].isoformat()
        return json.dumps(d)

    def _deserialize(self, raw: str) -> dict:
        d = json.loads(raw)
        if "started_at" in d and isinstance(d["started_at"], str):
            d["started_at"] = datetime.fromisoformat(d["started_at"])
        return d

    async def register(self, workflow_id: str, task_name: str, user_id: str, thread_id: str | None = None) -> None:
        wf = {
            "workflow_id": workflow_id,
            "task_name": task_name,
            "user_id": user_id,
            "thread_id": thread_id,
            "status": "running",
            "current_phase": "initializing",
            "cost": 0.0,
            "iterations": 0,
            "started_at": datetime.now(timezone.utc),
            "decisions": [],
            "artifacts": [],
        }
        async with self._lock:
            self._local[workflow_id] = wf
        r = await self._get_redis()
        if r:
            try:
                await r.set(f"{self._redis_key_prefix}{workflow_id}", self._serialize(wf), ex=86400)
                # Store thread → workflow mapping
                if thread_id:
                    await r.set(f"loop-engineering:thread-workflow:{thread_id}", workflow_id, ex=86400)
            except Exception:
                pass

    async def update_status(self, workflow_id: str, status: str, phase: str, cost: float, iterations: int | None = None) -> None:
        async with self._lock:
            if workflow_id in self._local:
                self._local[workflow_id]["status"] = status
                self._local[workflow_id]["current_phase"] = phase
                self._local[workflow_id]["cost"] = cost
                if iterations is not None:
                    self._local[workflow_id]["iterations"] = iterations
                wf = self._local[workflow_id]
            else:
                return
        r = await self._get_redis()
        if r:
            try:
                await r.set(f"{self._redis_key_prefix}{workflow_id}", self._serialize(wf), ex=86400)
            except Exception:
                pass

    async def get(self, workflow_id: str) -> dict[str, Any] | None:
        async with self._lock:
            if workflow_id in self._local:
                return self._local[workflow_id]
        r = await self._get_redis()
        if r:
            try:
                raw = await r.get(f"{self._redis_key_prefix}{workflow_id}")
                if raw:
                    wf = self._deserialize(raw)
                    async with self._lock:
                        self._local[workflow_id] = wf
                    return wf
            except Exception:
                pass
        return None

    async def get_all(self, user_id: str | None = None) -> list[dict[str, Any]]:
        # Try Redis first for full list
        r = await self._get_redis()
        if r:
            try:
                keys = await r.keys(f"{self._redis_key_prefix}*")
                workflows = []
                for key in keys:
                    raw = await r.get(key)
                    if raw:
                        wf = self._deserialize(raw)
                        if user_id is None or wf.get("user_id") == user_id:
                            workflows.append(wf)
                        async with self._lock:
                            self._local[wf["workflow_id"]] = wf
                workflows.sort(key=lambda w: w.get("started_at", datetime.min), reverse=True)
                return workflows
            except Exception:
                pass
        # Fallback to local
        async with self._lock:
            workflows = list(self._local.values())
            if user_id:
                workflows = [w for w in workflows if w.get("user_id") == user_id]
            workflows.sort(key=lambda w: w.get("started_at", datetime.min), reverse=True)
            return workflows

    async def get_by_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Get active workflow for a thread.

        Args:
            thread_id: LangGraph thread ID

        Returns:
            Workflow dict if found, None otherwise
        """
        r = await self._get_redis()
        if r:
            try:
                workflow_id = await r.get(f"loop-engineering:thread-workflow:{thread_id}")
                if workflow_id:
                    return await self.get(workflow_id)
            except Exception:
                pass
        return None

    async def clear(self) -> None:
        async with self._lock:
            self._local.clear()
        r = await self._get_redis()
        if r:
            try:
                keys = await r.keys(f"{self._redis_key_prefix}*")
                if keys:
                    await r.delete(*keys)
                # Clear thread mappings
                thread_keys = await r.keys("loop-engineering:thread-workflow:*")
                if thread_keys:
                    await r.delete(*thread_keys)
            except Exception:
                pass
