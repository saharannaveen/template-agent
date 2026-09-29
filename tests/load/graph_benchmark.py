"""In-process graph benchmark that bypasses HTTP.

Directly invokes the LangGraph agent factory and measures graph
build time and LLM-only TTFT without network overhead.  Useful for
isolating LLM latency from infrastructure latency.

Limitations:
    - Requires all agent dependencies to be importable in the Locust
      worker process (Vertex AI credentials, config files, etc.).
    - Uses ``gevent.spawn`` to bridge async graph invocation with
      Locust's gevent-based concurrency model.  If async dependencies
      are incompatible with gevent monkey-patching, this benchmark
      will log errors and skip iterations gracefully.
    - The graph factory performs startup initialization on first call
      (``_ensure_startup``), which may include network calls to MCP
      servers. First-call latency will be higher; subsequent calls
      use the graph cache.

Usage:
    locust -f tests/load/graph_benchmark.py --headless \\
        -u 5 -r 1 -t 2m --host http://localhost:8123
"""

import asyncio
import random
import time
from typing import Any
from unittest.mock import MagicMock

from locust import User, between, events, task

from tests.load.conftest import get_all_prompts


def _make_mock_runtime() -> Any:
    """Create a mock ``ServerRuntime`` with ``user=None``.

    When ``runtime.user`` is ``None``, the graph factory runs in
    schema-only mode: MCP tools are skipped and only built-in tools
    are included.  This is the same path used by LangGraph Studio
    for assistant listing.

    Returns:
        A mock object that satisfies the ``ServerRuntime`` interface
        for schema-only graph construction.
    """
    runtime = MagicMock()
    runtime.user = None
    return runtime


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from synchronous (gevent) context.

    Creates a new event loop per call to avoid conflicts with
    gevent's monkey-patched threading.  This is intentionally
    simple — for high-throughput benchmarking, consider running
    outside Locust with a native async harness.

    Args:
        coro: An awaitable coroutine.

    Returns:
        The coroutine's return value.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class GraphBenchmarkUser(User):
    """In-process benchmark that measures graph build and LLM latency.

    This is a plain ``User`` (not ``HttpUser``) because it does not
    make HTTP requests.  All measurements are reported via custom
    Locust events.

    Metrics reported:
        - **graph_build**: Time to call ``agent(runtime)`` and get
          a compiled graph.
        - **graph_invoke_ttft**: Time from ``astream()`` call to
          first content chunk from the LLM.
        - **graph_invoke_total**: Total time to consume the full
          stream from the graph.
    """

    wait_time = between(5, 15)

    # Required by Locust but unused (no HTTP calls)
    host = "in-process"

    def on_start(self) -> None:
        """Load prompts and build the graph once for reuse."""
        self._prompts = get_all_prompts()
        if not self._prompts:
            raise RuntimeError("Prompt corpus is empty — cannot run benchmark")

        self._graph: Any = None
        self._build_graph()

    def _build_graph(self) -> None:
        """Build the agent graph and measure construction time."""
        start = time.time()
        exception: Exception | None = None

        try:
            from deep_agent.aegra.graph import agent

            runtime = _make_mock_runtime()
            self._graph = _run_async(agent(runtime))
        except Exception as exc:
            exception = exc
            self._graph = None

        elapsed_ms = (time.time() - start) * 1000

        events.request.fire(
            request_type="GRAPH",
            name="graph_build",
            response_time=elapsed_ms,
            response_length=0,
            context={},
            exception=exception,
        )

    @task
    def invoke_graph(self) -> None:
        """Stream a message through the graph and measure latency."""
        if self._graph is None:
            self._build_graph()
            if self._graph is None:
                return

        prompt = random.choice(self._prompts)  # noqa: S311
        start = time.time()
        ttft_ms: float = 0.0
        first_token_received = False
        token_count = 0
        exception: Exception | None = None

        try:
            input_messages = {
                "messages": [
                    {"role": "human", "content": prompt},
                ]
            }

            async def _stream_graph() -> tuple[float, bool, int]:
                """Consume the async stream and return metrics."""
                nonlocal ttft_ms, first_token_received, token_count

                stream = self._graph.astream(
                    input_messages,
                    config={"configurable": {"thread_id": f"bench-{time.time()}"}},
                )

                async for chunk in stream:
                    # LangGraph streams dicts with node names as keys
                    # Content is nested under the agent/model node
                    if _chunk_has_content(chunk):
                        token_count += 1
                        if not first_token_received:
                            ttft_ms = (time.time() - start) * 1000
                            first_token_received = True

                return ttft_ms, first_token_received, token_count

            _run_async(_stream_graph())

        except Exception as exc:
            exception = exc

        total_ms = (time.time() - start) * 1000

        # Report TTFT if we got a first token
        if first_token_received:
            events.request.fire(
                request_type="GRAPH",
                name="graph_invoke_ttft",
                response_time=ttft_ms,
                response_length=0,
                context={"token_count": token_count},
                exception=None,
            )

        # Report total invocation time
        events.request.fire(
            request_type="GRAPH",
            name="graph_invoke_total",
            response_time=total_ms,
            response_length=token_count,
            context={"token_count": token_count},
            exception=exception,
        )


def _chunk_has_content(chunk: Any) -> bool:
    """Check whether a LangGraph stream chunk contains LLM content.

    LangGraph ``astream()`` yields dictionaries keyed by node name.
    Content appears in message objects under the node's output.

    Args:
        chunk: A single item from ``graph.astream()``.

    Returns:
        ``True`` if the chunk carries non-empty text content.
    """
    if not isinstance(chunk, dict):
        return False

    for _node_name, node_output in chunk.items():
        # node_output may be a dict with a "messages" key
        if isinstance(node_output, dict):
            messages = node_output.get("messages", [])
            if isinstance(messages, list):
                for msg in messages:
                    content = getattr(msg, "content", None)
                    if content and isinstance(content, str) and content.strip():
                        return True

    return False
