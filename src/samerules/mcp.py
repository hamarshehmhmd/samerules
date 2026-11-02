"""Translate canonical MCP server definitions into each harness's dialect."""

import json
import re

from .handlers import TOML_BEGIN, TOML_END

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# how each harness spells "read environment variable NAME"
VAR_SYNTAX = {
    "claude": "${%s}",
    "cursor": "${env:%s}",
    "copilot": "${env:%s}",
    "opencode": "{env:%s}",
    "gemini": "${%s}",
    "windsurf": "${%s}",
}


def _vars(target, s):
    return VAR_RE.sub(lambda m: VAR_SYNTAX[target] % m.group(1), s)


def _vmap(target, d):
    return {k: _vars(target, v) for k, v in d.items()}


def servers_for(target, servers):
    return {n: s for n, s in servers.items() if s.get("targets") is None or target in s["targets"]}


def convert(target, name, s, warnings):
    """Return the harness-native object for one server (JSON targets only)."""
    stdio = "command" in s
    if stdio:
        cmd, args, env = s["command"], [_vars(target, a) for a in s["args"]], _vmap(target, s["env"])
        if target == "claude":
            o = {"type": "stdio", "command": cmd, "args": args}
        elif target == "copilot":
            o = {"type": "stdio", "command": cmd, "args": args}
        elif target == "opencode":
            o = {"type": "local", "command": [cmd] + args}
        else:  # cursor, gemini, windsurf
            o = {"command": cmd, "args": args}
        if env:
            o["environment" if target == "opencode" else "env"] = env
        if s.get("cwd"):
            if target in ("gemini", "opencode"):
                o["cwd"] = s["cwd"]
            else:
                warnings.append("%s: mcp server %r: 'cwd' is not supported there, dropped" % (target, name))
        if target == "opencode":
            o["enabled"] = True
    else:
        url, hdrs, kind = _vars(target, s["url"]), _vmap(target, s["headers"]), s["type"]
        if target in ("claude", "copilot"):
            o = {"type": kind, "url": url}
        elif target == "opencode":
            o = {"type": "remote", "url": url}
        elif target == "gemini":
            o = {"httpUrl": url} if kind == "http" else {"url": url}
        elif target == "windsurf":
            o = {"url": url}
            if kind == "sse":
                o["transport"] = "sse"
        else:  # cursor
            o = {"url": url}
        if hdrs:
            o["headers"] = hdrs
        if s["env"]:
            warnings.append("%s: mcp server %r: 'env' only applies to stdio servers, dropped" % (target, name))
        if target == "opencode":
            o["enabled"] = True
    o.update(s.get("overrides", {}).get(target, {}))
    return o


def json_servers(target, servers, warnings):
    return {n: convert(target, n, s, warnings) for n, s in servers_for(target, servers).items()}


# ---- Codex (TOML) --------------------------------------------------------

