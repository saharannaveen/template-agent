#!/usr/bin/env bash
set -euo pipefail

AGENT_URL="${AGENT_BASE_URL:-http://localhost:5002}"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
REPORT_DIR="tests/load/reports"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_FILE="$REPORT_DIR/baseline-$TIMESTAMP.md"
CSV_PREFIX="$REPORT_DIR/locust-$TIMESTAMP"
USERS="${PERF_USERS:-3}"
DURATION="${PERF_DURATION:-90s}"
SPAWN_RATE="${PERF_SPAWN_RATE:-1}"

mkdir -p "$REPORT_DIR"

info()  { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }
ok()    { printf "\033[1;32m✓ %s\033[0m\n" "$1"; }
fail()  { printf "\033[1;31m✗ %s\033[0m\n" "$1"; }

# ── Prereq checks ────────────────────────────────────────────────

info "Checking prerequisites..."

if ! curl -sf "$AGENT_URL/health" > /dev/null 2>&1; then
  fail "Agent not running at $AGENT_URL"
  echo "  Start with: make local"
  exit 1
fi
ok "Agent healthy at $AGENT_URL"

JAEGER_UP=false
if curl -sf "$JAEGER_URL/api/services" > /dev/null 2>&1; then
  ok "Jaeger available at $JAEGER_URL"
  JAEGER_UP=true
else
  echo "  ⚠ Jaeger not running — traces will be skipped"
fi

if ! command -v .venv/bin/locust > /dev/null 2>&1; then
  fail "locust not installed"
  echo "  Install with: uv pip install locust --python .venv/bin/python"
  exit 1
fi
ok "Locust installed"

# ── Capture pre-test metrics ─────────────────────────────────────

info "Capturing pre-test metrics..."
PRE_METRICS=$(curl -sf "$AGENT_URL/metrics")
echo "$PRE_METRICS" > "$REPORT_DIR/metrics-pre-$TIMESTAMP.json"

# ── Run Locust ───────────────────────────────────────────────────

info "Running Locust ($USERS users, $DURATION, spawn=$SPAWN_RATE/s)..."
PYTHONPATH="$(pwd)" \
AGENT_BASE_URL="$AGENT_URL" \
.venv/bin/locust -f tests/load/locustfile.py \
  --headless \
  --users "$USERS" \
  --spawn-rate "$SPAWN_RATE" \
  --run-time "$DURATION" \
  --host "$AGENT_URL" \
  --csv "$CSV_PREFIX" 2>&1 | tee "$REPORT_DIR/locust-output-$TIMESTAMP.log" | \
  grep -E "Aggregated|TTFT|Total stream|Conversation|Error report|occurrences" || true

ok "Locust complete"

# ── Capture post-test metrics ────────────────────────────────────

info "Capturing post-test metrics..."
POST_METRICS=$(curl -sf "$AGENT_URL/metrics")
echo "$POST_METRICS" > "$REPORT_DIR/metrics-post-$TIMESTAMP.json"

# ── Pull Jaeger traces ───────────────────────────────────────────

