"""Multi-turn conversation load test scenario.

Simulates users having 3-5 turn conversations on a single thread,
measuring per-turn TTFT to observe context-growth effects.
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


class MultiTurnUser(HttpUser):
    """Simulates a user having a multi-turn conversation.

    On start, creates a new thread.  Each task iteration sends 3-5
    sequential messages on the same thread and measures per-turn
    metrics.  TTFT is expected to increase as the conversation
    context grows.

    After completing a conversation, creates a fresh thread for the
    next iteration to avoid unbounded context growth.
    """

    weight = 3
    wait_time = between(3, 8)

    # Number of turns per conversation (inclusive range)
    MIN_TURNS = 3
    MAX_TURNS = 5

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
            if response.status_code in (200, 201):
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
    def multi_turn_conversation(self) -> None:
        """Send 3-5 messages sequentially on the same thread."""
        if not self._thread_id:
            self._create_thread()
            if not self._thread_id:
                return

        num_turns = random.randint(self.MIN_TURNS, self.MAX_TURNS)  # noqa: S311
        turn_metrics: list[StreamMetrics] = []

        for turn_number in range(1, num_turns + 1):
            prompt = random.choice(self._prompts)  # noqa: S311
            metrics = self._send_turn(prompt, turn_number)
            turn_metrics.append(metrics)

            # If a turn fails hard, stop the conversation
            if metrics.error and not metrics.first_token_received:
                break

            # Brief pause between turns to simulate human reading/thinking
            time.sleep(random.uniform(1.0, 3.0))  # noqa: S311

        # Report aggregate conversation metrics
        self._report_conversation_metrics(turn_metrics)

        # Create a fresh thread for the next conversation
        self._create_thread()

    def _send_turn(self, prompt: str, turn_number: int) -> StreamMetrics:
        """Send a single turn and consume the SSE stream.

        Args:
            prompt: The message content to send.
            turn_number: 1-based turn index in the conversation.

        Returns:
            ``StreamMetrics`` for this turn.
        """
        endpoint = RUNS_STREAM_ENDPOINT.format(thread_id=self._thread_id)
        payload = build_run_payload(prompt)

        start_time = time.time()
        metrics = StreamMetrics()

        try:
            with self.client.post(
                endpoint,
                json=payload,
                name=f"POST /threads/{{id}}/runs/stream [turn {turn_number}]",
                stream=True,
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(
                        f"Turn {turn_number} failed: {response.status_code} "
                        f"{response.text[:200]}"
                    )
                    metrics.total_time_ms = (time.time() - start_time) * 1000
                    return metrics

                metrics = self._consume_stream(response, start_time)

                if metrics.error:
                    response.failure(
                        f"Turn {turn_number} stream error: {metrics.error}"
                    )
                elif not metrics.first_token_received:
                    response.failure(f"Turn {turn_number}: no content tokens received")
                else:
                    response.success()

        except Exception as exc:
            metrics.error = exc
            metrics.total_time_ms = (time.time() - start_time) * 1000

        # Report per-turn custom metrics
        self._report_turn_metrics(metrics, turn_number)

        return metrics

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

    def _report_turn_metrics(
        self,
        metrics: StreamMetrics,
        turn_number: int,
    ) -> None:
        """Fire custom Locust events for per-turn TTFT and timing.

        Args:
            metrics: The stream metrics for this turn.
            turn_number: 1-based turn index.
        """
        if metrics.first_token_received:
            events.request.fire(
                request_type="SSE",
                name=f"TTFT (multi_turn, turn={turn_number})",
                response_time=metrics.ttft_ms,
                response_length=0,
                context={"turn": turn_number},
                exception=None,
            )

        events.request.fire(
            request_type="SSE",
            name=f"Total stream (multi_turn, turn={turn_number})",
            response_time=metrics.total_time_ms,
            response_length=metrics.token_count,
            context={
                "turn": turn_number,
                "token_count": metrics.token_count,
            },
            exception=metrics.error,
        )

    def _report_conversation_metrics(
        self,
        turn_metrics: list[StreamMetrics],
    ) -> None:
        """Fire an aggregate metric for the full conversation.

        Reports total conversation duration and average TTFT across
        all turns that produced content.
        """
        total_time = sum(m.total_time_ms for m in turn_metrics)
        total_tokens = sum(m.token_count for m in turn_metrics)
        ttft_values = [m.ttft_ms for m in turn_metrics if m.first_token_received]
        avg_ttft = sum(ttft_values) / len(ttft_values) if ttft_values else 0.0
        had_error = any(m.error is not None for m in turn_metrics)

        events.request.fire(
            request_type="SSE",
            name="Conversation total (multi_turn)",
            response_time=total_time,
            response_length=total_tokens,
            context={
                "turns_completed": len(turn_metrics),
                "avg_ttft_ms": avg_ttft,
                "total_tokens": total_tokens,
            },
            exception=turn_metrics[-1].error if had_error else None,
        )
