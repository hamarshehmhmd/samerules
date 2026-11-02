import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout

from samerules.cli import main


def write(root, rel, text):
    p = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mode = "wb" if isinstance(text, bytes) else "w"
    with open(p, mode, **({} if isinstance(text, bytes) else {"encoding": "utf-8"})) as fh:
        fh.write(text)
    return p


def read(root, rel):
    with open(os.path.join(str(root), *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def exists(root, rel):
    return os.path.exists(os.path.join(str(root), *rel.split("/")))


def run(root, *args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main(["--color", "never", "-C", str(root)] + list(args))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def project(root, targets=("all",), rules=None, mcp=None, skills=None):
    write(root, ".agents/samerules.json", json.dumps({"targets": list(targets)}))
    for name, text in (rules or {"main": "# Project rules\n\n- Use pnpm.\n"}).items():
        write(root, ".agents/rules/%s.md" % name, text)
    if mcp is not None:
        write(root, ".agents/mcp.json", json.dumps({"mcpServers": mcp}))
    for name, text in (skills or {}).items():
        write(root, ".agents/skills/%s/SKILL.md" % name, text)
    return root
