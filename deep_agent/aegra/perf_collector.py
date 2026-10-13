"""In-memory performance metrics collector for the baseline dashboard.

Stores raw duration values in bounded deques so the ``/perf/metrics``
endpoint can compute percentiles on demand without depending on the
OTEL histogram bucket boundaries.
"""

from __future__ import annotations

import datetime
import statistics
import threading
import time
from collections import deque
from typing import Any

_MAX_SAMPLES = 2000
_MAX_RECENT_REQUESTS = 50

_collector: PerfCollector | None = None
_lock = threading.Lock()


def _classify_prompt_length(token_count: int) -> str:
    if token_count < 100:
        return "short"
    if token_count <= 500:
        return "medium"
    return "long"


class _Metric:
    """Thread-safe bounded sample buffer with percentile computation."""

    __slots__ = ("_samples", "_lock")

    def __init__(self, maxlen: int = _MAX_SAMPLES) -> None:
        self._samples: deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, value: float) -> None:
        with self._lock:
            self._samples.append(value)

    def percentiles(self) -> dict[str, float]:
        with self._lock:
            if not self._samples:
                return {
                    "p50": 0.0,
                    "p75": 0.0,
                    "p95": 0.0,
                    "p99": 0.0,
                    "count": 0,
                    "avg": 0.0,
                }
            data = sorted(self._samples)
        n = len(data)
        return {
            "p50": data[int(n * 0.50)] if n > 0 else 0.0,
            "p75": data[min(int(n * 0.75), n - 1)] if n > 0 else 0.0,
            "p95": data[min(int(n * 0.95), n - 1)] if n > 0 else 0.0,
            "p99": data[min(int(n * 0.99), n - 1)] if n > 0 else 0.0,
            "count": n,
            "avg": statistics.mean(data),
        }


class _Counter:
    """Thread-safe counter."""

    __slots__ = ("_value", "_lock")

    def __init__(self) -> None:
        self._value: int = 0
        self._lock = threading.Lock()

    def inc(self, n: int = 1) -> None:
        with self._lock:
            self._value += n

    def dec(self, n: int = 1) -> None:
        with self._lock:
            self._value -= n

    @property
    def value(self) -> int:
        return self._value


