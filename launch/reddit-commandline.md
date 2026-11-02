Subreddit: r/commandline (check the self-promo rules before posting)

Title: samerules: sync AI coding agent configs (CLAUDE.md, AGENTS.md, Cursor, Codex MCP) from one folder, fail CI on drift

Body:
Small Python CLI, zero deps.

- `samerules import` pulls your existing CLAUDE.md / AGENTS.md / .cursor/rules / MCP configs into .agents/
- `samerules sync` writes them back out for 8 tools
- `samerules check` exits 1 on drift, `samerules diff` shows what changed
- won't clobber hand-edited files without --force, has --dry-run

Install: curl -fsSL https://raw.githubusercontent.com/hamarshehmhmd/samerules/main/install.sh | sh

https://github.com/hamarshehmhmd/samerules (my project, AGPL-3.0)
