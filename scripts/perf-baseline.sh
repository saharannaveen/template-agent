#!/usr/bin/env bash
set -euo pipefail

AGENT_URL="${AGENT_BASE_URL:-http://localhost:5002}"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
REPORT_DIR="tests/load/reports"
REFERENCE_FILE="$REPORT_DIR/baseline-reference.json"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_FILE="$REPORT_DIR/baseline-$TIMESTAMP.md"
CSV_PREFIX="$REPORT_DIR/locust-$TIMESTAMP"
USERS="${PERF_USERS:-3}"
DURATION="${PERF_DURATION:-90s}"
SPAWN_RATE="${PERF_SPAWN_RATE:-1}"
REGRESSION_THRESHOLD="${PERF_REGRESSION_THRESHOLD:-20}"

mkdir -p "$REPORT_DIR"

info()  { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }
ok()    { printf "\033[1;32m✓ %s\033[0m\n" "$1"; }
warn()  { printf "\033[1;33m⚠ %s\033[0m\n" "$1"; }
fail()  { printf "\033[1;31m✗ %s\033[0m\n" "$1"; }
pass()  { printf "\033[1;32m  PASS  %s\033[0m\n" "$1"; }
regr()  { printf "\033[1;31m  FAIL  %s\033[0m\n" "$1"; }

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

if [ -f "$REFERENCE_FILE" ]; then
  info "Reference baseline found — will compare for regressions (threshold: ${REGRESSION_THRESHOLD}%)"
else
  info "No reference baseline — this run will become the reference"
