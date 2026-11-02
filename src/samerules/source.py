"""Load the canonical .agents/ folder: rules, skills, MCP servers, config."""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import frontmatter

SOURCE_DIR = ".agents"
CONFIG_FILE = "samerules.json"
LOCK_FILE = "samerules.lock"

ALL_TARGETS = ["agents", "claude", "cursor", "codex", "gemini", "opencode", "copilot", "windsurf"]
TARGET_ALIASES = {"devin": "windsurf", "vscode": "copilot", "agents.md": "agents", "agents-md": "agents"}
DEFAULT_TARGETS = ["agents", "claude", "cursor", "copilot", "gemini"]
APPLY_MODES = ("always", "glob", "auto", "manual")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class SourceError(Exception):
    """The .agents/ folder is missing or invalid in a way we can't work around."""


@dataclass
class Rule:
    name: str
    body: str
    apply: str = "always"
    globs: List[str] = field(default_factory=list)
    description: str = ""
    targets: Optional[List[str]] = None
    path: str = ""

    @property
    def title(self):
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
            if line.strip():
                break
        return self.name.replace("-", " ").replace("_", " ").strip().capitalize()

    def body_without_title(self):
        lines = self.body.strip("\n").splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        return "\n".join(lines).strip("\n")

    def for_target(self, target):
        return self.targets is None or target in self.targets


@dataclass
class Skill:
    name: str
    path: str  # absolute dir
    files: List[str]  # posix paths relative to the skill dir
    description: str = ""


@dataclass
class Source:
    root: str
    rules: List[Rule]
    skills: List[Skill]
    mcp: Dict[str, dict]
    targets: List[str]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def normalize_targets(names):
    out = []
    for raw in names:
        n = TARGET_ALIASES.get(raw.strip().lower(), raw.strip().lower())
        if n == "all":
            for t in ALL_TARGETS:
                if t not in out:
                    out.append(t)
            continue
        if n not in ALL_TARGETS:
            raise SourceError("unknown target %r (known: %s)" % (raw, ", ".join(ALL_TARGETS)))
        if n not in out:
            out.append(n)
    return out


def find_root(start):
    """Nearest ancestor (inclusive) containing .agents/, else ``start``."""
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, SOURCE_DIR)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start)
        cur = parent


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_rule(path, name, warnings):
    meta, body = frontmatter.split(_read(path))
    rel = os.path.relpath(path)
    globs = frontmatter.as_list(meta.get("globs", meta.get("paths", meta.get("applyTo"))))
    description = str(meta.get("description") or "").strip()
    apply = str(meta.get("apply") or "").strip().lower()
    if not apply:
        if meta.get("alwaysApply") is True:
            apply = "always"
        elif globs:
            apply = "glob"
        else:
            apply = "always"
    if apply not in APPLY_MODES:
        warnings.append("%s: unknown apply %r, treating as 'always'" % (rel, apply))
        apply = "always"
    if apply == "glob" and not globs:
        warnings.append("%s: apply: glob but no globs, treating as 'always'" % rel)
        apply = "always"
    if apply == "auto" and not description:
        warnings.append("%s: apply: auto needs a description so agents know when to use it" % rel)
    targets = meta.get("targets")
    if targets is not None:
        targets = normalize_targets(frontmatter.as_list(targets))
    return Rule(name=name, body=body.strip("\n") + "\n", apply=apply, globs=globs,
                description=description, targets=targets, path=path)


def load_rules(src, warnings):
    rules = []
    single = os.path.join(src, "rules.md")
    if os.path.isfile(single):
        rules.append(_load_rule(single, "rules", warnings))
    rdir = os.path.join(src, "rules")
    if os.path.isdir(rdir):
        for fn in sorted(os.listdir(rdir)):
            p = os.path.join(rdir, fn)
            if fn.endswith(".md") and os.path.isfile(p):
                name = fn[:-3]
                if any(r.name == name for r in rules):
                    warnings.append("rule %r defined twice; using the first" % name)
                    continue
                rules.append(_load_rule(p, name, warnings))
    return rules


def load_skills(src, errors, warnings):
    skills = []
    sdir = os.path.join(src, "skills")
    if not os.path.isdir(sdir):
        return skills
    for name in sorted(os.listdir(sdir)):
        d = os.path.join(sdir, name)
        if not os.path.isdir(d) or name.startswith("."):
            continue
        skill_md = os.path.join(d, "SKILL.md")
        if not os.path.isfile(skill_md):
            warnings.append("skill %s/ has no SKILL.md, skipped" % name)
            continue
        meta, _ = frontmatter.split(_read(skill_md))
        if not SKILL_NAME_RE.match(name) or len(name) > 64:
            errors.append("skill %r: name must be lowercase letters, digits and hyphens "
                          "(max 64), or agents silently skip it" % name)
        if meta.get("name") != name:
            errors.append("skill %r: SKILL.md 'name' is %r, it must match the folder name"
                          % (name, meta.get("name")))
        desc = str(meta.get("description") or "").strip()
        if not desc:
            errors.append("skill %r: SKILL.md needs a 'description'" % name)
        files = []
        for base, dirs, fns in os.walk(d):
            dirs[:] = sorted(x for x in dirs if x not in ("__pycache__", ".git"))
            for fn in sorted(fns):
                if fn in (".DS_Store",) or fn.endswith(".pyc"):
                    continue
                files.append(os.path.relpath(os.path.join(base, fn), d).replace(os.sep, "/"))
        skills.append(Skill(name=name, path=d, files=files, description=desc))
    return skills


