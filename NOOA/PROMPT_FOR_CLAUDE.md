# Build a NOOA-based Template Agent Framework

## Context

You are building an agent framework equivalent to `template-agent` (which uses LangGraph + Aegra) but using NVIDIA's NOOA (Object-Oriented Agents) framework. The existing `template-agent` is a production-grade orchestrator/subagent system with skills, MCP integration, dynamic subagent dispatch, code execution sandboxes, and Claude Code loop engineering.

A working MVP already exists at `NOOA/` in this repo — it has an orchestrator + analyst + publisher with BMI analysis working end-to-end. Your job is to extend it into a full framework.

## What NOOA Is

NOOA maps agent concepts onto Python OOP primitives:
- **Class** = Agent (with class docstring as system prompt)
- **Fields** = Typed state (model-visible, pass-by-reference)
- **Methods with real bodies** = Deterministic tools (no LLM needed)
- **Methods with `...` (ellipsis) bodies** = LLM-completed behavior at runtime
- **Type annotations** = Enforced I/O contracts
- **Inheritance** = Agent hierarchies
- **Mixins** = Composable capabilities
- **`@strategy` decorator** = Per-method execution strategy (PredictStrategy for single-shot, CodeActStrategy for iterative REPL)

Install: `uv add nooa` (uses LiteLLM for any LLM provider)

## What Already Exists (NOOA/*)

```
NOOA/
├── main.py              # CLI entry point (interactive + single query)
├── test_agents.py       # Unit tests for deterministic methods
├── agents/
│   ├── __init__.py
│   ├── models.py        # Typed data models (BMIResult, HealthReport, etc.)
│   ├── orchestrator.py  # HealthAssistant(Agent) with CodeActStrategy
│   ├── analyst.py       # BMIAnalyst(Agent) with calculate_bmi + analyze
│   └── publisher.py     # ReportPublisher(Agent) with email formatting
└── skills/
    ├── bmi-report/      # TextSkill with SKILL.md
    ├── client-intake/   # TextSkill with conversion scripts
    └── email-formatter/ # TextSkill with HTML templates
```

## What Needs to Be Built

### 1. Skills Framework (Priority: HIGH)

**How skills work in template-agent:**
- Skills live in `config/agent/skills/<name>/SKILL.md` with YAML frontmatter
- They contain instructions, references, scripts, assets, and evals
- Skills are mounted as virtual paths the agent can read
- Any team can create a skill by adding a directory

**How to implement in NOOA:**
NOOA has built-in `TextSkill` that loads `SKILL.md` files. Extend this:

```python
from nooa import Agent, TextSkill
from pathlib import Path

class MyAgent(Agent):
    """Agent with skills loaded from filesystem."""
    
    # Skills are typed fields — the LLM sees them via doc(self.my_skill)
    data_validation: TextSkill
    report_generation: TextSkill
    
    # Skills can also have runnable scripts
    async def run_skill_script(self, skill_name: str, script: str, *args: str) -> str:
        skill = getattr(self, skill_name)
        return await skill.run_script(script, *args)
```

Build a `SkillRegistry` that:
- Scans a configurable skills directory
- Auto-loads `TextSkill` instances from each `SKILL.md`
- Supports skill dependencies (one skill requires another)
- Supports skill scripts (Python/Shell in `scripts/` dir)
- Supports skill assets (templates, reference docs in `assets/`, `references/`)
- Provides a `create_agent_with_skills(agent_cls, skills_dir)` factory

### 2. Subagent Framework (Priority: HIGH)

**How subagents work in template-agent:**
- Defined as `.md` files with YAML frontmatter (name, type, model, tools, skills)
- Three types: `default` (in-process), `compiled` (pre-compiled graph), `async` (remote)
- Orchestrator dispatches via `task("analyst", ...)` in JavaScript eval

**How to implement in NOOA:**
Subagents are just Agent instances as typed fields on the orchestrator. NOOA's pass-by-reference means the LLM sees the full subagent API.

```python
class Orchestrator(Agent):
    """Orchestrator that delegates to subagents."""
    analyst: BMIAnalyst      # subagent as typed field
    publisher: ReportPublisher
    
    @strategy(CodeActStrategy())  # LLM writes Python to call subagents
    async def handle(self, message: str) -> str:
        """Route user message to appropriate subagent."""
        ...
```

Build a `SubagentLoader` that:
- Reads subagent definitions from `.md` files (reuse template-agent format)
- Dynamically creates Agent subclasses from markdown definitions
- Supports model routing (different models per subagent via `@strategy(llm=...)`)
- Supports tool allow/deny lists (methods exposed/hidden per subagent)
- Supports async subagents (remote Agent Protocol servers)

### 3. MCP Integration (Priority: HIGH)

**How MCP works in template-agent:**
- `mcp.json` registry with server URLs, auth modes (SSO, OAuth, DCR, API key)
- Tools from MCP servers are injected into the agent
- Circuit breaker, caching, parallel connection

**How to implement in NOOA:**
NOOA can integrate with MCP via a `MCPSkill` or by converting MCP tools to agent methods:

```python
from nooa import Agent, Skill

class MCPToolBridge(Skill):
    """Bridge MCP server tools into NOOA agent methods."""
    
    def __init__(self, server_url: str, auth_mode: str = "sso"):
        # Connect to MCP server, list tools, create callable methods
        ...

class MyAgent(Agent):
    mcp_tools: MCPToolBridge  # MCP tools appear as skill methods
```