fi

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
JAEGER_JSON="{}"
if [ "$JAEGER_UP" = true ]; then
  info "Pulling Jaeger traces..."
  JAEGER_RAW=$(curl -sf "$JAEGER_URL/api/traces?service=Health+Assistant&limit=100" 2>/dev/null || echo '{"data":[]}')
  echo "$JAEGER_RAW" > "$REPORT_DIR/jaeger-traces-$TIMESTAMP.json"

  JAEGER_JSON=$(echo "$JAEGER_RAW" | python3 -c "
import json, sys
data = json.load(sys.stdin)
traces = data.get('data', [])

span_stats = {}
for t in traces:
    for s in t['spans']:
        op = s['operationName']
        dur = s['duration'] / 1000
        if op not in span_stats:
            span_stats[op] = {'count': 0, 'total': 0, 'min': float('inf'), 'max': 0, 'values': []}
        span_stats[op]['count'] += 1
        span_stats[op]['total'] += dur
        span_stats[op]['min'] = min(span_stats[op]['min'], dur)
        span_stats[op]['max'] = max(span_stats[op]['max'], dur)
        span_stats[op]['values'].append(dur)

result = {}
for op, s in span_stats.items():
    vals = sorted(s['values'])
    p50 = vals[len(vals)//2] if vals else 0
    p95_idx = min(int(len(vals) * 0.95), len(vals)-1)
    p95 = vals[p95_idx] if vals else 0
    result[op] = {
        'count': s['count'],
        'avg': round(s['total'] / s['count'], 1),
        'min': round(s['min'], 1) if s['min'] != float('inf') else 0,
        'max': round(s['max'], 1),
        'p50': round(p50, 1),
        'p95': round(p95, 1),
    }
print(json.dumps({'trace_count': len(traces), 'spans': result}))
" 2>/dev/null || echo '{}')

  JAEGER_SUMMARY=$(echo "$JAEGER_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
spans = data.get('spans', {})
print(f'Total traces: {data.get(\"trace_count\", 0)}')
print()
print(f'{\"Span\":40s} {\"Count\":>5s} {\"Avg(ms)\":>8s} {\"p50(ms)\":>8s} {\"p95(ms)\":>8s} {\"Max(ms)\":>8s}')
print('-' * 81)
for op in sorted(spans, key=lambda x: -spans[x]['avg'] * spans[x]['count']):
    s = spans[op]
    print(f'{op:40s} {s[\"count\"]:5d} {s[\"avg\"]:8.1f} {s[\"p50\"]:8.1f} {s[\"p95\"]:8.1f} {s[\"max\"]:8.1f}')
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

# ── Build current snapshot for comparison ────────────────────────

CURRENT_SNAPSHOT=$(python3 -c "
import json, sys

post = json.loads('''$POST_METRICS''')
pre = json.loads('''$PRE_METRICS''')
jaeger = json.loads('''$JAEGER_JSON''')
spans = jaeger.get('spans', {})

snapshot = {
    'timestamp': '$TIMESTAMP',
    'users': $USERS,
    'duration': '$DURATION',
    'metrics': {},
    'jaeger': {},
    'locust': {},
}

for key, av in post.items():
    pv = pre.get(key, 0)
    short = key.replace('health_assistant_', '')
    if isinstance(av, dict):
        pc = pv.get('count', 0) if isinstance(pv, dict) else 0
        ac = av.get('count', 0)
        asv = av.get('sum', 0)
        ps = pv.get('sum', 0) if isinstance(pv, dict) else 0
        delta_c = ac - pc
        delta_s = asv - ps
        avg = delta_s / delta_c if delta_c > 0 else (asv / ac if ac > 0 else 0)
        snapshot['metrics'][short] = {'calls': delta_c, 'avg': round(avg, 3), 'total': round(delta_s, 3)}
    else:
        snapshot['metrics'][short] = {'value': av - pv}

for op, s in spans.items():
    snapshot['jaeger'][op] = s

print(json.dumps(snapshot, indent=2))
" 2>/dev/null)

echo "$CURRENT_SNAPSHOT" > "$REPORT_DIR/snapshot-$TIMESTAMP.json"

# ── Compare against reference ────────────────────────────────────

VERDICT=""
COMPARISON=""
REGRESSION_FOUND=false

if [ -f "$REFERENCE_FILE" ]; then
  info "Comparing against reference baseline..."

  COMPARISON=$(python3 -c "
import json, sys

ref = json.load(open('$REFERENCE_FILE'))
cur = json.loads('''$CURRENT_SNAPSHOT''')
threshold = $REGRESSION_THRESHOLD

lines = []
regressions = []
improvements = []
stable = []

key_metrics = [
    ('graph_build_duration_seconds', 'Graph build', 'metrics'),
    ('llm_time_to_first_token_seconds', 'LLM TTFT', 'metrics'),
    ('conversation_duration_seconds', 'Conversation duration', 'metrics'),
    ('stream_duration_seconds', 'Stream duration', 'metrics'),
]

key_spans = [
    ('ChatGoogleGenerativeAI', 'Gemini LLM call'),
    ('graph.build', 'Graph build'),
    ('graph.personalization', 'Personalization'),
    ('model.create', 'Model creation'),
    ('graph.mcp_tools', 'MCP tools'),
    ('personalization.load', 'DB: personalization'),
    ('mcp.server_connect', 'MCP server connect'),
    ('pii.scrub', 'PII scrubbing'),
]

lines.append('| Component | Reference | Current | Change | Verdict |')
lines.append('|-----------|-----------|---------|--------|---------|')

for metric_key, label, source in key_metrics:
    ref_m = ref.get(source, {}).get(metric_key, {})
    cur_m = cur.get(source, {}).get(metric_key, {})
    ref_avg = ref_m.get('avg', 0)
    cur_avg = cur_m.get('avg', 0)
    if ref_avg > 0 and cur_avg > 0:
        pct = ((cur_avg - ref_avg) / ref_avg) * 100
        if pct > threshold:
            verdict = f'🔴 +{pct:.0f}% REGRESSION'
            regressions.append(f'{label}: {ref_avg:.3f}s → {cur_avg:.3f}s (+{pct:.0f}%)')
        elif pct < -threshold:
            verdict = f'🟢 {pct:.0f}% IMPROVED'
            improvements.append(f'{label}: {ref_avg:.3f}s → {cur_avg:.3f}s ({pct:.0f}%)')
        else:
            verdict = f'⚪ {pct:+.0f}% stable'
            stable.append(label)
        lines.append(f'| {label} (OTEL) | {ref_avg:.3f}s | {cur_avg:.3f}s | {pct:+.1f}% | {verdict} |')

for span_key, label in key_spans:
    ref_s = ref.get('jaeger', {}).get(span_key, {})
    cur_s = cur.get('jaeger', {}).get(span_key, {})
    ref_avg = ref_s.get('avg', 0)
    cur_avg = cur_s.get('avg', 0)
    ref_p95 = ref_s.get('p95', 0)
    cur_p95 = cur_s.get('p95', 0)
    if ref_avg > 0 and cur_avg > 0:
        pct = ((cur_avg - ref_avg) / ref_avg) * 100
        if pct > threshold:
            verdict = f'🔴 +{pct:.0f}% REGRESSION'
            regressions.append(f'{label}: {ref_avg:.0f}ms → {cur_avg:.0f}ms (+{pct:.0f}%)')
        elif pct < -threshold:
            verdict = f'🟢 {pct:.0f}% IMPROVED'
            improvements.append(f'{label}: {ref_avg:.0f}ms → {cur_avg:.0f}ms ({pct:.0f}%)')
        else:
            verdict = f'⚪ {pct:+.0f}% stable'
            stable.append(label)
        lines.append(f'| {label} (Jaeger) | {ref_avg:.0f}ms (p95: {ref_p95:.0f}ms) | {cur_avg:.0f}ms (p95: {cur_p95:.0f}ms) | {pct:+.1f}% | {verdict} |')

print('\n'.join(lines))
print()
if regressions:
    print('REGRESSIONS_FOUND=true')
    print('### 🔴 Regressions')
    for r in regressions:
        print(f'- {r}')
if improvements:
    print('### 🟢 Improvements')
    for i in improvements:
        print(f'- {i}')
if stable:
    print(f'### ⚪ Stable ({len(stable)} components)')
    print(f'- {', '.join(stable)}')
" 2>/dev/null || echo "Failed to compare")

  if echo "$COMPARISON" | grep -q "REGRESSIONS_FOUND=true"; then
    REGRESSION_FOUND=true
    COMPARISON=$(echo "$COMPARISON" | grep -v "REGRESSIONS_FOUND=true")
  fi
else
  info "Saving as reference baseline..."
  cp "$REPORT_DIR/snapshot-$TIMESTAMP.json" "$REFERENCE_FILE"
  ok "Reference saved to $REFERENCE_FILE"
  COMPARISON="*First run — this is now the reference baseline. Future runs will compare against it.*"
fi

# ── Verdict ──────────────────────────────────────────────────────

if [ ! -f "$REFERENCE_FILE" ] || [ "$(cat "$REFERENCE_FILE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('timestamp',''))" 2>/dev/null)" = "$TIMESTAMP" ]; then
  VERDICT="📊 **BASELINE ESTABLISHED** — first run, no comparison available"
elif [ "$REGRESSION_FOUND" = true ]; then
  VERDICT="🔴 **REGRESSION DETECTED** — performance degraded beyond ${REGRESSION_THRESHOLD}% threshold"
else
  VERDICT="🟢 **PASS** — no regressions detected (threshold: ${REGRESSION_THRESHOLD}%)"
fi

# ── Generate metrics table ───────────────────────────────────────

METRICS_TABLE=$(python3 -c "
import json

pre = json.loads('''$PRE_METRICS''')
post = json.loads('''$POST_METRICS''')

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
import csv

with open('${CSV_PREFIX}_stats.csv') as f:
    rows = list(csv.DictReader(f))

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

# ── Write report ─────────────────────────────────────────────────

info "Generating baseline report..."

cat > "$REPORT_FILE" << REPORT
# Performance Baseline Report

**Date:** $(date '+%Y-%m-%d %H:%M:%S')
**Branch:** $(git branch --show-current)
**Commit:** $(git log --oneline -1)
**Provider:** Gemini (Vertex AI)
**Load:** $USERS users, $DURATION, spawn=$SPAWN_RATE/s

---

## Verdict

$VERDICT

## Regression Analysis

$COMPARISON

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

## Files Generated

- \`$REPORT_FILE\` — this report
- \`${CSV_PREFIX}_stats.csv\` — Locust request statistics
- \`$REPORT_DIR/metrics-pre-$TIMESTAMP.json\` — OTEL metrics before test
- \`$REPORT_DIR/metrics-post-$TIMESTAMP.json\` — OTEL metrics after test
- \`$REPORT_DIR/jaeger-traces-$TIMESTAMP.json\` — Jaeger raw traces
- \`$REPORT_DIR/snapshot-$TIMESTAMP.json\` — Snapshot for future comparison

## Observability Endpoints

| System | URL |
|--------|-----|
| OTEL Metrics | $AGENT_URL/metrics |
| Jaeger UI | $JAEGER_URL |
| Langfuse | https://us.cloud.langfuse.com |
REPORT

ok "Report generated: $REPORT_FILE"

# ── Console output ───────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════"
echo "  $VERDICT"
echo "════════════════════════════════════════════"
echo ""
if [ -n "$COMPARISON" ] && [ "$COMPARISON" != "*First run — this is now the reference baseline. Future runs will compare against it.*" ]; then
  echo "$COMPARISON"
  echo ""
fi
echo "$METRICS_TABLE"
echo ""
if [ -n "$JAEGER_SUMMARY" ]; then
  echo "$JAEGER_SUMMARY"
fi
echo ""
echo "Report: $REPORT_FILE"
echo "CSV:    ${CSV_PREFIX}_stats.csv"
echo "Ref:    $REFERENCE_FILE"
