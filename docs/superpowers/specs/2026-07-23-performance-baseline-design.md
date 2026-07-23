# Template-Agent Performance Baseline

**Date:** 2026-07-23
**Branch:** `feat/template-agent-baseline-performance`
**Provider scope:** Gemini (Vertex AI) only
**Approach:** Wire-First (Approach A) — wire existing OTEL metrics, then validate with Locust load tests

---

## 1. OTEL Metrics Wiring

Wire the 8 existing unwired `record_*` functions from `otel.py` into runtime code paths.

### Existing metrics → wire points

| Metric | Wire Point | File |
|--------|-----------|------|
| `record_conversation_started/completed` | Graph factory entry/exit | `deep_agent/aegra/graph.py` |
| `record_stream_started` + `record_first_token` | `TokenEventHandler` first token callback | `deep_agent/aegra/streaming/handlers.py` |
| `record_stream_completed/error` | Stream end/exception in streaming handlers | `deep_agent/aegra/streaming/handlers.py` |
| `record_message_sent` | Message ingress at graph state entry (human message arrival) | `deep_agent/aegra/graph.py` |
| `record_graph_built` | Wrap `create_deep_agent()` call and cache hit/miss paths | `deep_agent/aegra/graph.py` |

### New: LLM-only TTFT metric

Add `llm_time_to_first_token_seconds` histogram to `MetricsContainer` using the existing `TTFT_BUCKETS`.

Implement as a LangChain callback handler that captures the delta between `on_llm_start` and `on_llm_new_token`. Register via the existing `register_configure_hook` pattern in `telemetry.py`.

This isolates Gemini provider latency from graph/platform overhead.

### New: OTEL spans for request waterfall

Instrument each phase using `get_tracer()` from `otel.py`:

| Span Name | What it covers |
|-----------|---------------|
| `graph.build` | Graph factory total (cache check → `create_deep_agent`) |
| `graph.personalization` | Personalization DB lookup + prompt injection |
| `graph.mcp_tools` | MCP tool discovery and wrapping |
| `graph.llm_call` | LLM invocation (via callback handler) |
| `graph.streaming` | Full SSE stream duration |

---

## 2. Hot Path Profiling Infrastructure

### Discovery (one-time, flame graphs)

Use `py-spy` to capture flame graphs during Locust load runs:

- **CPU flame graph:** `py-spy record --pid <PID> --format speedscope -o flamegraph-cpu.json` during a 60s Locust burst at 100 concurrent users. Identifies CPU-bound hot paths (serialization, PII scrubbing, graph compilation).
- **Wall-clock flame graph:** `py-spy record --pid <PID> --idle --format speedscope` captures I/O wait (LLM calls, DB queries, Redis, MCP connections).

### Codification (permanent OTEL spans)

Candidate hot paths based on architecture review:

| Suspected Hot Path | Why | Span Name |
|---|---|---|
| `get_mcp_tools()` | HTTP calls to MCP servers per-request | `mcp.tool_discovery` |
| `refresh_access_token()` | Token refresh before MCP calls | `auth.token_refresh` |
| Personalization DB query | `list_top_memories()` + `list_rules()` | `personalization.load` |
| Graph cache miss rebuild | `create_deep_agent()` with full middleware/tool resolution | `graph.compile` |
| PII scrubbing | `PIIAwareRunnable` wrapping `astream`/`astream_events` | `pii.scrub` |
| Model cache miss | `get_or_create_model_from_spec()` first-call per provider | `model.create` |
| `_ensure_startup()` | First-request cold start (DB tables, cache warming, OTEL init) | `startup.cold` |

### Output

- Flame graph files (speedscope JSON) committed to `docs/performance/flamegraphs/`
- Markdown report mapping each hot path to measured p50/p95 timing and optimization recommendations

---

## 3. Locust Load Testing

### Test structure

```
tests/load/
├── locustfile.py          # Main Locust config + task definitions
├── scenarios/
│   ├── single_turn.py     # Single message → response
│   └── multi_turn.py      # 3-5 turn conversation
├── graph_benchmark.py     # In-process direct graph invocation (no HTTP)
├── payloads/
│   └── prompts.json       # Realistic prompt corpus (varied lengths)
└── reports/               # Generated baseline reports (gitignored)
```

### Scenario weighting

70% single-turn, 30% multi-turn.

### Two test layers

**Layer 1 — SSE endpoint (e2e):** Locust `HttpUser` hits the Aegra SSE streaming endpoint. Measures:
- TTFT (request sent → first `data:` event with content)
- Total response time (request → stream end)
- Tokens per second (token count / stream duration)
- Error rate by type (timeout, 5xx, stream disconnect)

**Layer 2 — Direct graph invocation (in-process):** Custom Locust `User` that calls `agent(mock_runtime)` → `graph.astream()` directly via asyncio. Measures:
- LLM-only TTFT (via callback handler)
- Graph build time (cache hit vs miss)
- Per-node execution time

### Load profiles

| Profile | Concurrent Users | Duration | Ramp-up | Purpose |
|---------|-----------------|----------|---------|---------|
| Smoke | 5 | 2 min | 10s | Validate setup |
| Baseline | 50 | 10 min | 60s | Steady-state baseline |
| Stress | 100 → 200 | 15 min | 120s | Find breaking point |
| Soak | 50 | 30 min | 60s | Memory leaks, GC pressure |

### Prompt corpus

10-15 realistic prompts of varied lengths (short question, medium instruction, long multi-step task) in `payloads/prompts.json`. No real user data.

---

## 4. Baseline Report & Success Criteria

### Baseline report

Generated after the first full Locust run, saved to `docs/performance/baseline-report.md`:

- **Gemini TTFT baseline** — p50, p75, p95, p99 for both e2e and LLM-only, broken down by prompt length bucket (short/medium/long)
- **Throughput** — requests/sec at each concurrency level, tokens/sec streaming rate
- **Hot path breakdown** — waterfall showing where time goes: graph build, personalization, MCP tool init, LLM wait, PII scrub, streaming overhead. Percentage of total request time per phase.
- **Error budget** — error rate by type at each load level
- **Resource utilization** — CPU, memory, GC pauses during each load profile (captured via py-spy + system metrics)
- **Flame graphs** — embedded speedscope links for CPU and wall-clock captures

### Success criteria

| Criterion | Definition |
|-----------|-----------|
| OTEL metrics flowing | All `record_*` functions wired, verified via `/api/metrics` endpoint returning non-zero values under load |
| TTFT measurable at both layers | e2e TTFT and LLM-only TTFT both captured with p50/p95 numbers for Gemini |
| Hot paths identified | Top 5 hot paths documented with measured timings, each has a permanent OTEL span |
| Locust reproducible | `locust -f tests/load/locustfile.py` runs all 4 profiles against a deployed instance |
| Baseline committed | Report with numbers, flame graphs, and recommendations checked into `docs/performance/` |

### Not in scope

- Actual performance tuning (next step after baseline)
- Changes to `deepagents` library internals
- Non-Gemini providers (Claude, vLLM)

---

## 5. Dependencies

### New dependencies

| Package | Purpose |
|---------|---------|
| `locust` | Load testing framework |
| `py-spy` | Flame graph profiling (dev/CI only, not a Python dep) |

### Existing dependencies leveraged

- `opentelemetry-*` — already installed, metrics infrastructure built
- `langfuse` — LLM tracing already wired via `telemetry.py`
- `langchain-google-genai` — Gemini provider already configured
