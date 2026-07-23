# Performance Profiling Guide

This directory contains tools and documentation for profiling and benchmarking the template-agent.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| py-spy | >= 0.3 | `pip install py-spy` |
| Locust | >= 2.0 | `pip install locust` |
| Speedscope | N/A | https://www.speedscope.app/ (browser-based) |

You also need a running agent instance (local or in a pod) to profile against.

## Capturing Flame Graphs

### CPU Flame Graph

Records only on-CPU time (excludes I/O waits, sleeps, and network calls). Useful for finding compute-bound bottlenecks.

```bash
py-spy record \
  --pid <PID> \
  --format speedscope \
  -o flamegraphs/cpu.json \
  -- python -m deep_agent.src.main
```

To attach to an already-running process:

```bash
py-spy record \
  --pid $(pgrep -f "deep_agent") \
  --format speedscope \
  -o flamegraphs/cpu.json \
  --duration 60
```

### Wall-Clock Flame Graph

Records wall-clock time including I/O, network, and sleep. Useful for finding latency bottlenecks in async code where the CPU is idle waiting on external services.

```bash
py-spy record \
  --pid $(pgrep -f "deep_agent") \
  --idle \
  --format speedscope \
  -o flamegraphs/wall.json \
  --duration 60
```

### Viewing Flame Graphs

1. Open https://www.speedscope.app/ in a browser.
2. Drag and drop the `.json` file from `flamegraphs/` into the page.
3. Use the **Left Heavy** view for aggregated hot paths, or **Sandwich** view to find all callers/callees of a specific function.

## Running Locust Load Profiles

Locust load test files live in `tests/load/`. Each profile targets a different scenario:

### Smoke Test

Verify the endpoint is responding under minimal load. Single user, 1 request.

```bash
locust -f tests/load/locustfile.py \
  --headless \
  --users 1 \
  --spawn-rate 1 \
  --run-time 30s \
  --host http://localhost:8000 \
  --tags smoke
```

### Baseline Test

Establish normal performance metrics. Moderate concurrency (5-10 users) for 5 minutes.

```bash
locust -f tests/load/locustfile.py \
  --headless \
  --users 10 \
  --spawn-rate 2 \
  --run-time 5m \
  --host http://localhost:8000 \
  --csv flamegraphs/baseline \
  --tags baseline
```

### Stress Test

Push beyond expected load to find breaking points. Ramp to 50 users.

```bash
locust -f tests/load/locustfile.py \
  --headless \
  --users 50 \
  --spawn-rate 5 \
  --run-time 10m \
  --host http://localhost:8000 \
  --csv flamegraphs/stress \
  --tags stress
```

### Soak Test

Run at baseline load for an extended period to detect memory leaks and resource exhaustion.

```bash
locust -f tests/load/locustfile.py \
  --headless \
  --users 10 \
  --spawn-rate 2 \
  --run-time 1h \
  --host http://localhost:8000 \
  --csv flamegraphs/soak \
  --tags soak
```

## Reading the Baseline Report

The baseline report template is at `docs/performance/baseline-report-template.md`. Key sections:

- **TTFT (Time to First Token)**: Measures perceived responsiveness. p50 should be under 2s for short prompts.
- **Throughput**: Requests/second and tokens/second at each concurrency level.
- **Hot Path Waterfall**: Breakdown of where time is spent in each phase of request processing.
- **Error Budget**: Error rates compared against SLO thresholds.

## OTEL Span Reference

All spans use `get_tracer()` from `deep_agent.aegra.otel`. When OTEL is enabled, these spans are exported to the configured OTLP endpoint.

| Span Name | Location | Attributes | Description |
|-----------|----------|------------|-------------|
| `startup.cold` | `deep_agent/aegra/graph.py` `_ensure_startup()` | `startup.first_request` | Cold start initialization on first request |
| `auth.token_refresh` | `deep_agent/aegra/graph.py` `agent()` | `auth.token_present` | SSO token refresh via OIDC |
| `mcp.tool_discovery` | `deep_agent/aegra/graph.py` `agent()` | `mcp.tool_count`, `mcp.server_count` | Full MCP tool discovery cycle |
| `mcp.server_connect` | `deep_agent/aegra/mcp.py` `_connect_single_server()` | `mcp.server_name`, `mcp.tool_count` | Individual MCP server connection |
| `model.create` | `deep_agent/src/cache/model_cache.py` `get_or_create_model_from_spec()` | `model.provider`, `model.name`, `model.cache_hit` | LLM model instance creation (cache miss) |
| `pii.scrub` | `deep_agent/src/pii/middleware.py` `PIIMiddleware.awrap_model_call()` | `pii.message_count`, `pii.token_count`, `pii.has_system_message` | PII detection and scrubbing of model inputs |
| `personalization.load` | `deep_agent/src/personalization/repository.py` `list_top_memories()` | `personalization.operation`, `personalization.limit`, `personalization.memory_count` | Load user memories from Postgres |
| `personalization.load` | `deep_agent/src/personalization/repository.py` `list_rules()` | `personalization.operation`, `personalization.active_only`, `personalization.rule_count` | Load user rules from Postgres |