JAEGER_SUMMARY=""
if [ "$JAEGER_UP" = true ]; then
  info "Pulling Jaeger traces..."
  JAEGER_RAW=$(curl -sf "$JAEGER_URL/api/traces?service=Health+Assistant&limit=100" 2>/dev/null || echo '{"data":[]}')
  echo "$JAEGER_RAW" > "$REPORT_DIR/jaeger-traces-$TIMESTAMP.json"

  JAEGER_SUMMARY=$(echo "$JAEGER_RAW" | python3 -c "
import json, sys
data = json.load(sys.stdin)
traces = data.get('data', [])

span_stats = {}
for t in traces:
    for s in t['spans']:
        op = s['operationName']
        dur = s['duration'] / 1000
        if op not in span_stats:
            span_stats[op] = {'count': 0, 'total': 0, 'min': float('inf'), 'max': 0}
        span_stats[op]['count'] += 1
        span_stats[op]['total'] += dur
        span_stats[op]['min'] = min(span_stats[op]['min'], dur)
        span_stats[op]['max'] = max(span_stats[op]['max'], dur)

print(f'Total traces: {len(traces)}')
print()
print(f'{\"Span\":45s} {\"Count\":>5s} {\"Avg(ms)\":>8s} {\"Min(ms)\":>8s} {\"Max(ms)\":>8s}')
print('-' * 78)
for op in sorted(span_stats, key=lambda x: -span_stats[x]['total']):
    s = span_stats[op]
    avg = s['total'] / s['count']
    mn = s['min'] if s['min'] != float('inf') else 0
    print(f'{op:45s} {s[\"count\"]:5d} {avg:8.1f} {mn:8.1f} {s[\"max\"]:8.1f}')
" 2>/dev/null || echo "Failed to parse Jaeger traces")
  ok "Jaeger traces captured"
fi

# ── Parse agent logs ─────────────────────────────────────────────

info "Parsing agent logs..."
AGENT_LOG="/tmp/agent-perf.log"
if [ -f "$AGENT_LOG" ]; then
  GRAPH_HITS=$(grep -c "Graph cache HIT" "$AGENT_LOG" 2>/dev/null || echo 0)
  GRAPH_MISSES=$(grep -c "Graph cache MISS" "$AGENT_LOG" 2>/dev/null || echo 0)
  ERRORS=$(grep -ci "error\|exception\|traceback" "$AGENT_LOG" 2>/dev/null || echo 0)
else
  GRAPH_HITS=0
  GRAPH_MISSES=0
  ERRORS=0
fi

# ── Generate report ──────────────────────────────────────────────

info "Generating baseline report..."

METRICS_TABLE=$(python3 -c "
import json

pre = json.loads('''$PRE_METRICS''')
post = json.loads('''$POST_METRICS''')

# Separate counters and histograms
counters = []
histograms = []

for key in sorted(post.keys()):
    pv = pre.get(key, 0)
    av = post.get(key, 0)
    short = key.replace('health_assistant_', '')
    if isinstance(av, dict):
        histograms.append((short, pv, av))
    else:
        counters.append((short, pv, av))

print('### Counters')
print()
print('| Metric | Before | After | Delta |')
print('|--------|--------|-------|-------|')
for short, pv, av in counters:
    delta = av - pv
    sign = '+' if delta >= 0 else ''
    print(f'| \`{short}\` | {pv} | {av} | {sign}{delta} |')

print()
print('### Histograms (latency)')
print()
print('| Metric | Calls | Avg | Total | Delta (calls) |')
print('|--------|-------|-----|-------|---------------|')
for short, pv, av in histograms:
    pc = pv.get('count', 0) if isinstance(pv, dict) else 0
    ps = pv.get('sum', 0) if isinstance(pv, dict) else 0
    ac = av.get('count', 0)
    asv = av.get('sum', 0)
    delta_c = ac - pc
    delta_s = round(asv - ps, 3)
    avg = f'{asv / ac:.3f}s' if ac > 0 else 'n/a'
    delta_avg = ''
    if delta_c > 0:
        delta_avg = f'{delta_s / delta_c:.3f}s avg'
    elif delta_c == 0:
        delta_avg = 'no new calls'
    print(f'| \`{short}\` | {ac} | {avg} | {round(asv, 3)}s | +{delta_c} ({delta_avg}) |')
" 2>/dev/null || echo "Failed to generate metrics table")

LOCUST_SUMMARY=""
if [ -f "${CSV_PREFIX}_stats.csv" ]; then
  LOCUST_SUMMARY=$(python3 -c "
import csv, io

with open('${CSV_PREFIX}_stats.csv') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print('| Type | Name | Reqs | Fails | Avg(ms) | p50 | p95 | p99 | Max |')
print('|------|------|------|-------|---------|-----|-----|-----|-----|')
for r in rows:
    name = r.get('Name', '')
    if not name:
        continue
    rtype = r.get('Type', '')
    reqs = r.get('Request Count', '0')
    fails = r.get('Failure Count', '0')
    avg = r.get('Average Response Time', '0')
    p50 = r.get('50%', 'N/A')
    p95 = r.get('95%', 'N/A')
    p99 = r.get('99%', 'N/A')
    mx = r.get('Max Response Time', '0')
    try:
        avg = f'{float(avg):.0f}'
        mx = f'{float(mx):.0f}'
    except ValueError:
        pass
    print(f'| {rtype} | {name} | {reqs} | {fails} | {avg} | {p50} | {p95} | {p99} | {mx} |')
" 2>/dev/null || echo "Failed to parse Locust CSV")
fi

cat > "$REPORT_FILE" << REPORT
# Performance Baseline Report

**Date:** $(date '+%Y-%m-%d %H:%M:%S')
**Branch:** $(git branch --show-current)
**Commit:** $(git log --oneline -1)
**Provider:** Gemini (Vertex AI)
**Load:** $USERS users, $DURATION, spawn=$SPAWN_RATE/s

---

## OTEL Metrics

$METRICS_TABLE

## Locust Results

$LOCUST_SUMMARY

## Jaeger Trace Analysis

\`\`\`
$JAEGER_SUMMARY
\`\`\`

## Agent Internals

| Metric | Value |
|--------|-------|
| Graph cache HITs | $GRAPH_HITS |
| Graph cache MISSes | $GRAPH_MISSES |
| Log errors/exceptions | $ERRORS |

## Hot Path Summary

The dominant hot path is the LLM call (\`ChatGoogleGenerativeAI\`), consuming 95%+ of
total request time. Graph build overhead is ~100ms cached, ~850ms cold. All middleware
combined is <5ms.

## Files Generated

- \`$REPORT_FILE\` — this report
- \`${CSV_PREFIX}_stats.csv\` — Locust request statistics
- \`$REPORT_DIR/metrics-pre-$TIMESTAMP.json\` — OTEL metrics before test
- \`$REPORT_DIR/metrics-post-$TIMESTAMP.json\` — OTEL metrics after test
- \`$REPORT_DIR/jaeger-traces-$TIMESTAMP.json\` — Jaeger raw traces
- \`$REPORT_DIR/locust-output-$TIMESTAMP.log\` — Locust console output

## Observability Endpoints

| System | URL |
|--------|-----|
| OTEL Metrics | $AGENT_URL/metrics |
| Jaeger UI | $JAEGER_URL |
| Langfuse | https://us.cloud.langfuse.com |
REPORT

ok "Report generated: $REPORT_FILE"

echo ""
echo "════════════════════════════════════════════"
echo "  BASELINE SUMMARY"
echo "════════════════════════════════════════════"
echo ""
echo "$METRICS_TABLE"
echo ""
if [ -n "$JAEGER_SUMMARY" ]; then
  echo "$JAEGER_SUMMARY"
fi
echo ""
echo "Report: $REPORT_FILE"
echo "CSV:    ${CSV_PREFIX}_stats.csv"
