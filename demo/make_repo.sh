#!/bin/sh
# Builds a small repo whose agent configs have drifted apart, for the demo and CI smoke test.
set -eu
D="${1:-/tmp/shop-api}"
rm -rf "$D"; mkdir -p "$D/.cursor/rules" "$D/.claude/skills/release" "$D/src/api"
cd "$D"
cat > CLAUDE.md <<'MD'
# shop-api

- Use pnpm, never npm or yarn.
- Run `pnpm test` before every commit.
- Money is integer cents, never floats.
MD
cat > AGENTS.md <<'MD'
# shop-api

- Use npm.
- Run `npm test` before every commit.
MD
cat > .cursor/rules/api.mdc <<'MD'
---
description: Conventions for HTTP handlers
globs: src/api/**/*.ts
alwaysApply: false
---
# API handlers

- Validate every request body with zod.
- Return errors as { error: { code, message } }.
MD
cat > .claude/skills/release/SKILL.md <<'MD'
---
name: release
description: Cut a release - bump version, tag, write the changelog
---
1. Run `pnpm version minor`.
2. Push the tag and open the release PR.
MD
cat > .mcp.json <<'JSON'
{
  "mcpServers": {
    "postgres": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "env": { "DATABASE_URL": "${DATABASE_URL}" }
    }
  }
}
JSON
mkdir -p .cursor && echo '{ "mcpServers": {} }' > .cursor/mcp.json
mkdir -p .codex && printf 'model = "gpt-5-codex"\n' > .codex/config.toml
echo "// app" > src/api/orders.ts
