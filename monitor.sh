#!/bin/bash
# Loop Engineering Monitor — run: ./monitor.sh [thread_id]
# Auto-refreshes every 10s. Ctrl+C to stop.

THREAD_ID="${1:-}"
PYTHON=".venv-dynamic-subagent/bin/python"

while true; do
    clear
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  LOOP ENGINEERING DASHBOARD — $(date '+%Y-%m-%d %H:%M:%S')          ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"

    echo ""
    echo "── SERVICES ─────────────────────────────────────────────────────"
    printf "  Agent (5002):    %s\n" "$(curl -s http://localhost:5002/health 2>/dev/null | grep -o healthy || echo '❌ DOWN')"
    printf "  UI (8080):       %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/ 2>/dev/null)"
    printf "  Temporal (8233): %s\n" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8233/ 2>/dev/null)"
    printf "  Worker:          %s\n" "$(pgrep -f temporal.worker > /dev/null 2>&1 && echo '✅ RUNNING' || echo '❌ DOWN')"

    echo ""
    echo "── SANDBOX CONTAINERS ───────────────────────────────────────────"
    SANDBOXES=$(podman ps --filter ancestor=claude-sandbox:v2.1.224 --format '  🐳 {{.Names}} | {{.Status}}' 2>/dev/null)
    echo "${SANDBOXES:-  none}"

    echo ""
    echo "── TEMPORAL WORKFLOWS (recent 5) ────────────────────────────────"
    temporal workflow list --limit 5 2>/dev/null | head -7 || echo "  unavailable"

    echo ""
    echo "── WORKER LOGS (last 5) ─────────────────────────────────────────"
    tail -5 /tmp/temporal-worker.log 2>/dev/null | grep -v "pydantic\|File.*site-packages\|validated_self" | sed 's/^/  /' || echo "  no logs"

    if [ -n "$THREAD_ID" ]; then
        echo ""
        echo "── THREAD: $THREAD_ID ──────────────────"

        curl -s "http://localhost:5002/threads/${THREAD_ID}/runs" 2>/dev/null | $PYTHON -c "
import sys,json
try:
    for r in json.load(sys.stdin):
        print(f'  Run {r[\"run_id\"][:12]}... | {r[\"status\"]}')
except: print('  error reading runs')
" 2>/dev/null

        echo ""
        echo "  Messages:"
        curl -s "http://localhost:5002/threads/${THREAD_ID}/state" 2>/dev/null | $PYTHON -c "
import sys,json
try:
    d=json.load(sys.stdin)
    msgs=d.get('values',{}).get('messages',[])
    for m in msgs:
        mt=m.get('type')
        if mt=='human':
            print(f'    👤 {str(m.get(\"content\",\"\"))[:100]}')
        elif mt=='ai':
            tc=m.get('tool_calls',[])
            if tc:
                print(f'    🤖 → {tc[0].get(\"name\")}()')
            else:
                c=m.get('content','')
                if isinstance(c,list):
                    for item in c:
                        if isinstance(item,dict) and 'text' in item and len(item['text'])>20:
                            print(f'    🤖 {item[\"text\"][:120]}')
                elif isinstance(c,str) and len(c)>20:
                    print(f'    🤖 {c[:120]}')
        elif mt=='tool':
            r=m.get('additional_kwargs',{}).get('claude_code_result',{})
            if r:
                ex=r.get('exit_code','?')
                icon='✅' if ex==0 else '❌'
                print(f'    {icon} exit={ex} model={r.get(\"model\",\"?\")} tokens={r.get(\"input_tokens\",0)}/{r.get(\"output_tokens\",0)}')
                out=r.get('output','')
                if 'passed' in out.lower():
                    import re; m2=re.findall(r'(\d+)\s*(?:tests?\s+)?passed',out.lower())
                    if m2: print(f'       Tests: {m2[-1]} passed')
                if 'push' in out.lower() and 'origin' in out.lower():
                    print(f'       Git push: ✅')
                print(f'       {out[:200]}')
except: print('    error reading state')
" 2>/dev/null
    fi

    echo ""
    echo "── GITHUB BRANCHES ────────────────────────────────────────────"
    curl -s "https://api.github.com/repos/saharannaveen/template-agent/branches" 2>/dev/null | $PYTHON -c "
import sys,json
try:
    for b in json.load(sys.stdin):
        if any(k in b['name'].lower() for k in ['todo','to-do','fastapi','loop','test']):
            print(f'  ✅ {b[\"name\"]} | {b[\"commit\"][\"sha\"][:8]}')
except: pass
" 2>/dev/null

    echo ""
    echo "─────────────────────────────────────────────────────────────────"
    echo "  Refreshing in 10s... (Ctrl+C to stop)"
    sleep 10
done
