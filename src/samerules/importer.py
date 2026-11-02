"""Bootstrap .agents/ from the rules, skills and MCP configs already in a repo."""

import json
import os
import re
import shutil

from . import frontmatter, mcp
from .handlers import MARKER
from .source import CONFIG_FILE, DEFAULT_TARGETS, SKILL_NAME_RE, SOURCE_DIR

INSTRUCTION_FILES = [
    ("AGENTS.md", "agents"),
    ("CLAUDE.md", "claude"),
    (".claude/CLAUDE.md", "claude"),
    ("GEMINI.md", "gemini"),
    (".github/copilot-instructions.md", "copilot"),
    (".cursorrules", "cursor"),
    (".windsurfrules", "windsurf"),
]
SKILL_DIRS = [".claude/skills", ".github/skills", ".cursor/skills", ".opencode/skills",
              ".gemini/skills", ".devin/skills", ".windsurf/skills", ".codex/skills"]
MCP_FILES = [
    (".mcp.json", "mcpServers", "claude"),
    (".cursor/mcp.json", "mcpServers", "cursor"),
    (".vscode/mcp.json", "servers", "copilot"),
    (".gemini/settings.json", "mcpServers", "gemini"),
    ("opencode.json", "mcp", "opencode"),
    (".devin/mcp_config.json", "mcpServers", "windsurf"),
    (".codex/config.toml", "mcp_servers", "codex"),
]
DETECT = {
    "claude": ["CLAUDE.md", ".claude", ".mcp.json"],
    "cursor": [".cursor", ".cursorrules"],
    "codex": [".codex"],
    "gemini": ["GEMINI.md", ".gemini"],
    "opencode": ["opencode.json", "opencode.jsonc", ".opencode"],
    "copilot": [".github/copilot-instructions.md", ".github/instructions", ".vscode/mcp.json", ".github/skills"],
    "windsurf": [".windsurf", ".windsurfrules", ".devin"],
    "agents": ["AGENTS.md"],
}
_HEADER_RE = re.compile(r"^\s*<!--\s*" + re.escape(MARKER) + r".*?-->\s*\n?", re.S)


def detect_targets(root):
    found = [t for t, paths in DETECT.items() if any(os.path.exists(os.path.join(root, p)) for p in paths)]
    if not found:
        return list(DEFAULT_TARGETS)
    if "agents" not in found:
        found.insert(0, "agents")
    order = ["agents", "claude", "cursor", "codex", "gemini", "opencode", "copilot", "windsurf"]
    return [t for t in order if t in found]


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _strip_header(text):
    return _HEADER_RE.sub("", text, count=1)


def _norm(text):
    return re.sub(r"\s+", " ", _strip_header(text)).strip()


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "rule"


def _scoped_rules(root):
    """Yield (name, meta, body, origin) from per-rule files of every harness."""
    specs = [
        (".cursor/rules", (".mdc", ".md"), "cursor"),
        (".claude/rules", (".md",), "claude"),
        (".windsurf/rules", (".md",), "windsurf"),
        (".devin/rules", (".md",), "windsurf"),
        (".github/instructions", (".instructions.md",), "copilot"),
    ]
    for d, exts, kind in specs:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirs, files in os.walk(base):
            dirs.sort()
            for fn in sorted(files):
                ext = next((e for e in exts if fn.endswith(e)), None)
                if not ext:
                    continue
                p = os.path.join(dirpath, fn)
                meta, body = frontmatter.split(_read(p))
                yield _slug(fn[: -len(ext)]), _to_canonical_meta(meta, kind), _strip_header(body), os.path.relpath(p, root)


def _to_canonical_meta(meta, kind):
    out = {}
    desc = str(meta.get("description") or "").strip()
    if kind == "cursor":
        globs = frontmatter.as_list(meta.get("globs"))
        if meta.get("alwaysApply") is True:
            apply = "always"
        elif globs:
            apply = "glob"
        elif desc:
            apply = "auto"
        else:
            apply = "manual"
    elif kind == "claude":
        globs = frontmatter.as_list(meta.get("paths"))
        apply = "glob" if globs else "always"
    elif kind == "copilot":
        globs = frontmatter.as_list(meta.get("applyTo"))
        apply = "always" if globs in ([], ["**"], ["**/*"]) else "glob"
        if apply == "always":
            globs = []
    else:  # windsurf / devin
        globs = frontmatter.as_list(meta.get("globs"))
        trig = str(meta.get("trigger") or "").lower()
        apply = {"always_on": "always", "glob": "glob", "model_decision": "auto",
                 "agent": "auto", "manual": "manual"}.get(trig, "glob" if globs else "always")
    out["apply"] = apply
    if globs:
        out["globs"] = globs
    if desc:
        out["description"] = desc
    return out


def _rule_text(meta, body):
    pairs = []
    if meta.get("description"):
        pairs.append("description: %s" % frontmatter.quote(meta["description"]))
    if meta.get("apply", "always") != "always":
        pairs.append("apply: %s" % meta["apply"])
    if meta.get("globs"):
        pairs.append("globs:")
        pairs.extend("  - %s" % frontmatter.quote(g) for g in meta["globs"])
    head = ("---\n" + "\n".join(pairs) + "\n---\n\n") if pairs else ""
    return head + body.strip("\n") + "\n"


