"""Webhook invoke tool — call another headless agent via the gateway.

Supports two auth modes:
- User token forwarding: uses the current user's SSO token from the auth context
- SA token (client_credentials): uses WEBHOOK_SSO_* env vars when user token is unavailable

The tool is registered as a LangGraph-compatible BaseTool and added to the
agent's available tools when WEBHOOK_GATEWAY_URL is configured.
"""

import json
import os
import time
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deep_agent.utils.pylogger import get_python_logger

logger = get_python_logger()

_GATEWAY_URL = os.environ.get("WEBHOOK_GATEWAY_URL", "")
_SSO_TOKEN_URL = os.environ.get("WEBHOOK_SSO_TOKEN_URL", "")
_SSO_CLIENT_ID = os.environ.get("WEBHOOK_SSO_CLIENT_ID", "")
_SSO_CLIENT_SECRET = os.environ.get("WEBHOOK_SSO_CLIENT_SECRET", "")
_GATEWAY_TOKEN_REFRESH_URL = os.environ.get(
    "WEBHOOK_GATEWAY_TOKEN_REFRESH_URL", ""
)

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_REQUEST_TIMEOUT = float(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "300"))


def _get_sa_token() -> str:
    """Get or refresh a cached SA token via client_credentials grant."""
    cache_key = f"{_SSO_TOKEN_URL}:{_SSO_CLIENT_ID}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached[1] > time.time():
        return cached[0]

    resp = httpx.post(
        _SSO_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": _SSO_CLIENT_ID,
            "client_secret": _SSO_CLIENT_SECRET,
            "scope": "email openid profile",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_at = time.time() + data.get("expires_in", 300) - 30
    _TOKEN_CACHE[cache_key] = (token, expires_at)
    logger.info("webhook_sa_token_acquired", expires_in=data.get("expires_in"))
    return token


def _resolve_token(config: dict[str, Any] | None) -> str:
    """Resolve the best available token: user's first, SA fallback.

    Priority 1: User's SSO token from the MCP auth context (ContextVar).
                Set by ``set_mcp_auth_context()`` at the start of each request.
                This is the same token the user authenticated with — their identity
                is preserved end-to-end (LDAP group check passes).

    Priority 2: SA token via client_credentials grant from env vars.
                Used when no user token is available (headless/event-driven).
                Requires the SA identity in the agent's ``service_accounts``
                allowlist in PROMPT.md.
    """
    from deep_agent.aegra.mcp import _current_access_token

    user_token = _current_access_token.get(None) or ""
    if user_token:
        logger.debug("webhook_using_user_token")
        return user_token

    if _SSO_TOKEN_URL and _SSO_CLIENT_ID and _SSO_CLIENT_SECRET:
        logger.debug("webhook_using_sa_token")
        return _get_sa_token()

    raise ValueError(
        "No token available for webhook invoke. "
        "Either forward a user token or configure WEBHOOK_SSO_* env vars."
    )


def _parse_sse_response(text: str) -> str:
    """Extract the last assistant message from an SSE stream."""
    last_message = ""
    for line in text.split("\n"):
        if not line.startswith("data:"):
            continue
        try:
            data = json.loads(line[5:])
            for msg in data.get("model", {}).get("messages", []):
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    last_message = content
                elif isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, dict) and chunk.get("text", "").strip():
                            last_message = chunk["text"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return last_message


class WebhookInvokeInput(BaseModel):
    target: str = Field(
        description=(
            "Target agent as '{env}/{org}/{name}', e.g. "
            "'preprod/redhatplatform/dataverse-agent'. "
            "env is 'preprod' or 'prod'."
        ),
    )
    message: str = Field(description="Message to send to the target agent.")


def _webhook_invoke(target: str, message: str, **kwargs: Any) -> str:
    """Invoke a headless agent via the gateway webhook endpoint."""
    if not _GATEWAY_URL:
        return "Error: WEBHOOK_GATEWAY_URL not configured"

    try:
        token = _resolve_token(kwargs.get("config"))
    except ValueError as exc:
        return f"Error: {exc}"

    invoke_url = f"{_GATEWAY_URL.rstrip('/')}/api/engine/v1/agents/{target}/invoke"

    logger.info(
        "webhook_invoke_start",
        target=target,
        url=invoke_url,
    )

    try:
        resp = httpx.post(
            invoke_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"message": message},
            timeout=_REQUEST_TIMEOUT,
        )
    except httpx.ConnectError:
        return f"Error: cannot reach gateway at {_GATEWAY_URL}"
    except httpx.TimeoutException:
        return f"Error: request timed out after {_REQUEST_TIMEOUT}s"

    if resp.status_code == 401:
        _TOKEN_CACHE.clear()
        return "Error: authentication failed — token may be expired or invalid"

    if resp.status_code != 200:
        return f"Error: invoke failed with HTTP {resp.status_code}: {resp.text[:200]}"

    result = _parse_sse_response(resp.text)
    logger.info(
        "webhook_invoke_complete",
        target=target,
        response_length=len(result),
    )
    return result or "Agent returned no response"


webhook_invoke_tool = StructuredTool.from_function(
    func=_webhook_invoke,
    name="webhook_invoke",
    description=(
        "Invoke another AI agent via its headless webhook endpoint. "
        "Use this when you need to delegate a task to a different agent. "
        "Provide the target as 'env/org/name' (e.g. 'preprod/myorg/data-agent') "
        "and the message to send."
    ),
    args_schema=WebhookInvokeInput,
)


def get_webhook_tools() -> list[StructuredTool]:
    """Return webhook tools if WEBHOOK_GATEWAY_URL is configured."""
    if not _GATEWAY_URL:
        return []
    return [webhook_invoke_tool]
