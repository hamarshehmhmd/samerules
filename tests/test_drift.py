import json
import os

from helpers import exists, project, read, run, write


def test_check_clean(repo):
    project(repo)
    run(repo, "sync")
    code, out, _ = run(repo, "check")
    assert code == 0 and out.startswith("ok:")


def test_check_missing_before_sync(repo):
    project(repo, targets=["agents"])
    code, out, _ = run(repo, "check")
    assert code == 1 and "AGENTS.md  missing" in out


def test_check_source_changed(repo):
    project(repo, targets=["agents"])
    run(repo, "sync")
    write(repo, ".agents/rules/main.md", "# Project rules\n\n- Use bun.\n")
    code, out, _ = run(repo, "check")
    assert code == 1 and "out of date: .agents/ changed" in out


def test_check_hand_edit(repo):
    project(repo, targets=["agents", "claude"])
    run(repo, "sync")
    write(repo, "CLAUDE.md", read(repo, "CLAUDE.md") + "- sneaky edit\n")
    code, out, _ = run(repo, "check")
    assert code == 1 and "CLAUDE.md" in out and "edited by hand" in out


def test_check_quiet(repo):
    project(repo, targets=["agents"])
    code, out, err = run(repo, "check", "-q")
    assert code == 1 and out == "" and err == ""


def test_sync_refuses_to_clobber_hand_edit(repo):
    project(repo, targets=["claude"])
    run(repo, "sync")
    edited = read(repo, "CLAUDE.md") + "- keep me\n"
    write(repo, "CLAUDE.md", edited)
    code, out, _ = run(repo, "sync")
    assert code == 1 and "use --force" in out
    assert read(repo, "CLAUDE.md") == edited
    code, out, _ = run(repo, "sync", "--force")
    assert code == 0 and "keep me" not in read(repo, "CLAUDE.md")
    assert run(repo, "check")[0] == 0


def test_sync_refuses_hand_written_file(repo):
    project(repo, targets=["agents"])
    write(repo, "AGENTS.md", "# my own notes\n")
    code, out, _ = run(repo, "sync")
    assert code == 1 and "hand-written file" in out
    assert read(repo, "AGENTS.md") == "# my own notes\n"


def test_identical_existing_file_is_adopted(repo):
    project(repo, targets=["agents"])
    run(repo, "sync")
    text = read(repo, "AGENTS.md")
    os.remove(os.path.join(str(repo), ".agents/samerules.lock"))
    write(repo, "AGENTS.md", text)
    code, out, _ = run(repo, "sync")
    assert code == 0 and "already in sync" in out
    assert "AGENTS.md" in json.loads(read(repo, ".agents/samerules.lock"))["files"]


def test_marked_file_without_lock_is_updated(repo):
    # e.g. a fresh clone where someone forgot to commit the lock
    project(repo, targets=["agents"])
    run(repo, "sync")
    os.remove(os.path.join(str(repo), ".agents/samerules.lock"))
    write(repo, ".agents/rules/main.md", "changed\n")
    code, _, _ = run(repo, "sync")
    assert code == 0 and "changed" in read(repo, "AGENTS.md")


def test_partial_conflict_still_writes_others(repo):
    project(repo, targets=["agents", "gemini"])
    write(repo, "GEMINI.md", "hand written\n")
    code, out, _ = run(repo, "sync")
    assert code == 1 and exists(repo, "AGENTS.md")
    assert read(repo, "GEMINI.md") == "hand written\n"
    assert "1 conflict(s) left untouched" in out


def test_stale_files_removed(repo):
    project(repo, rules={"main": "m\n", "api": "---\nglobs: src/**\n---\napi\n"}, targets=["cursor", "claude"])
    run(repo, "sync")
    assert exists(repo, ".cursor/rules/api.mdc")
    os.remove(os.path.join(str(repo), ".agents/rules/api.md"))
    code, out, _ = run(repo, "check")
    assert code == 1 and "stale" in out
    code, out, _ = run(repo, "sync")
    assert code == 0 and "removed 2" in out
    assert not exists(repo, ".cursor/rules/api.mdc") and not exists(repo, ".claude/rules")
    assert exists(repo, ".cursor/rules/main.mdc")


def test_stale_but_edited_is_conflict(repo):
    project(repo, rules={"main": "m\n", "api": "---\nglobs: src/**\n---\napi\n"}, targets=["cursor"])
    run(repo, "sync")
    write(repo, ".cursor/rules/api.mdc", "my edit\n")
    os.remove(os.path.join(str(repo), ".agents/rules/api.md"))
    code, out, _ = run(repo, "sync")
    assert code == 1 and exists(repo, ".cursor/rules/api.mdc")
    assert run(repo, "sync", "--force")[0] == 0
    assert not exists(repo, ".cursor/rules/api.mdc")


def test_target_removed_from_config_cleans_up(repo):
    project(repo, targets=["agents", "gemini"])
    run(repo, "sync")
    write(repo, ".agents/samerules.json", '{"targets": ["agents"]}')
    code, out, _ = run(repo, "sync")
    assert code == 0 and not exists(repo, "GEMINI.md")


def test_user_skill_left_alone(repo):
    project(repo, targets=["claude"], skills={"release": "---\nname: release\ndescription: d\n---\nx\n"})
    write(repo, ".claude/skills/personal/SKILL.md", "mine\n")
    run(repo, "sync")
    os.remove(os.path.join(str(repo), ".agents/skills/release/SKILL.md"))
    os.rmdir(os.path.join(str(repo), ".agents/skills/release"))
    run(repo, "sync")
    assert not exists(repo, ".claude/skills/release")
    assert read(repo, ".claude/skills/personal/SKILL.md") == "mine\n"


def test_diff_shows_changes(repo):
    project(repo, targets=["agents"])
    run(repo, "sync")
    write(repo, ".agents/rules/main.md", "# Project rules\n\n- Use bun.\n")
    code, out, _ = run(repo, "diff")
    assert code == 1
    assert "--- a/AGENTS.md" in out and "-- Use pnpm." in out and "+- Use bun." in out
    assert "Use pnpm" in read(repo, "AGENTS.md")  # diff never writes


def test_diff_new_file_and_conflict(repo):
    project(repo, targets=["agents", "claude"])
    write(repo, "CLAUDE.md", "mine\n")
    code, out, _ = run(repo, "diff")
    assert code == 1 and "--- /dev/null" in out and "-mine" in out


def test_diff_clean(repo):
    project(repo)
    run(repo, "sync")
    code, out, _ = run(repo, "diff")
    assert code == 0 and "no differences" in out


def test_symlink_and_directory_conflicts(repo):
    project(repo, targets=["agents", "claude"])
    os.makedirs(os.path.join(str(repo), "CLAUDE.md"))
    write(repo, "elsewhere.md", "x\n")
    os.symlink(os.path.join(str(repo), "elsewhere.md"), os.path.join(str(repo), "AGENTS.md"))
    code, out, _ = run(repo, "sync", "--force")
    assert code == 1 and "symlink" in out and "is a directory" in out
    assert read(repo, "elsewhere.md") == "x\n"


def test_lock_outside_paths_ignored(repo):
    project(repo, targets=["agents"])
    write(repo, ".agents/samerules.lock", json.dumps({"files": {"../evil.txt": "abc"}}))
    code, _, err = run(repo, "sync")
    assert code == 2 and "outside the project" in err


def test_corrupt_lock_treated_as_empty(repo):
    project(repo, targets=["agents"])
    write(repo, ".agents/samerules.lock", "{nope")
    assert run(repo, "sync")[0] == 0