def toml_str(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif o < 0x20 or o == 0x7F:
            out.append("\\u%04x" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def toml_key(k):
    return k if re.match(r"^[A-Za-z0-9_-]+$", k) else toml_str(k)


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return toml_str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join("%s = %s" % (toml_key(k), toml_value(x)) for k, x in v.items()) + " }" if v else "{}"
    raise TypeError("can't write %r as TOML" % (v,))


def codex_block(servers, warnings):
    servers = servers_for("codex", servers)
    if not servers:
        return None
    lines = [TOML_BEGIN]
    for name, s in servers.items():
        t = {}
        sub = {}
        if "command" in s:
            t["command"] = s["command"]
            t["args"] = s["args"]
            if s.get("cwd"):
                t["cwd"] = s["cwd"]
            fwd, lit = [], {}
            for k, v in s["env"].items():
                m = VAR_RE.fullmatch(v)
                if m and m.group(1) == k:
                    fwd.append(k)
                else:
                    if VAR_RE.search(v):
                        warnings.append("codex: mcp server %r: env %s=%s is passed literally (Codex only "
                                        "forwards variables with the same name, e.g. %s=${%s})" % (name, k, v, k, k))
                    lit[k] = v
            if fwd:
                t["env_vars"] = fwd
            if lit:
                sub["env"] = lit
        else:
            if s["type"] == "sse":
                warnings.append("codex: mcp server %r skipped: Codex supports stdio and streamable HTTP, not SSE" % name)
                continue
            t["url"] = s["url"]
            plain, envh = {}, {}
            for k, v in s["headers"].items():
                bearer = re.fullmatch(r"Bearer \$\{([A-Za-z_][A-Za-z0-9_]*)\}", v)
                whole = VAR_RE.fullmatch(v)
                if k.lower() == "authorization" and bearer:
                    t["bearer_token_env_var"] = bearer.group(1)
                elif whole:
                    envh[k] = whole.group(1)
                else:
                    if VAR_RE.search(v):
                        warnings.append("codex: mcp server %r: header %s is passed literally (Codex can't "
                                        "expand variables inside a header value)" % (name, k))
                    plain[k] = v
            if plain:
                sub["http_headers"] = plain
            if envh:
                sub["env_http_headers"] = envh
        for k, v in s.get("overrides", {}).get("codex", {}).items():
            if isinstance(v, dict):
                sub[k] = v
            else:
                t[k] = v
        lines.append("[mcp_servers.%s]" % toml_key(name))
        lines.extend("%s = %s" % (toml_key(k), toml_value(v)) for k, v in t.items())
        for k, v in sub.items():
            lines.append("")
            lines.append("[mcp_servers.%s.%s]" % (toml_key(name), toml_key(k)))
            lines.extend("%s = %s" % (toml_key(kk), toml_value(vv)) for kk, vv in v.items())
        lines.append("")
    if len(lines) == 1:
        return None
    if lines[-1] == "":
        lines.pop()
    lines.append(TOML_END)
    return "\n".join(lines) + "\n"


# ---- reverse direction (import) ----------------------------------------

_BACK = [re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}"), re.compile(r"(?<!\$)\{env:([A-Za-z_][A-Za-z0-9_]*)\}")]


def _unvars(s):
    s = str(s)
    for rx in _BACK:
        s = rx.sub(lambda m: "${%s}" % m.group(1), s)
    return s


def to_canonical(obj, fmt):
    """Best-effort conversion of a harness server object back to canonical form."""
    if not isinstance(obj, dict):
        return None
    out = {}
    if fmt == "opencode":
        cmd = obj.get("command")
        if obj.get("type") == "remote" or obj.get("url"):
            out["url"] = _unvars(obj.get("url", ""))
            if obj.get("headers"):
                out["headers"] = {k: _unvars(v) for k, v in obj["headers"].items()}
        elif isinstance(cmd, list) and cmd:
            out["command"] = str(cmd[0])
            if cmd[1:]:
                out["args"] = [_unvars(a) for a in cmd[1:]]
            if obj.get("environment"):
                out["env"] = {k: _unvars(v) for k, v in obj["environment"].items()}
            if obj.get("cwd"):
                out["cwd"] = obj["cwd"]
        else:
            return None
        return out
    if fmt == "codex":
        if obj.get("command"):
            out["command"] = str(obj["command"])
            if obj.get("args"):
                out["args"] = [str(a) for a in obj["args"]]
            env = dict(obj.get("env") or {})
            for k in obj.get("env_vars") or []:
                if isinstance(k, str):
                    env[k] = "${%s}" % k
            if env:
                out["env"] = env
            if obj.get("cwd"):
                out["cwd"] = obj["cwd"]
        elif obj.get("url"):
            out["url"] = obj["url"]
            hdrs = dict(obj.get("http_headers") or {})
            for k, v in (obj.get("env_http_headers") or {}).items():
                hdrs[k] = "${%s}" % v
            if obj.get("bearer_token_env_var"):
                hdrs["Authorization"] = "Bearer ${%s}" % obj["bearer_token_env_var"]
            if hdrs:
                out["headers"] = hdrs
        else:
            return None
        return out
    # claude / cursor / vscode / gemini / devin
    url = obj.get("httpUrl") or obj.get("url") or obj.get("serverUrl")
    if obj.get("command"):
        out["command"] = str(obj["command"])
        if obj.get("args"):
            out["args"] = [_unvars(a) for a in obj["args"]]
        if obj.get("env"):
            out["env"] = {k: _unvars(v) for k, v in obj["env"].items()}
        if obj.get("cwd"):
            out["cwd"] = obj["cwd"]
    elif url:
        out["url"] = _unvars(url)
        sse = obj.get("type") == "sse" or obj.get("transport") == "sse" or (fmt == "gemini" and "httpUrl" not in obj)
        if sse:
            out["type"] = "sse"
        if obj.get("headers"):
            out["headers"] = {k: _unvars(v) for k, v in obj["headers"].items()}
    else:
        return None
    return out