class _RateTracker:
    """Tracks events per second over a sliding window."""

    __slots__ = ("_timestamps", "_lock", "_window")

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._window = window_seconds

    def tick(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._timestamps.append(now)
            cutoff = now - self._window
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

    def rate_per_second(self) -> float:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            count = len(self._timestamps)
        if count == 0:
            return 0.0
        return round(count / self._window, 2)


def _resource_snapshot() -> dict[str, Any]:
    """Return CPU and memory usage for the current process."""
    try:
        import psutil

        proc = psutil.Process()
        mem = proc.memory_info()
        return {
            "cpu_percent": proc.cpu_percent(interval=None),
            "memory_rss_mb": round(mem.rss / (1024 * 1024), 1),
            "memory_heap_mb": round(mem.vms / (1024 * 1024), 1),
        }
    except (ImportError, Exception):
        import resource as res

        rusage = res.getrusage(res.RUSAGE_SELF)
        rss_mb = rusage.ru_maxrss / 1024
        import sys

        if sys.platform == "darwin":
            rss_mb = rusage.ru_maxrss / (1024 * 1024)
        return {
            "cpu_percent": None,
            "memory_rss_mb": round(rss_mb, 1),
            "memory_heap_mb": None,
        }


def _pct_to_ttft_dict(pct: dict[str, float]) -> dict[str, Any]:
    return {
        "p50_ms": round(pct["p50"], 1),
        "p75_ms": round(pct["p75"], 1),
        "p95_ms": round(pct["p95"], 1),
        "p99_ms": round(pct["p99"], 1),
        "samples": pct["count"],
    }


class PerfCollector:
    """Singleton collector for performance baseline metrics."""

    def _resolve_service_name(self) -> str:
        try:
            import yaml

            with open("config/agent/runtime/agent.yaml") as f:
                cfg = yaml.safe_load(f)
            if cfg and cfg.get("name"):
                return str(cfg["name"])
        except Exception:
            pass
        import os

        return os.environ.get("OTEL_SERVICE_NAME", "template-agent")

    def __init__(self) -> None:
        """Initialise metric buffers and counters."""
        self._start_time = time.monotonic()

        self.ttft_e2e = _Metric()
        self.ttft_e2e_by_bucket: dict[str, _Metric] = {
            "short": _Metric(),
            "medium": _Metric(),
            "long": _Metric(),
        }
        self.ttft_llm = _Metric()

        self.span_metrics: dict[str, _Metric] = {}
        self._span_lock = threading.Lock()

        self.conversations_started = _Counter()
        self.conversations_completed = _Counter()
        self.conversations_active = _Counter()
        self.messages_sent = _Counter()
        self.streams_active = _Counter()
        self.stream_errors = _Counter()
        self.stream_durations = _Metric()

        self.total_requests = _Counter()
        self.errors_by_type: dict[str, _Counter] = {}
        self._error_lock = threading.Lock()

        self.request_rate = _RateTracker()
        self.token_rate = _RateTracker()

        self._recent_requests: deque[dict[str, Any]] = deque(
            maxlen=_MAX_RECENT_REQUESTS
        )
        self._recent_lock = threading.Lock()
        self._pending_request: dict[str, dict[str, Any]] = {}
        self._pending_lock = threading.Lock()

    def record_span(self, name: str, duration_s: float) -> None:
        """Store a span duration sample."""
        with self._span_lock:
            if name not in self.span_metrics:
                self.span_metrics[name] = _Metric()
        self.span_metrics[name].record(duration_s * 1000)

    def record_ttft_e2e(self, duration_s: float, *, token_count: int = 0) -> None:
        """Record an end-to-end TTFT sample."""
        ms = duration_s * 1000
        self.ttft_e2e.record(ms)
        if token_count > 0:
            bucket = _classify_prompt_length(token_count)
            self.ttft_e2e_by_bucket[bucket].record(ms)

    def record_ttft_llm(self, duration_s: float) -> None:
        """Record an LLM-only TTFT sample."""
        self.ttft_llm.record(duration_s * 1000)

    def record_error(self, error_type: str = "unknown") -> None:
        """Increment error counters by type."""
        self.stream_errors.inc()
        with self._error_lock:
            if error_type not in self.errors_by_type:
                self.errors_by_type[error_type] = _Counter()
        self.errors_by_type[error_type].inc()

    def record_request(self) -> None:
        """Count a new request and tick the rate tracker."""
        self.total_requests.inc()
        self.request_rate.tick()

    def begin_request(self, *, trace_id: str = "", thread_id: str = "") -> float:
        """Start tracking a request; returns monotonic timestamp."""
        mono = time.monotonic()
        req: dict[str, Any] = {
            "trace_id": trace_id,
            "thread_id": thread_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "start_mono": mono,
            "ttft_ms": 0.0,
            "spans": [],
            "status": "ok",
        }
        key = trace_id or str(id(req))
        with self._pending_lock:
            self._pending_request[key] = req
        return mono

    def finish_request(
        self,
        start_mono: float,
        *,
        trace_id: str = "",
        ttft_ms: float = 0.0,
        status: str = "ok",
    ) -> None:
        """Finalise a tracked request and add it to the recent list."""
        duration_ms = (time.monotonic() - start_mono) * 1000
        key = trace_id
        with self._pending_lock:
            req = self._pending_request.pop(key, None)
        if req is None:
            req = {
                "trace_id": trace_id,
                "thread_id": "",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "spans": [],
            }
        req["total_duration_ms"] = round(duration_ms, 1)
        req["ttft_ms"] = round(ttft_ms, 1)
        req["status"] = status
        req.pop("start_mono", None)
        with self._recent_lock:
            self._recent_requests.append(req)

    def _generate_insights(self) -> list[dict[str, Any]]:
        insights: list[dict[str, Any]] = []
        graph_build = self.span_metrics.get("graph.build")
        if graph_build:
            pct = graph_build.percentiles()
            if pct["p95"] > 500:
                insights.append(
                    {
                        "level": "warn",
                        "message": f"Graph build is slow (p95: {round(pct['p95'])}ms). Consider enabling graph caching.",
                        "metric": "graph.build.p95",
                        "value": round(pct["p95"], 1),
                    }
                )

        llm_pct = self.ttft_llm.percentiles()
        if llm_pct["count"] > 0 and llm_pct["p50"] > 3000:
            insights.append(
                {
                    "level": "warn",
                    "message": f"LLM response time is high (p50: {round(llm_pct['p50'] / 1000, 1)}s). Check model provider latency.",
                    "metric": "ttft.llm.p50",
                    "value": round(llm_pct["p50"], 1),
                }
            )

        mcp = self.span_metrics.get("mcp.server_connect")
        if mcp:
            pct = mcp.percentiles()
            if pct["p95"] > 100:
                insights.append(
                    {
                        "level": "warn",
                        "message": f"MCP server connections are slow (p95: {round(pct['p95'])}ms). Check network latency.",
                        "metric": "mcp.connect.p95",
                        "value": round(pct["p95"], 1),
                    }
                )

        total_req = self.total_requests.value
        total_err = self.stream_errors.value
        if total_req > 0:
            err_rate = (total_err / total_req) * 100
            if err_rate > 1:
                insights.append(
                    {
                        "level": "critical",
                        "message": f"Error rate is above SLO threshold ({err_rate:.1f}%).",
                        "metric": "error_rate",
                        "value": round(err_rate, 2),
                    }
                )

        res = _resource_snapshot()
        rss = res.get("memory_rss_mb", 0) or 0
        if rss > 500:
            insights.append(
                {
                    "level": "warn",
                    "message": f"High memory usage ({round(rss)}MB). Check for memory leaks.",
                    "metric": "memory_rss_mb",
                    "value": round(rss, 1),
                }
            )

        cpu = res.get("cpu_percent")
        if cpu is not None and cpu > 80:
            insights.append(
                {
                    "level": "warn",
                    "message": f"High CPU usage ({round(cpu)}%). Check for compute-bound bottlenecks.",
                    "metric": "cpu_percent",
                    "value": round(cpu, 1),
                }
            )

        if not insights:
            insights.append(
                {
                    "level": "info",
                    "message": "All performance metrics are within normal ranges.",
                    "metric": "status",
                    "value": 0,
                }
            )

        return insights

    def snapshot(self) -> dict[str, Any]:
        """Build the full metrics response for /perf/metrics."""
        ttft_e2e = self.ttft_e2e.percentiles()
        ttft_llm = self.ttft_llm.percentiles()
        stream_pct = self.stream_durations.percentiles()

        ttft_by_prompt_length = {}
        for bucket, metric in self.ttft_e2e_by_bucket.items():
            pct = metric.percentiles()
            if pct["count"] > 0:
                ttft_by_prompt_length[bucket] = _pct_to_ttft_dict(pct)

        spans = []
        total_avg = 0.0
        with self._span_lock:
            names = list(self.span_metrics.keys())
        for name in names:
            pct = self.span_metrics[name].percentiles()
            avg = round(pct["avg"], 1)
            total_avg += avg
            spans.append(
                {
                    "name": name,
                    "label": name,
                    "avg_ms": avg,
                    "p50_ms": round(pct["p50"], 1),
                    "p75_ms": round(pct["p75"], 1),
                    "p95_ms": round(pct["p95"], 1),
                    "p99_ms": round(pct["p99"], 1),
                    "count": pct["count"],
                    "color": "",
                    "pct_of_total": 0.0,
                }
            )
        if total_avg > 0:
            for s in spans:
                s["pct_of_total"] = round(float(s["avg_ms"]) / total_avg * 100, 1)

        total_req = self.total_requests.value
        total_errors = self.stream_errors.value
        with self._error_lock:
            errors_by_type = {k: v.value for k, v in self.errors_by_type.items()}

        with self._recent_lock:
            recent = list(self._recent_requests)

        import os

        jaeger_url = os.environ.get("JAEGER_UI_URL", "http://localhost:16686")

        return {
            "ttft": {
                "e2e": _pct_to_ttft_dict(ttft_e2e),
                "llm_only": _pct_to_ttft_dict(ttft_llm),
                "by_prompt_length": ttft_by_prompt_length,
            },
            "throughput": {
                "conversations_started": self.conversations_started.value,
                "conversations_completed": self.conversations_completed.value,
                "conversations_active": self.conversations_active.value,
                "messages_sent": self.messages_sent.value,
                "streams_active": self.streams_active.value,
                "stream_errors": total_errors,
                "avg_stream_duration_ms": round(stream_pct["avg"], 1),
                "requests_per_second": self.request_rate.rate_per_second(),
                "tokens_per_second": self.token_rate.rate_per_second(),
            },
            "error_budget": {
                "total_requests": total_req,
                "errors_by_type": errors_by_type,
                "error_rate_pct": round(
                    (total_errors / total_req * 100) if total_req > 0 else 0.0, 2
                ),
            },
            "resources": _resource_snapshot(),
            "spans": spans,
            "insights": self._generate_insights(),
            "recent_requests": recent[-_MAX_RECENT_REQUESTS:],
            "jaeger_url": jaeger_url,
            "service_name": self._resolve_service_name(),
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
        }


def get_collector() -> PerfCollector:
    """Return the global PerfCollector singleton."""
    global _collector
    if _collector is None:
        with _lock:
            if _collector is None:
                _collector = PerfCollector()
    return _collector


_TRACKED_SPANS = frozenset(
    {
        "startup.cold",
        "auth.token_refresh",
        "mcp.tool_discovery",
        "mcp.server_connect",
        "graph.personalization",
        "model.create",
        "graph.build",
        "pii.scrub",
        "personalization.load",
        "graph.mcp_tools",
        "graph.streaming",
    }
)


class PerfSpanProcessor:
    """OTEL SpanProcessor that records durations of tracked spans."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        pass

    def _on_ending(self, span: Any) -> None:
        pass

    def on_end(self, span: Any) -> None:
        name = span.name
        if name not in _TRACKED_SPANS:
            return
        start_ns = span.start_time
        end_ns = span.end_time
        if start_ns and end_ns:
            duration_s = (end_ns - start_ns) / 1e9
            get_collector().record_span(name, duration_s)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
