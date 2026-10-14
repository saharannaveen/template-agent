---
name: headless-invoke
description: Invoke another AI agent via its headless webhook endpoint through the gateway. Use when you need to delegate a task to an external agent.
include_tools:
  - webhook_invoke
---

# Headless Agent Invocation

Use the `webhook_invoke` tool to call another agent's headless endpoint through the gateway.

## When to Use
- You need to delegate a calculation or task to a specialist agent
- The target agent is registered on the platform and accessible via the gateway
- You want the result back in the current conversation

## Parameters
- **target**: Agent path as `env/org/name` (e.g., `preprod/nsaharan/test1`)
- **message**: The query to send to the target agent

## Example
```
webhook_invoke(target="preprod/nsaharan/test1", message="calculate BMI for weight 89kg and height 172cm")
```

## Notes
- The tool handles authentication automatically (user SSO token or SA token)
- Responses are streamed back from the target agent
- The target agent must be deployed and accessible via the gateway