_SERVER_KEYS = {"command", "args", "env", "cwd", "url", "type", "headers", "targets", "overrides", "description"}


def validate_server(name, srv, errors, warnings):
    if not isinstance(srv, dict):
        errors.append("mcp server %r must be an object" % name)
        return None
    has_cmd, has_url = "command" in srv, "url" in srv
    if has_cmd == has_url:
        errors.append("mcp server %r needs exactly one of 'command' (stdio) or 'url' (remote)" % name)
        return None
    for k in sorted(set(srv) - _SERVER_KEYS):
        warnings.append("mcp server %r: unknown key %r ignored (use 'overrides' for "
                        "harness-specific settings)" % (name, k))
    out = {}
    if has_cmd:
        out["command"] = str(srv["command"])
        args = srv.get("args", [])
        if not isinstance(args, list):
            errors.append("mcp server %r: 'args' must be a list" % name)
            return None
        out["args"] = [str(a) for a in args]
        if srv.get("cwd"):
            out["cwd"] = str(srv["cwd"])
    else:
        out["url"] = str(srv["url"])
        t = str(srv.get("type") or "http").lower()
        if t in ("streamable-http", "streamablehttp", "remote"):
            t = "http"
        if t not in ("http", "sse"):
            errors.append("mcp server %r: type must be 'http' or 'sse' for url servers" % name)
            return None
        out["type"] = t
        hdrs = srv.get("headers")
        hdrs = {} if hdrs is None else hdrs
        if not isinstance(hdrs, dict):
            errors.append("mcp server %r: 'headers' must be an object" % name)
            return None
        out["headers"] = {str(k): str(v) for k, v in hdrs.items()}
    env = srv.get("env")
    env = {} if env is None else env
    if not isinstance(env, dict):
        errors.append("mcp server %r: 'env' must be an object" % name)
        return None
    out["env"] = {str(k): str(v) for k, v in env.items()}
    if srv.get("targets") is not None:
        try:
            out["targets"] = normalize_targets(frontmatter.as_list(srv["targets"]))
        except SourceError as e:
            errors.append("mcp server %r: %s" % (name, e))
            return None
    ov = srv.get("overrides")
    ov = {} if ov is None else ov
    if not isinstance(ov, dict):
        errors.append("mcp server %r: 'overrides' must be an object" % name)
        return None
    out["overrides"] = {TARGET_ALIASES.get(k, k): v for k, v in ov.items()}
    return out


def load_mcp(src, errors, warnings):
    p = os.path.join(src, "mcp.json")
    if not os.path.isfile(p):
        return {}
    try:
        data = json.loads(_read(p))
    except ValueError as e:
        raise SourceError(".agents/mcp.json is not valid JSON: %s" % e)
    servers = data.get("mcpServers", data.get("servers", {})) if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise SourceError(".agents/mcp.json must look like {\"mcpServers\": {...}}")
    out = {}
    for name in servers:
        s = validate_server(name, servers[name], errors, warnings)
        if s is not None:
            out[name] = s
    return out


def load_config(src):
    p = os.path.join(src, CONFIG_FILE)
    if not os.path.isfile(p):
        return {}
    try:
        data = json.loads(_read(p))
    except ValueError as e:
        raise SourceError(".agents/%s is not valid JSON: %s" % (CONFIG_FILE, e))
    if not isinstance(data, dict):
        raise SourceError(".agents/%s must be a JSON object" % CONFIG_FILE)
    return data


def load(root, targets_override=None):
    src = os.path.join(root, SOURCE_DIR)
    if not os.path.isdir(src):
        raise SourceError("no .agents/ folder in %s (run `samerules init` or `samerules import`)" % root)
    errors, warnings = [], []
    cfg = load_config(src)
    if targets_override:
        targets = normalize_targets(targets_override)
    else:
        targets = normalize_targets(cfg.get("targets") or ALL_TARGETS)
    rules = load_rules(src, warnings)
    skills = load_skills(src, errors, warnings)
    mcp = load_mcp(src, errors, warnings)
    if not rules and not skills and not mcp:
        warnings.append(".agents/ has no rules, skills or mcp.json yet")
    return Source(root=root, rules=rules, skills=skills, mcp=mcp, targets=targets,
                  errors=errors, warnings=warnings)
