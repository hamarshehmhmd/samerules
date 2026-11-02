import subprocess
import sys

from helpers import project, run

from samerules import __version__
from samerules.cli import _use_color


def test_version(repo):
    code, out, _ = run(repo, "--version")
    assert code == 0 and __version__ in out


def test_help_without_command(repo):
    code, out, _ = run(repo)
    assert code == 2 and "sync" in out


def test_targets_listing(repo):
    code, out, _ = run(repo, "targets")
    assert code == 0 and ".cursor/rules/<rule>.mdc" in out and "opencode" in out


def test_verbose_lists_ok(repo):
    project(repo, targets=["agents"])
    run(repo, "sync")
    code, out, _ = run(repo, "sync", "-v")
    assert "= AGENTS.md" in out


def test_color_choice(monkeypatch):
    class T:
        def isatty(self):
            return True
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert _use_color("always", None) and not _use_color("never", T())
    assert _use_color("auto", T())
    monkeypatch.setenv("NO_COLOR", "1")
    assert not _use_color("auto", T())


def test_color_output(repo):
    project(repo, targets=["agents"])
    from helpers import io, redirect_stdout
    from samerules.cli import main
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--color", "always", "-C", str(repo), "sync"])
    assert "\033[32m+\033[0m" in buf.getvalue()


def test_module_entry_point(repo):
    project(repo, targets=["agents"])
    r = subprocess.run([sys.executable, "-m", "samerules", "-C", str(repo), "check"], capture_output=True, text=True,
                       env={"PYTHONPATH": __import__("os").path.dirname(__import__("samerules").__file__) + "/..", "PATH": ""})
    assert r.returncode == 1 and "missing" in r.stdout
