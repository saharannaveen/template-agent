#!/bin/bash
set -e

CLAUDE_HOME="${HOME}/.claude"

# ── Git Credentials ──
if [ -n "$GITHUB_TOKEN" ]; then
  git config --global credential.helper store 2>/dev/null || true
  echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > ~/.git-credentials 2>/dev/null || true
  chmod 600 ~/.git-credentials 2>/dev/null || true
fi

if [ -n "$GITLAB_TOKEN" ]; then
  git config --global credential.helper store 2>/dev/null || true
  echo "https://oauth2:${GITLAB_TOKEN}@gitlab.com" >> ~/.git-credentials 2>/dev/null || true
  chmod 600 ~/.git-credentials 2>/dev/null || true
fi

# Git user config from env vars
git config --global user.email "${GIT_AUTHOR_EMAIL:-loop-engineering@agent.dev}" 2>/dev/null || true
git config --global user.name "${GIT_AUTHOR_NAME:-LoopBot}" 2>/dev/null || true

# ── Auto-clone repo ──
if [ -n "$REPO_URL" ]; then
  CLONE_BRANCH="${REPO_BRANCH:-main}"
  echo "Cloning $REPO_URL (branch: $CLONE_BRANCH)..."
  git clone --branch "$CLONE_BRANCH" "$REPO_URL" /workspace/repo 2>&1 || \
    git clone "$REPO_URL" /workspace/repo 2>&1 || true

  if [ -d "/workspace/repo" ]; then
    cd /workspace/repo

    # Checkout base branch if specified
    if [ -n "$REPO_BRANCH" ]; then
      git fetch origin "$REPO_BRANCH" 2>/dev/null && \
        git checkout "$REPO_BRANCH" 2>/dev/null || true
    fi

    # Create feature branch if specified
    if [ -n "$FEATURE_BRANCH" ]; then
      echo "Creating feature branch: $FEATURE_BRANCH from $(git branch --show-current)"
      git checkout -b "$FEATURE_BRANCH" 2>/dev/null || \
        git checkout "$FEATURE_BRANCH" 2>/dev/null || true
    fi

    echo "On branch: $(git branch --show-current)"
    echo "Working directory: $(pwd)"
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

# If first arg is a non-claude command (e.g. sleep, bash), run it directly
if [ "$1" != "" ] && command -v "$1" >/dev/null 2>&1 && [ "$1" != "claude" ]; then
  exec "$@"
fi

exec claude "$@"
