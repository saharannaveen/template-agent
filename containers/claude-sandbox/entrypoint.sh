#!/bin/bash
set -e

CLAUDE_HOME="${HOME}/.claude"

# ── Git Credentials ──
if [ -n "$GITHUB_TOKEN" ]; then
  git config --global credential.helper store
  echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
  chmod 600 ~/.git-credentials
  git config --global user.email "loop-engineering@agent.dev"
  git config --global user.name "LoopBot"
fi

if [ -n "$GITLAB_TOKEN" ]; then
  git config --global credential.helper store
  echo "https://oauth2:${GITLAB_TOKEN}@gitlab.com" >> ~/.git-credentials
  chmod 600 ~/.git-credentials
fi

# ── Auto-clone repo ──
if [ -n "$REPO_URL" ]; then
  echo "Cloning $REPO_URL..."
  git clone --depth 1 "$REPO_URL" /workspace/repo 2>&1 || true
  if [ -d "/workspace/repo" ] && [ -n "$REPO_BRANCH" ]; then
    cd /workspace/repo
    git fetch origin "$REPO_BRANCH" --depth 1 2>/dev/null && \
      git checkout "$REPO_BRANCH" 2>/dev/null || \
      git checkout -b "$REPO_BRANCH" 2>/dev/null || true
    echo "On branch: $(git branch --show-current)"
  fi
fi

# ── Plugins/Skills (install once, persist on mounted volume) ──
if [ -n "$CLAUDE_PLUGINS" ] && [ ! -f "$CLAUDE_HOME/.plugins-installed" ]; then
  echo "Installing plugins: $CLAUDE_PLUGINS"
  for plugin in $CLAUDE_PLUGINS; do
    claude plugins install "$plugin" 2>/dev/null || true
  done
  touch "$CLAUDE_HOME/.plugins-installed"
fi

# ── MCP Servers (from env) ──
if [ -n "$MCP_CONFIG" ]; then
  echo "$MCP_CONFIG" > "$CLAUDE_HOME/.mcp.json"
fi

# ── Settings (from env or mounted file) ──
if [ -n "$CLAUDE_SETTINGS" ]; then
  echo "$CLAUDE_SETTINGS" > "$CLAUDE_HOME/settings.json"
fi

# ── Session resume support ──
# Sessions stored at $CLAUDE_HOME/sessions/ — persists if mounted on PVC
if [ -n "$RESUME_SESSION_ID" ]; then
  echo "Resuming session: $RESUME_SESSION_ID"
fi

exec claude "$@"
