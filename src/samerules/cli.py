"""samerules command line."""

import argparse
import json
import os
import sys

from . import __version__, engine, importer
from .engine import CONFLICT, CREATE, DELETE, OK, UPDATE
from .source import ALL_TARGETS, CONFIG_FILE, SOURCE_DIR, SourceError, find_root, load
from .targets import TARGET_FILES

SYMBOL = {CREATE: "+", UPDATE: "~", DELETE: "-", CONFLICT: "!", OK: "="}
COLOR = {CREATE: "32", UPDATE: "33", DELETE: "35", CONFLICT: "31", OK: "2"}


class UI:
    def __init__(self, color):
        self.color = color

    def c(self, code, s):
        return "\033[%sm%s\033[0m" % (code, s) if self.color else s


def _use_color(choice, stream):
    if choice == "always":
        return True
    if choice == "never" or os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _load(args, ui):
    root = find_root(args.root)
    targets = args.targets.split(",") if getattr(args, "targets", None) else None
    src = load(root, targets)
    for w in src.warnings:
        print(ui.c("33", "warning: ") + w, file=sys.stderr)
    return src


def _summary(src, ui):
    parts = []
    for n, word in ((len(src.rules), "rule"), (len(src.skills), "skill"), (len(src.mcp), "MCP server")):
        parts.append("%d %s%s" % (n, word, "" if n == 1 else "s"))
    return "%s -> %s" % (", ".join(parts), ", ".join(src.targets))


def _print_items(items, ui, show_ok=False):
    width = max([len(i.path) for i in items] + [10])
    for it in items:
        if it.action == OK and not show_ok:
            continue
        sym = ui.c(COLOR[it.action], SYMBOL[it.action])
        print("  %s %s  %s" % (sym, it.path.ljust(width), ui.c("2" if it.action != CONFLICT else "31", it.reason)))


def _print_warnings(warnings, ui):
    for w in sorted(set(warnings)):
        print(ui.c("33", "warning: ") + w, file=sys.stderr)


def _print_errors(src, ui):
    for e in src.errors:
        print("  %s %s" % (ui.c("31", "!"), e))


def cmd_sync(args, ui):
    src = _load(args, ui)
    items, warnings = engine.plan(src, force=args.force)
    _print_warnings(warnings, ui)
    print("samerules: " + _summary(src, ui))
    _print_errors(src, ui)
    _print_items(items, ui, show_ok=args.verbose)
    n = {a: sum(1 for i in items if i.action == a) for a in SYMBOL}
    changes = n[CREATE] + n[UPDATE] + n[DELETE]
    if args.dry_run:
        print("dry run: would write %d, remove %d, %d up to date, %d conflict(s)"
              % (n[CREATE] + n[UPDATE], n[DELETE], n[OK], n[CONFLICT]))
        return 1 if n[CONFLICT] else 0
    engine.apply(src, items)
    if not changes and not n[CONFLICT]:
        print("everything already in sync (%d files)" % n[OK])
    else:
        print("wrote %d, removed %d, %d up to date%s" % (
            n[CREATE] + n[UPDATE], n[DELETE], n[OK],
            ui.c("31", ", %d conflict(s) left untouched" % n[CONFLICT]) if n[CONFLICT] else ""))
    return 1 if n[CONFLICT] or src.errors else 0


def cmd_check(args, ui):
    src = _load(args, ui)
    items, warnings = engine.plan(src)
    if not args.quiet:
        _print_warnings(warnings, ui)
    bad = [i for i in items if i.action != OK]
    labels = {CREATE: "missing", UPDATE: "out of date", DELETE: "stale (no longer generated)"}
    if not args.quiet:
        for it in bad:
            reason = it.reason if it.action in (CONFLICT, UPDATE) else labels[it.action]
            if it.action == CREATE and it.current is not None:
                reason = "managed section missing"
            print("  %s %s  %s" % (ui.c("31", "x"), it.path, reason))
        _print_errors(src, ui)
    problems = len(bad) + len(src.errors)
    if problems:
        if not args.quiet:
            print(ui.c("31", "%d problem(s): agent configs have drifted from .agents/" % problems)
                  + " - run `samerules diff` to see them, `samerules sync` to fix")
        return 1
    if not args.quiet:
        print(ui.c("32", "ok") + ": %d generated files match .agents/ (%s)" % (len(items), _summary(src, ui)))
    return 0


def cmd_diff(args, ui):
    src = _load(args, ui)
    items, warnings = engine.plan(src, force=True)
    _print_warnings(warnings, ui)
    any_diff = False
    for it in items:
        d = engine.unified(it)
        if not d:
            continue
        any_diff = True
        for line in d.splitlines(True):
            if line.startswith(("+++", "---")):
                sys.stdout.write(ui.c("1", line.rstrip("\n")) + "\n")
            elif line.startswith("+"):
                sys.stdout.write(ui.c("32", line.rstrip("\n")) + "\n")
            elif line.startswith("-"):
                sys.stdout.write(ui.c("31", line.rstrip("\n")) + "\n")
            elif line.startswith("@@"):
                sys.stdout.write(ui.c("36", line.rstrip("\n")) + "\n")
            else:
                sys.stdout.write(line)
    if not any_diff:
        print("no differences")
    return 1 if any_diff else 0