def _load_mcp(root, path, key, fmt, report):
    full = os.path.join(root, path)
    if not os.path.isfile(full):
        return {}
    if path.endswith(".toml"):
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            report.append("skipped %s: reading TOML needs Python 3.11+" % path)
            return {}
        try:
            with open(full, "rb") as fh:
                data = tomllib.load(fh)
        except Exception as e:  # noqa: BLE001 - any parse problem
            report.append("skipped %s: %s" % (path, e))
            return {}
    else:
        try:
            data = json.loads(_read(full))
        except ValueError:
            report.append("skipped %s: not plain JSON" % path)
            return {}
    servers = data.get(key) if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}
    out = {}
    for name, obj in servers.items():
        c = mcp.to_canonical(obj, {"opencode": "opencode", "codex": "codex", "gemini": "gemini"}.get(fmt, "json"))
        if c:
            out[name] = c
        else:
            report.append("skipped mcp server %r in %s: unrecognised shape" % (name, path))
    return out


def run(root, force=False):
    """Create .agents/ from existing files. Returns a list of report lines."""
    src = os.path.join(root, SOURCE_DIR)
    report = []
    if os.path.isdir(os.path.join(src, "rules")) and not force:
        raise FileExistsError(".agents/rules already exists; use --force to import over it")
    os.makedirs(os.path.join(src, "rules"), exist_ok=True)

    # 1. main instructions: first file wins, the rest are compared against it
    # the most complete file becomes rules/main.md (ties: AGENTS.md, CLAUDE.md, ...)
    found = []
    for rel, _kind in INSTRUCTION_FILES:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        text = _strip_header(_read(p))
        if re.fullmatch(r"\s*@AGENTS\.md\s*", text):
            report.append("%s just imports AGENTS.md, nothing extra to import" % rel)
            continue
        found.append((rel, text))
    found.sort(key=lambda f: -len(_norm(f[1])))
    main = None
    for rel, text in found:
        if main is None:
            main = (rel, text)
            with open(os.path.join(src, "rules", "main.md"), "w", encoding="utf-8") as fh:
                fh.write(text.strip("\n") + "\n")
            report.append("rules/main.md      <- %s" % rel)
        elif _norm(text) != _norm(main[1]):
            report.append("NOTE %s differs from %s (%d vs %d lines): review it and copy anything "
                          "missing into .agents/rules/" % (rel, main[0], len(text.splitlines()),
                                                          len(main[1].splitlines())))
        else:
            report.append("%s matches %s" % (rel, main[0]))

    # 2. per-rule files
    seen = {"main": main[1] if main else ""}
    for name, meta, body, origin in _scoped_rules(root):
        if any(_norm(body) == _norm(b) for b in seen.values()):
            continue
        if name in seen:
            report.append("NOTE skipped %s: a different rule named %r was already imported" % (origin, name))
            continue
        seen[name] = body
        with open(os.path.join(src, "rules", name + ".md"), "w", encoding="utf-8") as fh:
            fh.write(_rule_text(meta, body))
        report.append("rules/%s.md <- %s" % (name, origin))

    # 3. skills
    for d in SKILL_DIRS:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            sd = os.path.join(base, name)
            if not os.path.isfile(os.path.join(sd, "SKILL.md")):
                continue
            dest = os.path.join(src, "skills", name)
            if os.path.exists(dest):
                continue
            shutil.copytree(sd, dest)
            report.append("skills/%s/ <- %s/%s" % (name, d, name))
            if not SKILL_NAME_RE.match(name):
                report.append("NOTE skill %r has an invalid name; rename the folder (lowercase-hyphen)" % name)

    # 4. MCP servers: union, first definition wins
    servers, origin = {}, {}
    for rel, key, fmt in MCP_FILES:
        for name, s in _load_mcp(root, rel, key, fmt, report).items():
            if name not in servers:
                servers[name], origin[name] = s, rel
            elif json.dumps(s, sort_keys=True) != json.dumps(servers[name], sort_keys=True):
                report.append("NOTE mcp server %r in %s differs from %s; kept the %s version"
                              % (name, rel, origin[name], origin[name]))
    mp = os.path.join(src, "mcp.json")
    if servers and (force or not os.path.exists(mp)):
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": servers}, fh, indent=2)
            fh.write("\n")
        report.append("mcp.json           <- %d server(s) from %s" % (
            len(servers), ", ".join(sorted(set(origin.values())))))

    cfg = os.path.join(src, CONFIG_FILE)
    if force or not os.path.exists(cfg):
        targets = detect_targets(root)
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"targets": targets}, fh, indent=2)
            fh.write("\n")
        report.append("%s   targets: %s" % (CONFIG_FILE, ", ".join(targets)))
    if main is None and len(seen) == 1:
        report.append("no instruction files found; wrote an empty rules/ folder")
    return report
