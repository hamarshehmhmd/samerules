Subreddit: r/ClaudeCode (check the self-promo rules / flair before posting)

Title: Made a tiny CLI so CLAUDE.md, AGENTS.md and .cursor/rules stop drifting apart

Body:
If people on your team use Claude Code, Cursor and Codex, someone fixes a rule in CLAUDE.md, forgets AGENTS.md, and Codex is still told to use npm lol.

samerules: put rules, skills and MCP servers in one .agents/ folder, run `samerules sync`, and it writes CLAUDE.md, .claude/rules (with paths:), .mcp.json, AGENTS.md, Cursor .mdc files, codex config.toml, etc. `samerules check` fails CI if someone edits a generated file by hand.

`samerules import` bootstraps from what you already have.

https://github.com/hamarshehmhmd/samerules (I'm the author, AGPL-3.0, no deps)

Feedback welcome, especially if Claude Code's rules/skills behave differently than I assumed.
