# Performance Baseline Report

## Test Configuration

| Parameter | Value |
|-----------|-------|
| Date | YYYY-MM-DD |
| Branch | `feat/...` |
| Commit | `abc1234` |
| Provider | Gemini / OpenAI / Anthropic |
| Model | e.g. `gemini-3.1-pro-preview` |
| Deployment Target | local / OpenShift dev / OpenShift prod |
| Agent Config | default orchestrator |
| MCP Servers | (list enabled servers) |
| PII Middleware | enabled / disabled |
| Personalization | enabled / disabled |

## TTFT Results (Time to First Token)

### End-to-End TTFT

Measured from HTTP request received to first SSE token emitted.

| Prompt Length | p50 | p75 | p95 | p99 | Samples |
|--------------|-----|-----|-----|-----|---------|
| Short (< 100 tokens) | | | | | |
| Medium (100-500 tokens) | | | | | |
| Long (500-2000 tokens) | | | | | |
| Very Long (> 2000 tokens) | | | | | |

### LLM-Only TTFT

Measured from model invocation to first token callback. Excludes graph build, MCP, PII.

| Prompt Length | p50 | p75 | p95 | p99 | Samples |
|--------------|-----|-----|-----|-----|---------|
| Short (< 100 tokens) | | | | | |
| Medium (100-500 tokens) | | | | | |
| Long (500-2000 tokens) | | | | | |
| Very Long (> 2000 tokens) | | | | | |

## Throughput

| Concurrency | Req/s | Tokens/s (output) | Avg Latency (ms) | p99 Latency (ms) | Error Rate |
|-------------|-------|-------------------|-------------------|-------------------|------------|
| 1 | | | | | |
| 5 | | | | | |
| 10 | | | | | |
| 25 | | | | | |
| 50 | | | | | |

## Hot Path Waterfall

Time breakdown for a single request (median, non-cached).

| Phase | Span Name | Measured Time (ms) | % of Total |
|-------|-----------|--------------------|------------|
| Startup (cold) | `startup.cold` | | |
| Token Refresh | `auth.token_refresh` | | |
| MCP Tool Discovery | `mcp.tool_discovery` | | |
| - Server Connect (per server) | `mcp.server_connect` | | |
| Model Creation | `model.create` | | |
| Personalization Load | `personalization.load` | | |
| Graph Build | `graph.build` | | |
| PII Scrub (per model call) | `pii.scrub` | | |
| LLM Inference | (provider SDK) | | |
| **Total E2E** | | | 100% |

## Error Budget

| Metric | Target SLO | Measured | Status |
|--------|-----------|----------|--------|
| Availability (5xx rate) | < 0.1% | | |
| TTFT p95 | < 5s | | |
| TTFT p99 | < 10s | | |
| Stream error rate | < 1% | | |
| MCP connection failures | < 5% | | |

## Resource Utilization

### CPU

| Condition | Avg CPU (%) | Peak CPU (%) | Notes |
|-----------|-------------|-------------- |-------|
| Idle | | | |
| 1 concurrent request | | | |
| 10 concurrent requests | | | |
| 50 concurrent requests | | | |

### Memory

| Condition | RSS (MB) | Heap (MB) | Notes |
|-----------|----------|-----------|-------|
| Startup | | | |
| After 100 requests | | | |
| After 1000 requests | | | |
| After 1h soak | | | |

### Observations

- (Note any memory growth patterns)
- (Note CPU spikes correlated with specific operations)
- (Note GC pressure or event loop blocking)

## Flame Graph References

| Profile | File | Duration | Description |
|---------|------|----------|-------------|
| CPU baseline | `flamegraphs/cpu.json` | 60s | Baseline CPU profile under 10 concurrent users |
| Wall-clock baseline | `flamegraphs/wall.json` | 60s | Wall-clock profile showing I/O wait time |

## Recommendations

### Immediate (P0)

- (List any hot paths consuming > 20% of total time)
- (List any blocking operations on the event loop)

### Short-term (P1)

- (Caching opportunities identified from flame graph)
- (Connection pooling improvements)

### Long-term (P2)

- (Architectural changes for scale)
- (Async pipeline optimizations)
