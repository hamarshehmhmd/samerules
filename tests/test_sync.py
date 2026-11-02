import json
import os
import stat

from helpers import exists, project, read, run, write

from samerules.targets import HEADER

API = "---\ndescription: API handler rules\nglobs: src/api/**/*.ts, src/routes/*.ts\n---\n# API handlers\n\n- Validate with zod.\n"
AUTO = "---\ndescription: When touching database migrations\napply: auto\n---\n# Migrations\n\n- Never edit an applied migration.\n"
MANUAL = "---\napply: manual\n---\n# Release checklist\n\n- Bump version.\n"
SKILL = "---\nname: release\ndescription: Cut a release\n---\nRun ./release.sh\n"


def test_sync_writes_instruction_files(repo):
    project(repo, targets=["agents", "claude", "gemini", "copilot"])
    code, out, _ = run(repo, "sync")
    assert code == 0, out
    for f in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"):
        text = read(repo, f)
        assert text.startswith(HEADER)
        assert "- Use pnpm." in text
    assert "wrote 4" in out
    assert exists(repo, ".agents/samerules.lock")


def test_second_sync_is_noop(repo):
    project(repo)
    run(repo, "sync")
    code, out, _ = run(repo, "sync")
    assert code == 0 and "already in sync" in out


def test_scoped_rules_per_harness(repo):
    project(repo, rules={"main": "# Main\n\n- a\n", "api": API, "migrations": AUTO, "release": MANUAL})
    assert run(repo, "sync")[0] == 0
    agents = read(repo, "AGENTS.md")
    assert "## API handlers" in agents and "`src/api/**/*.ts`" in agents
    assert "_Use when relevant: When touching database migrations_" in agents
    assert "Release checklist" not in agents  # manual rules can't be invoked in a single file
    claude = read(repo, "CLAUDE.md")
    assert "API handlers" not in claude and "Migrations" in claude
    crule = read(repo, ".claude/rules/api.md")
    assert crule.startswith('---\npaths:\n  - "src/api/**/*.ts"\n  - "src/routes/*.ts"\n---\n')
    mdc = read(repo, ".cursor/rules/api.mdc")
    assert "globs: src/api/**/*.ts,src/routes/*.ts\nalwaysApply: false" in mdc
    assert "description: API handler rules" in mdc
    assert "alwaysApply: false" in read(repo, ".cursor/rules/release.mdc")
    assert "description: When touching" in read(repo, ".cursor/rules/migrations.mdc")
    # always rules reach Cursor/Windsurf through AGENTS.md, so no duplicate .mdc
    assert not exists(repo, ".cursor/rules/main.mdc")
    assert not exists(repo, ".windsurf/rules/main.md")
    assert "trigger: glob" in read(repo, ".windsurf/rules/api.md")
    assert "trigger: model_decision" in read(repo, ".windsurf/rules/migrations.md")
    assert "trigger: manual" in read(repo, ".windsurf/rules/release.md")
    assert 'applyTo: "src/api/**/*.ts,src/routes/*.ts"' in read(repo, ".github/instructions/api.instructions.md")


def test_cursor_gets_always_rules_without_agents_md(repo):
    project(repo, targets=["cursor", "windsurf"])
    run(repo, "sync")
    assert "alwaysApply: true" in read(repo, ".cursor/rules/main.mdc")
    assert "trigger: always_on" in read(repo, ".windsurf/rules/main.md")
    assert not exists(repo, "AGENTS.md")


def test_rules_md_alias_and_order(repo):
    project(repo, targets=["agents"], rules={"20-b": "B rule\n", "10-a": "A rule\n"})
    write(repo, ".agents/rules.md", "TOP\n")
    run(repo, "sync")
    t = read(repo, "AGENTS.md")
    assert t.index("TOP") < t.index("A rule") < t.index("B rule")


def test_rule_targets_filter(repo):
    project(repo, targets=["agents", "claude"], rules={"main": "shared\n", "c": "---\ntargets: claude\n---\nclaude only\n"})
    run(repo, "sync")
    assert "claude only" in read(repo, "CLAUDE.md")
    assert "claude only" not in read(repo, "AGENTS.md")


def test_skills_copied_only_where_needed(repo):
    project(repo, skills={"release": SKILL})
    p = write(repo, ".agents/skills/release/scripts/run.sh", "#!/bin/sh\necho hi\n")
    os.chmod(p, 0o755)
    write(repo, ".agents/skills/release/logo.png", b"\x89PNG\x00\xff")
    run(repo, "sync")
    assert read(repo, ".claude/skills/release/SKILL.md") == SKILL
    assert read(repo, ".github/skills/release/SKILL.md") == SKILL
    assert os.stat(os.path.join(str(repo), ".claude/skills/release/scripts/run.sh")).st_mode & stat.S_IXUSR
    with open(os.path.join(str(repo), ".claude/skills/release/logo.png"), "rb") as fh:
        assert fh.read() == b"\x89PNG\x00\xff"
    assert not exists(repo, ".cursor/skills") and not exists(repo, ".gemini/skills")


def test_invalid_skill_fails_check(repo):
    project(repo, skills={"Bad_Name": "---\nname: other\n---\nx\n"})
    code, out, _ = run(repo, "sync")
    assert code == 1
    assert "lowercase" in out and "must match the folder" in out and "description" in out
    code, out, _ = run(repo, "check")
    assert code == 1


def test_dry_run_writes_nothing(repo):
    project(repo)
    code, out, _ = run(repo, "sync", "--dry-run")
    assert code == 0 and "dry run: would write" in out
    assert not exists(repo, "AGENTS.md") and not exists(repo, ".agents/samerules.lock")


def test_targets_flag_override(repo):
    project(repo)
    run(repo, "sync", "-t", "claude")
    assert exists(repo, "CLAUDE.md") and not exists(repo, "AGENTS.md")


def test_unknown_target_is_usage_error(repo):
    project(repo, targets=["nope"])
    code, _, err = run(repo, "sync")
    assert code == 2 and "unknown target" in err


def test_aliases(repo):
    project(repo, targets=["devin", "vscode"])
    run(repo, "sync")
    assert exists(repo, ".windsurf/rules/main.md") and exists(repo, ".github/copilot-instructions.md")


def test_missing_source(repo):
    code, _, err = run(repo, "sync")
    assert code == 2 and "no .agents/ folder" in err


def test_root_found_from_subdirectory(repo):
    project(repo, targets=["agents"])
    sub = os.path.join(str(repo), "src", "deep")
    os.makedirs(sub)
    code, _, _ = run(sub, "sync")
    assert code == 0 and exists(repo, "AGENTS.md") and not exists(sub, "AGENTS.md")


def test_no_rules_no_files(repo):
    write(repo, ".agents/samerules.json", '{"targets": ["all"]}')
    code, out, err = run(repo, "sync")
    assert code == 0 and "has no rules" in err
    assert not exists(repo, "AGENTS.md")


def test_bad_rule_apply_warns(repo):
    project(repo, targets=["agents"], rules={"x": "---\napply: sometimes\n---\nX\n", "y": "---\napply: glob\n---\nY\n"})
    code, _, err = run(repo, "sync")
    assert code == 0 and "unknown apply" in err and "no globs" in err
    t = read(repo, "AGENTS.md")
    assert "X" in t and "Y" in t


def test_mcp_lock_records_hashes(repo):
    project(repo, targets=["claude"], mcp={"a": {"command": "x"}})
    run(repo, "sync")
    lock = json.loads(read(repo, ".agents/samerules.lock"))
    assert set(lock["files"]) == {"CLAUDE.md", ".mcp.json"}
