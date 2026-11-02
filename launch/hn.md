Title: Show HN: Samerules – one .agents/ folder for CLAUDE.md, AGENTS.md, Cursor rules and MCP configs

URL: https://github.com/hamarshehmhmd/samerules

Text:
If you use more than one coding agent you end up with CLAUDE.md saying "use pnpm" while AGENTS.md still says npm, and MCP servers copied by hand between .mcp.json, .cursor/mcp.json and .codex/config.toml. Nobody notices until an agent does the wrong thing.

So I built a small CLI. You keep rules, skills and MCP servers in .agents/, and `samerules sync` writes the native files for Claude Code, Cursor, Codex, Gemini CLI, OpenCode, Copilot and Windsurf. `samerules check` exits 1 if anything drifted, so you can put it in CI.

A few things I cared about:
- `samerules import` builds .agents/ from the files you already have and tells you where they disagree
- it won't overwrite a file you edited by hand (lock file + header), unless you pass --force
- it merges into opencode.json / .gemini/settings.json / codex config.toml instead of replacing them
- ${VAR} gets translated per tool (${env:VAR}, {env:VAR}, env_vars = [...])

Python, zero deps, AGPL-3.0. Happy to hear which formats I got wrong, they change every month.