Build:
- `MCPConnector` — connects to MCP servers from `mcp.json` config
- `MCPSkill` — wraps MCP tools as a Skill the agent can call
- Auth support (SSO token forwarding, OAuth flow)
- Tool caching and circuit breaker

### 4. Dynamic Subagent Orchestration (Priority: MEDIUM)

**How it works in template-agent:**
- `CodeInterpreterMiddleware` exposes `eval` tool
- LLM writes JavaScript with `await task()` calls
- QuickJS runtime executes the orchestration code

**How to implement in NOOA:**
NOOA already has `CodeActStrategy` which lets the LLM write Python. The orchestrator's `handle` method with `@strategy(CodeActStrategy())` IS the dynamic subagent orchestration — the LLM writes Python that calls `self.analyst.analyze()`, `self.publisher.publish()`, etc.

This is actually simpler and more powerful than template-agent's approach because:
1. No JavaScript/QuickJS needed — it's native Python
2. Pass-by-reference means subagents see full data objects, not serialized JSON
3. The LLM can use Python control flow (if/else, loops, try/except)
4. Type checking at method boundaries catches errors early

### 5. Loop Engineering (Priority: MEDIUM)

**How it works in template-agent:**
- `LoopEngineeringMiddleware` wraps claude_code calls with iterative self-correction
- Temporal workflows manage long-running coding tasks
- Cost circuit breaker, struggle detection, user checkpoints

**How to implement in NOOA:**
NOOA's `CodeActStrategy` already IS a loop — the model writes code, sees results, iterates. Build on top:

```python
class CodingAgent(Agent):
    """Autonomous coding agent with self-correction loop."""
    
    max_iterations: int = 5
    cost_budget_usd: float = 25.0
    
    @strategy(CodeActStrategy())
    async def implement(self, task: str, repo_url: str) -> TaskResult:
        """Implement the task with iterative test-fix cycles.
        
        1. Clone repo, understand codebase
        2. Write implementation
        3. Run tests
        4. If tests fail, analyze failures and fix
        5. Repeat until tests pass or max_iterations reached
        """
        ...
    
    def run_tests(self, test_command: str = "pytest") -> TestResult:
        """Run tests and return structured results."""
        # deterministic — runs subprocess
        ...
    
    def estimate_cost(self, task_complexity: str) -> CostEstimate:
        """Estimate cost based on task complexity."""
        ...
```

### 6. Middleware Equivalent (Priority: LOW)

**How it works in template-agent:**
- Middleware pipeline: audit, guardrails, PII, retry, fallback, rate limiting
- Each middleware wraps model calls and tool calls

**How to implement in NOOA:**
NOOA agents don't have middleware in the traditional sense. Instead:
- **Guardrails** → method preconditions/postconditions
- **PII filtering** → deterministic method that sanitizes input/output
- **Rate limiting** → deterministic method or class-level state
- **Retry** → NOOA has built-in retry via `RetryConfig` on the LLM client
- **Audit** → NOOA has built-in tracing (ATIF)

```python
from nooa import Agent
from nooa.decorators import MethodPrecondition, MethodPostcondition

class GuardedAgent(Agent):
    call_count: int = 0
    max_calls: int = 50
    
    # Precondition checked before every LLM call
    @MethodPrecondition
    def check_rate_limit(self):
        if self.call_count >= self.max_calls:
            raise RuntimeError("Rate limit exceeded")
        self.call_count += 1
```

### 7. Configuration System (Priority: LOW)

Build a YAML-based config system similar to `agent.yaml`:

```yaml
name: "Health Assistant"
model: "vertex_ai/gemini-2.5-pro"
skills_dir: "./skills"
subagents_dir: "./subagents"
mcp_config: "./mcp.json"
middleware:
  rate_limit:
    max_calls_per_run: 50
  retry:
    max_retries: 3
  pii:
    enabled: true
```

## Architecture Comparison

| Concept | template-agent (LangGraph) | NOOA Framework |
|---|---|---|
| Agent definition | Markdown + YAML frontmatter | Python class + docstring |
| System prompt | PROMPT.md body | Class docstring |
| Tools | External functions registered | Methods with real bodies |
| LLM behavior | Graph nodes | Methods with `...` bodies |
| Subagent dispatch | eval + task() in JavaScript | CodeActStrategy + self.subagent.method() in Python |
| Skills | SKILL.md directories | TextSkill fields |
| MCP tools | mcp.json + middleware | MCPSkill bridge |
| State | LangGraph state dict | Typed class fields |
| Middleware | Pipeline of wrappers | Preconditions/postconditions + deterministic methods |
| Orchestration | Graph edges + routing | CodeActStrategy (LLM writes Python) |
| Config | YAML (agent.yaml) | YAML → dataclass |
| Deployment | Aegra + K8s | FastAPI + any deployment |

## Testing Strategy

1. **Deterministic tests** (no LLM): Test all methods with real bodies
2. **Integration tests** (with LLM): Test methods with `...` bodies against a real model
3. **End-to-end tests**: Test full orchestrator → subagent → skill flows
4. **Comparison tests**: Same input to both template-agent and NOOA, compare outputs

## Environment Setup

```bash
cd NOOA
uv venv .venv
source .venv/bin/activate
uv pip install nooa google-auth google-cloud-aiplatform

# Set model (LiteLLM format)
export NOOA_MODEL=vertex_ai/gemini-2.5-pro
export VERTEXAI_PROJECT=your-project
export VERTEXAI_LOCATION=us-east5

# Run tests
python test_agents.py

# Run interactive
python main.py

# Run single query
python main.py --query "My height is 175cm and weight is 70kg"
```
