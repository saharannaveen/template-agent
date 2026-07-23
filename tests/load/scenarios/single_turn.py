"""Single-turn conversation load test scenario.

Simulates users sending a single message and consuming the full
SSE response stream.  Measures TTFT, total response time, and
token count per request.
"""

import random
import time

from locust import HttpUser, between, events, task

from tests.load.conftest import (
    RUNS_STREAM_ENDPOINT,
    THREADS_ENDPOINT,
    StreamMetrics,
    build_run_payload,
    extract_content_from_event,
    get_all_prompts,
    parse_sse_stream,
)


class SingleTurnUser(HttpUser):
    """Simulates a user sending one message and reading the response.

    On start, creates a new thread.  Each task iteration picks a
    random prompt, sends it to the streaming endpoint, and measures:

    - **TTFT**: time from request to first content-bearing SSE event
    - **Total time**: request to stream completion
    - **Token count**: number of content-bearing SSE events
    """

    weight = 7
    wait_time = between(2, 5)

    def on_start(self) -> None:
        """Create a new thread for this simulated user."""
        self._prompts = get_all_prompts()
        if not self._prompts:
            raise RuntimeError("Prompt corpus is empty — cannot run load test")

        self._thread_id: str | None = None
        self._create_thread()

    def _create_thread(self) -> None:
        """POST to the threads endpoint to create a new conversation thread."""
        with self.client.post(
            THREADS_ENDPOINT,
            json={},
            name="POST /threads",
            catch_response=True,
        ) as response:
            if response.status_code == 200 or response.status_code == 201:
                try:
                    body = response.json()
                    self._thread_id = body.get("thread_id") or body.get("id")
                    if not self._thread_id:
                        response.failure(
                            f"Thread creation returned no thread_id: {body}"
                        )
                    else:
                        response.success()
                except Exception as exc:
                    response.failure(f"Failed to parse thread response: {exc}")
            else:
                response.failure(
                    f"Thread creation failed: {response.status_code} "
                    f"{response.text[:200]}"
                )

    @task
    def single_message(self) -> None:
        """Send a single message and consume the SSE stream."""
        if not self._thread_id:
            self._create_thread()
            if not self._thread_id:
                return

        prompt = random.choice(self._prompts)  # noqa: S311
        endpoint = RUNS_STREAM_ENDPOINT.format(thread_id=self._thread_id)
        payload = build_run_payload(prompt)

        start_time = time.time()
        metrics = StreamMetrics()

        try:
            with self.client.post(
                endpoint,
                json=payload,
                name="POST /threads/{id}/runs/stream",
                stream=True,
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(
                        f"Stream request failed: {response.status_code} "
                        f"{response.text[:200]}"
                    )
                    return

                # Consume the SSE stream and measure metrics
                metrics = self._consume_stream(response, start_time)

                if metrics.error:
                    response.failure(f"Stream consumption error: {metrics.error}")
                elif not metrics.first_token_received:
                    response.failure("No content tokens received in stream")
                else:
                    response.success()

        except Exception as exc:
            metrics.error = exc
            metrics.total_time_ms = (time.time() - start_time) * 1000

        # Report custom metrics regardless of success/failure
        self._report_metrics(metrics)

    def _consume_stream(
        self,
        response: object,
        start_time: float,
    ) -> StreamMetrics:
        """Parse the SSE response stream and collect metrics.

        Args:
            response: The HTTP response object with ``iter_lines()``.
            start_time: Epoch timestamp when the request was initiated.

        Returns:
            Populated ``StreamMetrics``.
        """
        metrics = StreamMetrics()

        try:
            for event in parse_sse_stream(response.iter_lines()):
                content = extract_content_from_event(event)
                if content is not None:
                    metrics.token_count += 1
                    if not metrics.first_token_received:
                        metrics.ttft_ms = (time.time() - start_time) * 1000
                        metrics.first_token_received = True
        except Exception as exc:
            metrics.error = exc

        metrics.total_time_ms = (time.time() - start_time) * 1000
        return metrics

    def _report_metrics(self, metrics: StreamMetrics) -> None:
        """Fire custom Locust events for TTFT and token count.

        These metrics appear in the Locust UI alongside standard
        request statistics.
        """
        if metrics.first_token_received:
            events.request.fire(
                request_type="SSE",
                name="TTFT (single_turn)",
                response_time=metrics.ttft_ms,
                response_length=0,
                context={"turn": 1},
                exception=None,
            )

        events.request.fire(
            request_type="SSE",
            name="Total stream (single_turn)",
            response_time=metrics.total_time_ms,
            response_length=metrics.token_count,
            context={"token_count": metrics.token_count},
            exception=metrics.error,
        )
