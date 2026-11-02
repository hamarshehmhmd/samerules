import json
import sys

import pytest
from helpers import exists, project, read, run, write

from samerules import mcp as m
from samerules.handlers import JsonKey, MergeError, TomlBlock

SERVERS = {
    "github": {"url": "https://api.githubcopilot.com/mcp/", "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}},
    "pg": {"command": "npx", "args": ["-y", "server-postgres"], "env": {"DATABASE_URL": "${DATABASE_URL}"}},
}


def j(repo, rel):
    return json.loads(read(repo, rel))


def test_all_mcp_files(repo):
    project(repo, mcp=SERVERS)
    assert run(repo, "sync")[0] == 0
    claude = j(repo, ".mcp.json")["mcpServers"]
    assert claude["pg"] == {"type": "stdio", "command": "npx", "args": ["-y", "server-postgres"],
                            "env": {"DATABASE_URL": "${DATABASE_URL}"}}
    assert claude["github"]["type"] == "http"
    cursor = j(repo, ".cursor/mcp.json")["mcpServers"]
    assert cursor["pg"]["env"]["DATABASE_URL"] == "${env:DATABASE_URL}"
    assert cursor["github"] == {"url": "https://api.githubcopilot.com/mcp/",
                                "headers": {"Authorization": "Bearer ${env:GITHUB_TOKEN}"}}
    vs = j(repo, ".vscode/mcp.json")
    assert set(vs) == {"servers"} and vs["servers"]["pg"]["type"] == "stdio"
    gem = j(repo, ".gemini/settings.json")["mcpServers"]
    assert gem["github"]["httpUrl"] == "https://api.githubcopilot.com/mcp/"
    oc = j(repo, "opencode.json")
    assert oc["$schema"] == "https://opencode.ai/config.json"
    assert oc["mcp"]["pg"] == {"type": "local", "command": ["npx", "-y", "server-postgres"],
                               "environment": {"DATABASE_URL": "{env:DATABASE_URL}"}, "enabled": True}
    assert oc["mcp"]["github"]["type"] == "remote"
    assert j(repo, ".devin/mcp_config.json")["mcpServers"]["pg"]["command"] == "npx"
    toml = read(repo, ".codex/config.toml")
    assert 'bearer_token_env_var = "GITHUB_TOKEN"' in toml and 'env_vars = ["DATABASE_URL"]' in toml


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib needs 3.11")
def test_codex_toml_parses_and_keeps_user_config(repo):
    import tomllib
    project(repo, targets=["codex"], mcp=dict(SERVERS, weird={"command": "x y", "env": {"A": "lit\"q", "B": "${OTHER}"},
                                                              "overrides": {"codex": {"startup_timeout_sec": 20, "tools": {"a": True}}}}))
    write(repo, ".codex/config.toml", 'model = "gpt-5"\n\n[mcp_servers.mine]\ncommand = "keep"\n')
    code, _, err = run(repo, "sync")
    assert code == 0 and "passed literally" in err
    data = tomllib.loads(read(repo, ".codex/config.toml"))
    assert data["model"] == "gpt-5" and data["mcp_servers"]["mine"]["command"] == "keep"
    w = data["mcp_servers"]["weird"]
    assert w["env"] == {"A": 'lit"q', "B": "${OTHER}"} and w["startup_timeout_sec"] == 20 and w["tools"] == {"a": True}
    # removing all servers removes only our block
    write(repo, ".agents/mcp.json", '{"mcpServers": {}}')
    assert run(repo, "sync")[0] == 0
    assert tomllib.loads(read(repo, ".codex/config.toml")) == {"model": "gpt-5", "mcp_servers": {"mine": {"command": "keep"}}}


def test_codex_duplicate_table_conflict(repo):
    project(repo, targets=["codex"], mcp={"pg": SERVERS["pg"]})
    write(repo, ".codex/config.toml", "[mcp_servers.pg]\ncommand = \"old\"\n")
    code, out, _ = run(repo, "sync")
    assert code == 1 and "already defines [mcp_servers.pg]" in out
    assert run(repo, "sync", "--force")[0] == 0
    t = read(repo, ".codex/config.toml")
    assert "old" not in t and t.count("[mcp_servers.pg]") == 1


def test_codex_headers_and_sse(repo):
    project(repo, targets=["codex"], mcp={
        "h": {"url": "https://x", "headers": {"X-Key": "${KEY}", "X-Team": "core", "X-Mix": "a-${B}"}},
        "s": {"url": "https://y", "type": "sse"}})
    code, _, err = run(repo, "sync")
    t = read(repo, ".codex/config.toml")
    assert "[mcp_servers.h.env_http_headers]\nX-Key = \"KEY\"" in t
    assert "[mcp_servers.h.http_headers]" in t and "X-Team" in t
    assert "mcp_servers.s" not in t and "not SSE" in err and "can't expand" in err


def test_gemini_merge_preserves_settings(repo):
    project(repo, targets=["gemini"], mcp={"pg": SERVERS["pg"]})
    write(repo, ".gemini/settings.json", '{"theme": "GitHub", "mcp": {"allowed": ["pg"]}}')
    run(repo, "sync")
    data = j(repo, ".gemini/settings.json")
    assert data["theme"] == "GitHub" and data["mcp"] == {"allowed": ["pg"]} and "pg" in data["mcpServers"]
    assert run(repo, "check")[0] == 0
    # hand edit inside our key -> conflict, edit outside -> fine
    data["theme"] = "Dark"
    write(repo, ".gemini/settings.json", json.dumps(data))
    assert run(repo, "check")[0] == 0
    data["mcpServers"]["pg"]["command"] = "bunx"
    write(repo, ".gemini/settings.json", json.dumps(data))
    code, out, _ = run(repo, "sync")
    assert code == 1 and "edited by hand" in out


def test_gemini_existing_hand_written_servers_conflict(repo):
    project(repo, targets=["gemini"], mcp={"pg": SERVERS["pg"]})
    write(repo, ".gemini/settings.json", '{"mcpServers": {"other": {"command": "z"}}}')
    code, out, _ = run(repo, "sync")
    assert code == 1 and "weren't written by samerules" in out


def test_jsonc_refused(repo):
    project(repo, targets=["opencode"], mcp={"pg": SERVERS["pg"]})
    write(repo, "opencode.json", '{\n  // comment\n  "model": "x"\n}\n')
    code, out, _ = run(repo, "sync", "--force")
    assert code == 1 and "not plain JSON" in out


def test_opencode_file_removed_when_only_ours(repo):
    project(repo, targets=["opencode"], mcp={"pg": SERVERS["pg"]})
    run(repo, "sync")
    write(repo, ".agents/mcp.json", '{"mcpServers": {}}')
    run(repo, "sync")
    assert not exists(repo, "opencode.json")


def test_server_targets_cwd_overrides(repo):
    project(repo, targets=["claude", "gemini", "cursor"], mcp={
        "only": {"command": "a", "targets": ["gemini"], "cwd": "tools", "overrides": {"gemini": {"trust": True}}},
        "both": {"command": "b", "cwd": "x"}})
    code, _, err = run(repo, "sync")
    assert code == 0
    gem = j(repo, ".gemini/settings.json")["mcpServers"]
    assert gem["only"] == {"command": "a", "args": [], "cwd": "tools", "trust": True}
    assert "only" not in j(repo, ".mcp.json")["mcpServers"]
    assert "'cwd' is not supported" in err


def test_sse_and_env_on_remote(repo):
    project(repo, targets=["claude", "gemini", "windsurf", "copilot"], mcp={"s": {"url": "https://s", "type": "sse", "env": {"A": "1"}}})
    code, _, err = run(repo, "sync")
    assert j(repo, ".mcp.json")["mcpServers"]["s"] == {"type": "sse", "url": "https://s"}
    assert j(repo, ".gemini/settings.json")["mcpServers"]["s"] == {"url": "https://s"}
    assert j(repo, ".devin/mcp_config.json")["mcpServers"]["s"]["transport"] == "sse"
    assert "only applies to stdio" in err


@pytest.mark.parametrize("bad,msg", [
    ({"x": {}}, "exactly one of"),
    ({"x": {"command": "a", "url": "b"}}, "exactly one of"),
    ({"x": {"command": "a", "args": "nope"}}, "'args' must be a list"),
    ({"x": {"url": "a", "type": "ws"}}, "type must be"),
    ({"x": {"url": "a", "headers": []}}, "'headers' must be"),
    ({"x": {"command": "a", "env": []}}, "'env' must be"),
    ({"x": {"command": "a", "targets": ["nope"]}}, "unknown target"),
    ({"x": "str"}, "must be an object"),
])
def test_invalid_servers(repo, bad, msg):
    project(repo, targets=["claude"], mcp=bad)
    code, out, _ = run(repo, "check")
    assert code == 1 and msg in out


def test_unknown_server_key_warns(repo):
    project(repo, targets=["claude"], mcp={"x": {"command": "a", "timeout": 5}})
    _, _, err = run(repo, "sync")
    assert "unknown key 'timeout'" in err


def test_bad_mcp_json(repo):
    project(repo, targets=["claude"])
    write(repo, ".agents/mcp.json", "{oops")
    code, _, err = run(repo, "sync")
    assert code == 2 and "not valid JSON" in err
    write(repo, ".agents/mcp.json", "[]")
    assert run(repo, "sync")[0] == 2


def test_toml_helpers():
    assert m.toml_str('a"b\\c\n\x01é') == '"a\\"b\\\\c\\n\\u0001é"'
    assert m.toml_key("a.b") == '"a.b"' and m.toml_key("a_b-1") == "a_b-1"
    assert m.toml_value([1, True, 2.5, {"k": "v"}, {}]) == '[1, true, 2.5, { k = "v" }, {}]'
    with pytest.raises(TypeError):
        m.toml_value(None)


def test_toml_block_errors():
    tb = TomlBlock(["a"])
    with pytest.raises(MergeError):
        tb.extract(b"# >>> samerules start\n[x]\n")
    assert tb.render(None, None) is None
    assert tb.render(b"model = 1", "# >>> samerules\n# <<< samerules <<<\n").decode().startswith("model = 1\n\n# >>>")


def test_json_key_errors():
    jk = JsonKey("k")
    with pytest.raises(MergeError):
        jk.extract(b"[1]")
    assert jk.extract(b"  ") is None
    assert jk.render(b"{}", None) is None


def test_to_canonical_round_trips():
    assert m.to_canonical({"type": "local", "command": ["npx", "-y", "p"], "environment": {"A": "{env:A}"}}, "opencode") == \
        {"command": "npx", "args": ["-y", "p"], "env": {"A": "${A}"}}
    assert m.to_canonical({"type": "remote", "url": "u", "headers": {"H": "{env:T}"}}, "opencode") == {"url": "u", "headers": {"H": "${T}"}}
    assert m.to_canonical({"command": "c", "env_vars": ["T"], "env": {"X": "1"}, "cwd": "d"}, "codex") == \
        {"command": "c", "env": {"X": "1", "T": "${T}"}, "cwd": "d"}
    assert m.to_canonical({"url": "u", "bearer_token_env_var": "T", "env_http_headers": {"K": "V"}}, "codex") == \
        {"url": "u", "headers": {"K": "${V}", "Authorization": "Bearer ${T}"}}
    assert m.to_canonical({"httpUrl": "u"}, "gemini") == {"url": "u"}
    assert m.to_canonical({"url": "u"}, "gemini") == {"url": "u", "type": "sse"}
    assert m.to_canonical({"type": "stdio", "command": "c", "args": ["${env:A}"]}, "json") == {"command": "c", "args": ["${A}"]}
    assert m.to_canonical({"nothing": 1}, "json") is None
    assert m.to_canonical("x", "json") is None
    assert m.to_canonical({"type": "local"}, "opencode") is None
    assert m.to_canonical({}, "codex") is None
