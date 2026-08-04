# Dynamic Subagents in Deep Agents — Architecture & Concepts

## Table of Contents

1. [Deep Agents Architecture Recap](#deep-agents-architecture-recap)
2. [What Are Dynamic Subagents](#what-are-dynamic-subagents)
3. [Deep Agents vs Dynamic Subagents](#deep-agents-vs-dynamic-subagents)
4. [How the eval Tool Works](#how-the-eval-tool-works)
5. [The task() Bridge](#the-task-bridge)
6. [Determinism — What It Is and What It Isn't](#determinism)
7. [Where Dynamic Subagents Fit In Our Use Case](#where-dynamic-subagents-fit-in-our-use-case)
8. [Building Blocks — Subagents, MCP, Skills, Models](#building-blocks)
9. [Sandbox and Code Execution](#sandbox-and-code-execution)
10. [Budget, Limits, and Performance Control](#budget-limits-and-performance-control)
11. [User Visibility and Status](#user-visibility-and-status)
12. [Implementation Reference](#implementation-reference)
13. [Key Takeaways](#key-takeaways)

---

## 1. Deep Agents Architecture Recap <a id="deep-agents-architecture-recap"></a>

Deep Agents is a LangChain library (`deepagents`) that provides an opinionated agent architecture with built-in planning, filesystem access, subagent delegation, skills, memory, and summarization.

### How Our Agent Works Today

```
User Request
    │
    ▼
┌─────────────────────────────────┐
│         Orchestrator            │  ← gemini-2.5-pro
│   (config/agent/PROMPT.md)      │  ← Classifies intent, delegates work
│                                 │  ← NEVER does analysis itself
│   Tools: validate_email,        │
│          queue_task,             │
│          check_task_status       │
│   Skills: client-intake          │
└────────────┬────────────────────┘
             │ calls task(subagentType="analyst")
             ▼
┌─────────────────────────────────┐
│     Subagent (e.g. analyst)     │  ← Has its own system prompt
│                                 │  ← Scoped MCP tools (calculate_bmi, search_web)
│                                 │  ← Scoped skills (bmi-report)
│                                 │  ← Runs full LLM loop independently
└─────────────────────────────────┘
```

The orchestrator is a **coordinator** — it classifies user intent and delegates to specialist subagents. Each subagent has:

- A **controlled system prompt** (defined in markdown frontmatter)
- **Scoped MCP tools** (only the tools it needs via `allowed_tools`/`denied_tools`)
- **Skills** (reusable knowledge + scripts)
- **Its own LLM** (can be a different model than the orchestrator)

### Our 10 Subagents

| Subagent | MCP Tools | Purpose |
|----------|-----------|---------|
| analyst | calculate_bmi, search_web | BMI calculation and classification |
| publisher | send_email | Email delivery of reports |
| nutritionist | search_web | Meal plans and dietary guidance |
| fitness-coach | search_web | Exercise programs |
| risk-assessor | search_web | Health risk profiles |
| report-writer | *(none)* | Compiles multi-section reports |
| comparator | *(none)* | Group statistics and rankings |
| wellness-advisor | search_web | Sleep, stress, hydration tips |
| data-validator | *(none)* | Input validation |
| follow-up-scheduler | send_email, validate_email | Action plans and reminders |

### Our 4 MCP Tools

All provided by `template-mcp-server` on port 5001:

| Tool | What It Does |
|------|-------------|
| `calculate_bmi` | Takes height_cm and weight_kg, returns BMI value + category |
| `search_web` | Returns health tips for a BMI category |
| `send_email` | Sends email to a recipient |
| `validate_email` | Validates email format |

---

## 2. What Are Dynamic Subagents <a id="what-are-dynamic-subagents"></a>

Despite the name, "dynamic subagents" does **not** mean creating new subagent types at runtime. The subagents are still pre-defined in config.

**"Dynamic" refers to the dispatch mechanism** — how the orchestrator invokes subagents.

### Without Dynamic Subagents (Standard Deep Agents)

The orchestrator LLM makes one `task` tool call per turn:

```
Turn 1:  LLM thinks → calls task(analyst, "BMI for Alice")     → waits for result
Turn 2:  LLM thinks → calls task(analyst, "BMI for Bob")       → waits for result
Turn 3:  LLM thinks → calls task(analyst, "BMI for Carol")     → waits for result
Turn 4:  LLM thinks → calls task(risk-assessor, "risks for Alice") → waits for result
...
Turn 12: LLM thinks → calls task(report-writer, "compile all")     → waits for result
```

Each turn requires a full LLM inference just to decide the next step.

### With Dynamic Subagents

The orchestrator writes a **JavaScript program** that dispatches subagents:

```javascript
// ONE eval call — the LLM writes this code, then steps out of the loop
const bmis = await Promise.all(people.map(p =>
  task({
    description: `Calculate BMI for ${p.name}: height ${p.height}cm, weight ${p.weight}kg`,
    subagentType: "analyst"
  })
));

const risks = await Promise.all(bmis.map(b =>
  task({ description: `Risk profile for ${b}`, subagentType: "risk-assessor" })
));

const report = await task({
  description: `Compile: ${JSON.stringify({bmis, risks})}`,
  subagentType: "report-writer"
});
```

The JavaScript runs in a sandboxed QuickJS interpreter. `task()` bridges back into the Python subagent system.

### A More Accurate Name

LangChain calls this "dynamic subagents" but a more honest name would be **"programmatic subagent dispatch"** or **"code-driven orchestration."** The subagents aren't dynamic — the dispatch is.

---

## 3. Deep Agents vs Dynamic Subagents <a id="deep-agents-vs-dynamic-subagents"></a>

### Side-by-Side Comparison

| Aspect | Standard Deep Agents | With Dynamic Subagents |
|--------|---------------------|----------------------|
| **Dispatch mechanism** | LLM makes one `task` tool call per turn | LLM writes JS that calls `task()` in loops |
| **Parallelism** | Sequential only — one subagent at a time | `Promise.all` for concurrent dispatch |
| **Orchestrator LLM calls** | N calls (one per dispatch decision) | 1 call (writes the program) |
| **Scale coverage** | LLM judgment — may skip items at scale | Loop guarantees every item processed |
| **Subagent definitions** | Pre-defined in config | Same — still pre-defined in config |
| **Subagent capabilities** | Controlled system prompt, scoped tools | Same — no change |
| **Cost** | N × orchestrator inference | 1 × orchestrator + cheap JS execution |

### What Dynamic Subagents Do NOT Change

- **Subagent quality** — each subagent is still an LLM, same reasoning ability
- **Subagent control** — same system prompts, same tool scoping, same skills
- **Planning quality** — the orchestrator still decides what to do (it just expresses it as code)
- **MCP tool access** — same tools, same access control

### The Actual Value (Honest Assessment)

Dynamic subagents provide exactly **two concrete benefits**:

1. **Parallel execution** — `Promise.all` runs multiple subagents concurrently. Impossible with sequential tool calls. Pure latency win.

2. **Batch scale** — a `for` loop will process all 100 items. An LLM making sequential tool calls may fatigue, summarize early, or hit turn limits at item 20.

For small-scale work (3-5 subagent calls), the difference is marginal. The feature becomes valuable when processing many items or when wall-clock latency matters.

---

## 4. How the eval Tool Works <a id="how-the-eval-tool-works"></a>

`eval` is a tool injected by `CodeInterpreterMiddleware` that runs JavaScript in a sandboxed QuickJS interpreter embedded in the Python process.

### Execution Flow

```
User: "Calculate BMI for 100 employees and flag the obese ones"
         │
         ▼
┌─────────────────────────┐
│   Orchestrator LLM      │  Sees the `eval` tool in its tool list
│   (gemini-2.5-pro)      │  Decides to write JS code
│                         │  Makes ONE tool call: eval(code="...")
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│   QuickJS Interpreter    │  Lightweight JS runtime (in-process, NOT K8s)
│                         │  Executes the JS code the LLM wrote
│   Has globals:          │
│     • task()            │  Bridges back into SubAgentMiddleware
│     • console.log()     │  Captured and returned to LLM
│     • tools.*           │  PTC: direct tool calls (if allowlisted)
└──────────┬──────────────┘
           │  When JS calls task({subagentType: "analyst"})
           ▼
┌─────────────────────────┐
│   SubAgentMiddleware     │  Same middleware that handles normal task calls
│                         │  Looks up "analyst" in the subagent registry
│                         │  Runs the subagent's full LLM loop
│                         │  Returns result back to QuickJS
└─────────────────────────┘
```

### What QuickJS Is and Is Not

QuickJS is a tiny, embeddable JavaScript engine compiled into a Python C extension (`quickjs-rs`). It is:

- **NOT** Node.js
- **NOT** a browser
- **NOT** a K8s pod (that's `CodeExecutionMiddleware`)
- **NOT** connected to the network

It runs **inside the agent process** with:

| Constraint | Value |
|-----------|-------|
| Memory cap | 64MB (configurable) |
| Per-call timeout | 5 seconds (configurable) |
| Filesystem access | None |
| Network access | None |
| Module imports | None (`require`/`import` unavailable) |

The only way it interacts with the outside world is through injected globals:

| Global | What It Does |
|--------|-------------|
| `task()` | Dispatches a subagent — bridges into SubAgentMiddleware |
| `console.log()` | Captured, returned as output to the LLM |
| `tools.*` | PTC — calls MCP tools directly (only if allowlisted in config) |

### Variable Persistence Modes

The `mode` config controls how long JS variables live:

| Mode | Variables Persist Across |
|------|------------------------|
| `thread` | All turns in the conversation — `bmiResult` from turn 1 is available in turn 3 |
| `turn` | Only within one orchestrator turn — fresh context each turn |
| `call` | Only within one `eval` call — fresh context every time |

---

## 5. The task() Bridge <a id="the-task-bridge"></a>

When JavaScript calls `task()`, the QuickJS interpreter suspends, the bridge calls into Python, runs a full subagent LLM loop, and resumes JS with the result.

### task() Parameters

```javascript
const result = await task({
  description: "Calculate BMI for Alice: height 165cm, weight 58kg",  // required
  subagentType: "analyst",                                            // required — must match a pre-defined subagent name
  responseSchema: {                                                   // optional — forces structured output
    type: "object",
    properties: {
      bmi: { type: "number" },
      category: { type: "string" }
    }
  }
});
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `description` | Yes | The prompt/instructions sent to the subagent |
| `subagentType` | Yes | Which pre-defined subagent to invoke (must match a name in config) |
| `responseSchema` | No | JSON Schema for structured output — result is a typed JS object |

### What Happens Inside

1. QuickJS **suspends** JS execution
2. Bridge calls Python → `SubAgentMiddleware` → looks up `subagentType` in `subagent_graphs` dict
3. Runs the subagent's full LLM loop (which may call MCP tools, use skills, etc.)
4. Returns the subagent's final message as a string (or typed object if `responseSchema` was provided)
5. QuickJS **resumes** with that value as the resolved `await`

For `Promise.all`, multiple `task()` calls are dispatched concurrently on the Python side.

---

## 6. Determinism — What It Is and What It Isn't <a id="determinism"></a>

### The Claim

LangChain's documentation suggests dynamic subagents provide "deterministic coverage" because code execution is deterministic.

### The Reality

The full execution chain is:

```
LLM writes code               (non-deterministic — may write different code each run)
  → code executes             (deterministic — JS runs the same way)
    → calls subagents         (non-deterministic — each subagent is an LLM)
      → code processes results (deterministic — filter, map, etc.)
        → calls more subagents (non-deterministic — LLM reasoning varies)
```

Deterministic execution sandwiched between non-deterministic layers. The overall system behavior is **non-deterministic**.

### What "Deterministic" Actually Means Here

Given a specific piece of JS code and specific subagent results, the code will always:
- Call the same subagents in the same order
- Apply the same filters and transformations
- Never skip items in a loop

But:
- The LLM may write **different code** for the same prompt on different runs
- Each subagent may produce **different results** for the same input
- So `bmis.filter(b => b.category === "Obese")` may filter differently because the analyst returned slightly different output

### What's Actually Gained

The code itself (once written) guarantees coverage — a `for` loop processes every item. An LLM making sequential tool calls might:
- Forget it already processed Alice and redo her
- Skip Carol because the context got long
- Decide "3 is enough" at an arbitrary point
- Change strategy mid-way

These failure modes disappear when orchestration is code, not LLM judgment. But the code is only as good as what the LLM writes, and the LLM writes different code each time.

---

## 7. Where Dynamic Subagents Fit In Our Use Case <a id="where-dynamic-subagents-fit-in-our-use-case"></a>

### Our Health Screening Platform

Our template-agent is a Red Hat fitness assistant with BMI analysis, health reporting, and email delivery. Dynamic subagents enable:

### Pattern 1: Batch Health Screening (Fan-Out)

Process 100 employees in parallel instead of sequentially:

```javascript
const bmis = await Promise.all(employees.map(e =>
  task({ description: `BMI for ${e.name}...`, subagentType: "analyst" })
));
```

Without dynamic subagents: 100 sequential LLM turns. With: 1 turn + parallel execution.

### Pattern 2: Multi-Phase Pipeline

Chain validation → analysis → risk assessment → reporting:

```javascript
// Phase 1: Validate
const valid = await task({ description: `Validate: ${data}`, subagentType: "data-validator" });

// Phase 2: Analyze (parallel)
const bmis = await Promise.all(valid.records.map(r =>
  task({ description: `BMI for ${r.name}...`, subagentType: "analyst" })
));

// Phase 3: Risk + Wellness (parallel, 2 subagents per person)
const enriched = await Promise.all(bmis.map(b => Promise.all([
  task({ description: `Risks: ${b}`, subagentType: "risk-assessor" }),
  task({ description: `Wellness: ${b}`, subagentType: "wellness-advisor" })
])));

// Phase 4: Compare + Report
const comparison = await task({ description: `Compare: ${bmis}`, subagentType: "comparator" });
const report = await task({ description: `Compile all...`, subagentType: "report-writer" });
```

### Pattern 3: Conditional Routing

Send follow-up emails only to flagged employees:

```javascript
const flagged = bmis.filter(b => b.category === "Obese" || b.category === "Overweight");
await Promise.all(flagged.map(b =>
  task({ description: `Schedule follow-up for ${b.name}...`, subagentType: "follow-up-scheduler" })
));
```

### When NOT to Use Dynamic Subagents

- Single BMI calculation — just call the analyst directly
- Simple orchestration (2-3 sequential steps) — standard task calls are fine
- When you need full control over each step — sequential tool calls let the LLM adapt between steps

---

## 8. Building Blocks — Subagents, MCP, Skills, Models <a id="building-blocks"></a>

### How They Compose

```
┌─────────────────────────────────────────────────────────┐
│                    create_deep_agent()                    │
│                                                          │
│   model ──────── LLM (gemini-2.5-pro, claude-sonnet-4)  │
│   tools ──────── MCP tools (calculate_bmi, search_web)   │
│   subagents ──── Pre-defined specialists                 │
│   skills ─────── Reusable knowledge + scripts            │
│   middleware ─── Guardrails, audit, CodeInterpreter       │
│   backend ────── Filesystem (state, composite, sandbox)  │
│   memory ─────── Cross-turn memory (namespaced)          │
│   permissions ── File access control                     │
└─────────────────────────────────────────────────────────┘
```

### Subagent Definition (Markdown Frontmatter)

Each subagent is defined in `config/agent/subagents/<name>.md`:

```yaml
---
name: analyst
type: default          # default | compiled | async
description: >
  Calculates BMI and classifies the result.
model: gemini-2.5-pro
allowed_tools:
  - calculate_bmi
  - search_web
denied_tools:
  - send_email
skills:
  - bmi-report
---

You are a BMI Analyst...  (system prompt follows)
```

The subagent gets:
- **Its own system prompt** — the markdown body
- **Scoped tools** — only `allowed_tools`, never `denied_tools`
- **Skills** — loaded from `config/agent/skills/<name>/SKILL.md`
- **Model** — inherits from orchestrator if not specified

### MCP Tools

MCP (Model Context Protocol) servers expose tools that subagents can call. Configured in `config/agent/mcp.json`:

```json
{
  "mcpServers": {
    "template-mcp-server": {
      "url": "http://localhost:5001/mcp",
      "transport": "streamable_http",
      "enabled": true,
      "auth": true,
      "auth_mode": "sso"
    }
  }
}
```

Each subagent accesses only the MCP tools listed in its `allowed_tools`. This is **tool access control** — the nutritionist can `search_web` but cannot `calculate_bmi` or `send_email`.

### Skills

Skills are reusable knowledge packages with:
- `SKILL.md` — instructions for the subagent
- `references/` — domain knowledge files
- `assets/` — templates, scripts
- `evals/` — evaluation test cases

The analyst uses the `bmi-report` skill which provides BMI categories, report structure, and health tip references.

### How Dynamic Subagents Use All of These

When JS calls `task({subagentType: "analyst"})`:
1. SubAgentMiddleware looks up the `analyst` spec
2. Creates a subagent LLM loop with the analyst's **model**, **system prompt**, **scoped MCP tools**, and **skills**
3. The analyst runs independently — calls `calculate_bmi` via MCP, reads `bmi-report` skill references
4. Returns the result to QuickJS

The dynamic dispatch doesn't bypass any of these controls. Each subagent still operates within its defined boundaries.

---

## 9. Sandbox and Code Execution <a id="sandbox-and-code-execution"></a>

There are **two completely independent** code execution systems:

### CodeInterpreterMiddleware (QuickJS) — For Orchestration

```
Purpose:     Dispatch subagents programmatically
Runtime:     QuickJS (in-process, embedded JS engine)
Isolation:   Memory cap, timeout, no filesystem, no network
Tool:        eval
Use case:    LLM writes JS with task() calls, Promise.all, loops
```

### CodeExecutionMiddleware / K8sSandbox — For Computation

```
Purpose:     Run user's actual code safely
Runtime:     Ephemeral K8s Job (pod with container)
Isolation:   Full container (seccomp, read-only rootfs, dropped caps, NetworkPolicy)
Tool:        execute_code (custom middleware) or execute (SandboxBackendProtocol)
Use case:    Run Python data analysis, shell scripts, Node.js code
```

### They Are Independent

| | QuickJS | K8s Sandbox |
|---|---------|------------|
| Requires K8s cluster | No | Yes |
| Runs on `make local` | Yes | No |
| What code runs | JS orchestration logic | User's Python/shell/Node code |
| Security model | In-process sandboxing | Container isolation |
| Interacts with subagents | Yes (via `task()`) | No |

### Using Both Together

When both are enabled, the agent has three dispatch paths:

```javascript
// Inside an eval call (QuickJS):

// 1. Dispatch subagents via task()
const bmi = await task({ description: "...", subagentType: "analyst" });

// 2. Run Python in K8s sandbox via PTC (if allowlisted)
const chart = await tools.execute({ command: "python3 -c 'import json; ...'" });

// 3. Direct MCP tool calls via PTC (if allowlisted)
const files = await tools.glob({ pattern: "reports/*.md" });
```

For `tools.*` to work from inside JS, the tool must be allowlisted in the PTC config:

```yaml
dynamic_subagents:
  ptc: [glob, grep, execute]    # tools accessible from JS code
```

### SandboxBackendProtocol

deepagents 0.7+ provides a standard interface (`SandboxBackendProtocol`) for sandbox backends. Our `K8sSandbox` adapter wraps the existing `K8sJobRunner` behind this protocol:

```python
class K8sSandbox(BaseSandbox):
    # Implement 4 abstract methods:
    def execute(self, command, *, timeout=None) -> ExecuteResponse: ...
    def upload_files(self, files) -> list[FileUploadResponse]: ...
    def download_files(self, paths) -> list[FileDownloadResponse]: ...
    @property
    def id(self) -> str: ...
```

When using `K8sSandbox` as the backend, deepagents automatically provides `execute`, `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep` tools — all routed through the K8s Job sandbox. The custom `CodeExecutionMiddleware` becomes redundant.

---

## 10. Budget, Limits, and Performance Control <a id="budget-limits-and-performance-control"></a>

### Layer 1: QuickJS Sandbox Limits (per eval call)

```yaml
dynamic_subagents:
  timeout: 5.0              # JS execution timeout per eval call
  memory_limit: 67108864    # 64MB heap cap
  max_ptc_calls: 256        # max direct tools.* calls per eval
  max_result_chars: 4000    # truncate results returned to JS
```

**Note:** `max_ptc_calls` caps `tools.*` calls only. `task()` subagent dispatches are NOT counted against this limit.

### Layer 2: Deepagents Guardrail Middleware (per agent run)

```yaml
middleware:
  defaults:
    model_call_limit:
      enabled: true
      run_limit: 50         # max LLM calls (orchestrator + all subagents combined)
    tool_call_limit:
      enabled: true
      run_limit: 200        # max MCP tool calls across all agents
```

These DO cap subagent dispatches indirectly. Each `task()` dispatch triggers a full subagent LLM run (counted against `model_call_limit`) with MCP tool calls (counted against `tool_call_limit`).

### Layer 3: K8s Execution Limits (per code execution)

```yaml
code_execution:
  max_timeout_seconds: 60
  max_concurrent_per_org: 3
  resource_limits:
    cpu: "500m"
    memory: "256Mi"
```

### Effective Budget Example

With `model_call_limit: 50` and `tool_call_limit: 200`:
- Orchestrator uses 1-3 LLM calls (writing JS code + retries)
- Each subagent dispatch uses ~2-3 LLM calls
- So ~15-20 subagent dispatches max before hitting the model call limit
- Each subagent makes 1-3 MCP tool calls
- So ~60-100 MCP calls before hitting the tool call limit

### Controlling Costs

| Goal | Config Change |
|------|--------------|
| Fewer subagent dispatches | Lower `model_call_limit.run_limit` |
| Fewer MCP tool calls | Lower `tool_call_limit.run_limit` |
| Shorter JS execution | Lower `dynamic_subagents.timeout` |
| Less memory for JS | Lower `dynamic_subagents.memory_limit` |
| Disable dynamic subagents entirely | Set `dynamic_subagents.enabled: false` |
| Disable PTC (no tools.* from JS) | Set `dynamic_subagents.ptc: []` |

---

## 11. User Visibility and Status <a id="user-visibility-and-status"></a>

### The Problem

When the orchestrator writes a JS program that dispatches 10+ subagents via `eval`, the user sees **nothing** until the entire program finishes. All subagent work happens inside one tool call. This can take minutes for complex workflows.

### Current Status Reporting

With `dcode` (LangChain's CLI agent), dynamic subagents display in a live progress panel grouped by dispatch phase. Our template-ui does not have this — the user sees a loading spinner until `eval` returns.

### What the User Sees

| Phase | Standard Deep Agents | Dynamic Subagents |
|-------|---------------------|-------------------|
| Planning | LLM response streaming | LLM response streaming |
| Dispatching | Each `task` tool call visible | **Hidden** — all inside `eval` |
| Subagent work | Results stream back per subagent | **Hidden** — accumulating in JS |
| Final result | Streams as subagents complete | Returns all at once when `eval` finishes |

### Planned Enhancement: Execution Overlay (Hybrid Stepper + DAG)

A button in the chat UI opens an overlay showing real-time workflow execution:

**Default view — Vertical Stepper:**
```
Step 1: Validate Input Data          ✅ 1.2s
  └─ data-validator (3 records)       done

Step 2: Calculate BMI (parallel)      ⏳ 4.8s
  ├─ analyst → Alice                  ✅ 3.1s
  │   ├─ calculate_bmi               ✅
  │   └─ search_web                  ✅
  ├─ analyst → Bob                    ⏳ running
  │   └─ calculate_bmi               ⏳
  └─ analyst → Carol                  ○ queued

Step 3: Risk + Wellness (parallel)    ○ pending
Step 4: Compare Results               ○ pending
Step 5: Compile Report                ○ pending
```

**Expanded view — Click a parallel step to see DAG:**
```
              ┌──────────┐
         ┌───→│risk(Alice)│───┐
         │    └──────────┘   │
[analyst]─┤                   ├→[comparator]→[report]
         │    ┌──────────┐   │
         └───→│well(Alice)│───┘
              └──────────┘
```

**Implementation requires two parts:**

1. **Backend: Structured event emission** — Emit typed events during `eval` execution:
   - `workflow_plan` — the steps the LLM planned (emitted when `eval` starts)
   - `subagent_start` — subagent dispatch began (name, description, step)
   - `tool_call` — MCP tool called within a subagent (tool name, args)
   - `tool_result` — MCP tool returned (tool name, result summary)
   - `subagent_complete` — subagent finished (name, duration, result summary)
   - `step_complete` — entire step finished (step number, duration)
   - `approval_required` — HITL gate reached (tool name, awaiting user)

   These events flow via SSE (Server-Sent Events) to the UI in real-time.

2. **Frontend: React overlay component** — Renders the events as a hybrid stepper/DAG:
   - Stepper component with collapsible steps
   - Mini DAG renderer (React Flow or custom SVG) for parallel branches
   - Status badges (pending → running → completed/failed)
   - Duration timers per node
   - Tool call detail on expand
   - HITL approval buttons inline

This is a separate feature branch. The backend event emission can be prototyped using `console.log()` with structured JSON, then upgraded to proper SSE events.

---

## 12. Implementation Reference <a id="implementation-reference"></a>

### Files Modified/Created

| File | Change |
|------|--------|
| `pyproject.toml` | `deepagents[quickjs]==0.7.3` |
| `deep_agent/src/agent/config/middleware.py` | Added `DynamicSubagentConfig` model |
| `deep_agent/src/infrastructure/middleware.py` | Added `_build_dynamic_subagents()` |
| `deep_agent/src/infrastructure/backend.py` | Fixed backend factories → instances for 0.7.x |
| `deep_agent/src/infrastructure/async_tasks.py` | Fixed TypedDict isinstance for Python 3.14 |
| `deep_agent/src/code_execution/k8s_sandbox.py` | `K8sSandbox(BaseSandbox)` adapter |
| `config/agent/runtime/agent.yaml` | Added `dynamic_subagents` config section |
| `config/agent/subagents/*.md` | 7 new subagent configs |
| `tests/unit/config/test_dynamic_subagent_config.py` | 13 config tests |
| `tests/unit/test_dynamic_subagent_middleware.py` | 7 middleware builder tests |
| `tests/unit/code_execution/test_k8s_sandbox.py` | 11 K8sSandbox tests |

### Config Reference (agent.yaml)

```yaml
middleware:
  defaults:
    dynamic_subagents:
      enabled: true                    # master toggle
      memory_limit: 67108864           # 64MB QuickJS heap
      timeout: 5.0                     # per-eval timeout (seconds)
      max_ptc_calls: 256               # max tools.* calls per eval
      tool_name: eval                  # tool name exposed to LLM
      max_result_chars: 4000           # result truncation
      capture_console: true            # bridge console.log
      subagents: true                  # expose task() global
      mode: thread                     # thread | turn | call
      ptc: [glob, grep]               # tools accessible from JS
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `deepagents` | 0.7.3 | Agent framework with CodeInterpreter support |
| `langchain-quickjs` | 0.3.5 | QuickJS sandbox for JS execution |
| `quickjs-rs` | 0.2.5 | QuickJS C extension (installed by langchain-quickjs) |

### Separate Virtual Environment

The upgrade from deepagents 0.4.12 → 0.7.3 is isolated to `.venv-dynamic-subagent`. Other branches use `.venv` with the old version. The Makefile auto-detects which venv to use.

---

## 13. Key Takeaways <a id="key-takeaways"></a>

1. **Dynamic subagents = programmatic dispatch, not dynamic creation.** Subagents are still pre-defined with controlled prompts, scoped tools, and skills. The "dynamic" part is how they're orchestrated at runtime.

2. **The real value is parallelism and batch scale.** `Promise.all` runs subagents concurrently (impossible with sequential tool calls). Loops guarantee coverage at scale. Everything else is the same LLM-driven process.

3. **It's not deterministic end-to-end.** The JS code executes deterministically, but the LLM writes different code each run, and each subagent produces non-deterministic results. Deterministic orchestration sandwiched between non-deterministic layers.

4. **QuickJS and K8s sandbox are independent.** QuickJS is for orchestration (dispatching subagents). K8s sandbox is for computation (running user code). They solve different problems and can be used together or separately.

5. **Control comes from subagent definitions, not dynamic dispatch.** Tool scoping, system prompts, skills, and model selection are all defined in config. Dynamic dispatch just decides when and how to call them.

6. **Budget control uses existing guardrails.** `model_call_limit` and `tool_call_limit` middleware indirectly cap how many subagents a single `eval` can dispatch. No new budget mechanism needed.

7. **User visibility is a gap.** When subagents run inside `eval`, the user sees nothing until the entire workflow completes. Progress reporting via `console.log()` streaming is possible but not built into the UI yet.

---

*Document generated from implementation on branch `feat/dynamic-subagent` — deepagents 0.7.3 with langchain-quickjs 0.3.5.*