INIT_RULE = """# Project rules

<!-- Shared by every coding agent. Edit here, then run `samerules sync`. -->

- Describe how to build, test and lint this project.
- List the conventions agents keep getting wrong.
"""


def cmd_init(args, ui):
    root = os.path.abspath(args.root)
    src = os.path.join(root, SOURCE_DIR)
    if os.path.isdir(os.path.join(src, "rules")) or os.path.isfile(os.path.join(src, CONFIG_FILE)):
        print(".agents/ is already set up here", file=sys.stderr)
        return 2
    os.makedirs(os.path.join(src, "rules"), exist_ok=True)
    os.makedirs(os.path.join(src, "skills"), exist_ok=True)
    targets = args.targets.split(",") if args.targets else importer.detect_targets(root)
    from .source import normalize_targets
    targets = normalize_targets(targets)
    with open(os.path.join(src, "rules", "main.md"), "w", encoding="utf-8") as fh:
        fh.write(INIT_RULE)
    mp = os.path.join(src, "mcp.json")
    if not os.path.exists(mp):
        with open(mp, "w", encoding="utf-8") as fh:
            fh.write('{\n  "mcpServers": {}\n}\n')
    with open(os.path.join(src, CONFIG_FILE), "w", encoding="utf-8") as fh:
        json.dump({"targets": targets}, fh, indent=2)
        fh.write("\n")
    print("created .agents/ (rules/main.md, skills/, mcp.json, %s)" % CONFIG_FILE)
    print("targets: " + ", ".join(targets))
    print("next: edit .agents/rules/main.md, then run `samerules sync`")
    if any(os.path.exists(os.path.join(root, p)) for p in ("CLAUDE.md", "AGENTS.md", ".cursor", "GEMINI.md")):
        print(ui.c("33", "tip: ") + "you already have agent files; `samerules import` would have pulled them in")
    return 0


def cmd_import(args, ui):
    root = os.path.abspath(args.root)
    try:
        report = importer.run(root, force=args.force)
    except FileExistsError as e:
        print("samerules: %s" % e, file=sys.stderr)
        return 2
    print("imported into .agents/:")
    for line in report:
        if line.startswith("NOTE"):
            print("  " + ui.c("33", line))
        else:
            print("  " + line)
    print("next: `samerules diff` to review, then `samerules sync --force` to take over the existing files")
    return 0


def cmd_targets(args, ui):
    for t in ALL_TARGETS:
        print("  %-9s %s" % (t, ", ".join(TARGET_FILES[t])))
    print("skills in .agents/skills/ are read natively by Codex, Cursor, Gemini CLI, OpenCode and "
          "Windsurf/Devin; claude and copilot get a copy.")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="samerules",
        description="Keep AGENTS.md, CLAUDE.md, Cursor rules, skills and MCP configs in sync from one .agents/ folder.")
    p.add_argument("--version", action="version", version="samerules " + __version__)
    p.add_argument("-C", "--root", default=".", help="project directory (default: nearest folder with .agents/)")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    s = sub.add_parser("sync", help="generate every harness's files from .agents/")
    s.add_argument("-n", "--dry-run", action="store_true", help="show what would change, write nothing")
    s.add_argument("-f", "--force", action="store_true", help="overwrite hand-written or hand-edited files")
    s.add_argument("-v", "--verbose", action="store_true", help="also list files already up to date")
    s.add_argument("-t", "--targets", help="comma list overriding .agents/samerules.json")
    s.set_defaults(func=cmd_sync)

    c = sub.add_parser("check", help="exit 1 if any generated file drifted (for CI / pre-commit)")
    c.add_argument("-q", "--quiet", action="store_true")
    c.add_argument("-t", "--targets")
    c.set_defaults(func=cmd_check)

    d = sub.add_parser("diff", help="show what sync would change as a unified diff")
    d.add_argument("-t", "--targets")
    d.set_defaults(func=cmd_diff)

    i = sub.add_parser("init", help="create an empty .agents/ folder")
    i.add_argument("-t", "--targets", help="comma list (default: detected from the repo)")
    i.set_defaults(func=cmd_init)

    im = sub.add_parser("import", help="build .agents/ from existing CLAUDE.md, AGENTS.md, .cursor/rules, MCP configs...")
    im.add_argument("-f", "--force", action="store_true", help="import even if .agents/rules exists")
    im.set_defaults(func=cmd_import)

    t = sub.add_parser("targets", help="list supported agents and the files each one gets")
    t.set_defaults(func=cmd_targets)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    ui = UI(_use_color(args.color, sys.stdout))
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args, ui)
    except SourceError as e:
        print("samerules: %s" % e, file=sys.stderr)
        return 2
    except ValueError as e:
        print("samerules: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
