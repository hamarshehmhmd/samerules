"""Render the narrated demo video: real command output + edge-tts narration.

Usage: python demo/render.py   (needs ffmpeg, edge-tts, Pillow, samerules on PATH)
Every terminal scene runs its commands for real and shows the actual output;
each scene lasts exactly as long as its narration.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
OUT = os.path.join(ROOT, "demo.mp4")
W, H, FPS = 1280, 720, 24
VOICE = "en-US-AndrewNeural"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG, FG = (24, 26, 33), (220, 223, 228)
ANSI = {"31": (255, 95, 95), "32": (95, 215, 120), "33": (240, 200, 80), "2": (130, 135, 145)}
PROMPT = "~/shop-api $ "

SCENES = [
    {"kind": "title", "title": "samerules", "sub": "one .agents/ folder for every coding agent's\nrules, skills and MCP servers",
     "say": "This is samerules, a small open source command line tool. You keep your coding agent rules, skills and "
            "M C P servers in one dot agents folder, and it writes the native files for Claude Code, Cursor, Codex, "
            "Gemini C L I, Open Code, Copilot and Windsurf, then tells you when any of them drift."},
    {"kind": "bullets", "title": "The problem",
     "bullets": ["Same rules copied into CLAUDE.md, AGENTS.md, .cursor/rules, GEMINI.md ...",
                 "Same MCP servers in five config files, five different formats",
                 "Skills copied into .claude/skills and .github/skills",
                 "Someone fixes one file, forgets the rest",
                 "Claude says pnpm, Codex says npm. Nobody notices."],
     "say": "If your team uses more than one agent, the same instructions end up in Claude dot M D, agents dot M D, "
            "Cursor rules and more. M C P servers get copied into five config files, each with its own format. "
            "Someone fixes a rule in one place and forgets the others, and now Claude and Codex are following different rules."},
    {"kind": "term", "cmds": ["ls -A", "grep -H test CLAUDE.md AGENTS.md"],
     "say": "Here's a typical repo. It has a Claude file, an agents file, a Cursor rule, a Claude skill, and M C P configs. "
            "They already disagree: Claude is told to use pnpm, while Codex and Cursor read agents dot M D, which still says npm."},
    {"kind": "term", "cmds": ["samerules import", "find .agents -type f | sort"],
     "say": "samerules import pulls all of it into one dot agents folder. It picks the most complete instruction file, "
            "and warns that agents dot M D disagrees, so you can review it. The Cursor rule, the skill, and the M C P server "
            "come along too."},
    {"kind": "term", "cmds": ["samerules sync --dry-run; echo \"exit code: $?\""],
     "say": "A dry run shows what sync would write. samerules never overwrites a file it didn't generate, so these "
            "hand written files show up as conflicts, and the exit code is a real one."},
    {"kind": "term", "cmds": ["samerules sync --force", "head -4 CLAUDE.md", "cat .cursor/mcp.json"],
     "say": "Since we just imported them, we take them over once with force. Every generated file gets a header saying "
            "where it came from. The M C P server from Claude's config is now in Cursor's config too, and in Codex's "
            "T O M L file, translated to each format."},
    {"kind": "term", "cmds": ["echo '- Use Postgres transactions for every write.' >> .agents/rules/main.md",
                              "samerules check; echo \"exit code: $?\"", "samerules sync"],
     "say": "Now you only edit the dot agents folder. Add a rule, and check fails with exit code one, because two files "
            "are out of date. Run sync, and both are updated."},
    {"kind": "term", "cmds": ["echo '- quick hack' >> CLAUDE.md", "samerules check; echo \"exit code: $?\"",
                              "samerules diff"],
     "say": "If someone edits a generated file by hand, check catches that too, and sync refuses to overwrite it without "
            "force. diff shows exactly what changed, so you can move it into the source."},
    {"kind": "bullets", "title": "Built for CI",
     "bullets": ["samerules check  →  exit 1 on any drift",
                 "pre-commit hooks: samerules-check, samerules-sync",
                 "Lock file + header: hand edits are never clobbered",
                 "Merges into opencode.json, .gemini/settings.json, .codex/config.toml",
                 "Translates ${VAR} for each harness"],
     "say": "Put samerules check in C I or pre-commit, and drift fails the build. It merges into shared files like "
            "open code dot jason and Codex's config without touching your other settings, and it translates "
            "environment variables for each tool."},
    {"kind": "bullets", "title": "Try it",
     "bullets": ["curl -fsSL https://raw.githubusercontent.com/",
                 "   hamarshehmhmd/samerules/main/install.sh | sh",
                 "samerules import  ·  sync  ·  check  ·  diff",
                 "", "Zero dependencies  ·  Python 3.9+  ·  84 tests",
                 "AGPL-3.0 licensed (commercial licenses available)"],
     "say": "samerules has no dependencies and needs Python three point nine or newer. It is licensed under the "
            "A G P L version 3, with commercial licenses available from the author. "
            "It's on GitHub at hamarsheh m h m d slash samerules."},
]


async def tts(text, path):
    import edge_tts
    for attempt in range(4):  # the edge-tts service occasionally returns no audio; retry
        try:
            await edge_tts.Communicate(text, VOICE, rate="+4%").save(path)
            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == 3:
                raise
            await asyncio.sleep(3)


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path], text=True)
    return float(out.strip())


def run_cmd(cmd, cwd):
    env = dict(os.environ, HOME=os.path.dirname(cwd), NO_COLOR="")
    env.pop("NO_COLOR")
    env["PATH"] = os.path.dirname(shutil.which("samerules")) + os.pathsep + env["PATH"]
    full = re.sub(r"\bsamerules (?=[a-z])", "samerules --color always ", cmd)
    p = subprocess.run(["bash", "-c", full], cwd=cwd, capture_output=True, text=True, env=env)
    out = (p.stdout + p.stderr).rstrip("\n")
    # pretty-print hook JSON
    if out.startswith("{"):
        import json
        try:
            out = json.dumps(json.loads(out), indent=2)
        except ValueError:
            pass
    return out


def parse_ansi(line):
    """Return [(text, color, bold)] spans for a line with SGR codes."""
    spans, color, bold = [], FG, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        m = re.match(r"\x1b\[([0-9;]*)m", part)
        if m:
            for code in (m.group(1) or "0").split(";"):
                if code == "0":
                    color, bold = FG, False
                elif code == "1":
                    bold = True
                elif code in ANSI:
                    color = ANSI[code]
        elif part:
            spans.append((part, color, bold))
    return spans


class Term:
    def __init__(self):
        self.font = ImageFont.truetype(MONO, 19)
        self.bold = ImageFont.truetype(MONO_B, 19)
        self.cw = self.font.getlength("M")
        self.lh = 27
        self.cols = int((W - 80) / self.cw)

    def wrap(self, spans):
        lines, cur, n = [], [], 0
        for text, c, b in spans:
            while text:
                room = self.cols - n
                if len(text) <= room:
                    cur.append((text, c, b)); n += len(text); text = ""
                else:
                    cur.append((text[:room], c, b)); lines.append(cur); cur, n = [], 0
                    text = "    " + text[room:]
        lines.append(cur)
        return lines

    def frame(self, lines, cursor=False):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([20, 14, W - 20, H - 14], 12, fill=(30, 33, 41), outline=(60, 64, 76))
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([40 + i * 24, 30, 54 + i * 24, 44], fill=c)
        d.text((W // 2, 37), "samerules demo — bash", font=ImageFont.truetype(SANS, 15), fill=(150, 155, 165), anchor="mm")
        visible = lines[-23:]
        y = 64
        for ln in visible:
            x = 40
            for text, c, b in ln:
                d.text((x, y), text, font=self.bold if b else self.font, fill=c)
                x += self.cw * len(text)
            y += self.lh
        if cursor:
            last = visible[-1] if visible else []
            x = 40 + self.cw * sum(len(t) for t, _, _ in last)
            d.rectangle([x, y - self.lh + 3, x + self.cw - 2, y - 4], fill=FG)
        return img


def card(scene):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    if scene["kind"] == "title":
        d.text((W // 2, 280), scene["title"], font=ImageFont.truetype(MONO_B, 84), fill=(95, 215, 120), anchor="mm")
        d.multiline_text((W // 2, 420), scene["sub"], font=ImageFont.truetype(SANS, 34), fill=FG, anchor="mm",
                         align="center", spacing=12)
        d.text((W // 2, 620), "github.com/hamarshehmhmd/samerules  ·  AGPL-3.0", font=ImageFont.truetype(SANS, 22),
               fill=(150, 155, 165), anchor="mm")
    else:
        d.text((90, 90), scene["title"], font=ImageFont.truetype(SANS_B, 52), fill=(95, 215, 120))
        f = ImageFont.truetype(SANS, 29)
        y = 200
        for b in scene["bullets"]:
            if b and not b.startswith("   "):
                d.text((90, y), "•", font=f, fill=(240, 200, 80))
            d.text((130, y), b.strip(), font=f, fill=FG)
            y += 58 if b.startswith("   ") or not b else 62
    return img


class Writer:
    def __init__(self, path, audio):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", audio,
                                   "-af", "apad", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                   "-shortest", path], stdin=subprocess.PIPE)
        self.n = 0

    def put(self, img, count=1):
        data = img.tobytes()
        for _ in range(count):
            self.p.stdin.write(data)
        self.n += count

    def close(self):
        self.p.stdin.close()
        self.p.wait()
        if self.p.returncode:
            sys.exit("ffmpeg failed")


def render_scene(i, scene, workdir):
    audio = os.path.join(BUILD, f"s{i}.mp3")
    if not os.path.exists(audio):
        asyncio.run(tts(scene["say"], audio))
    total = int((duration(audio) + 0.7) * FPS)
    path = os.path.join(BUILD, f"s{i}.mp4")
    w = Writer(path, audio)
    if scene["kind"] != "term":
        w.put(card(scene), total)
        w.close()
        return path
    t = Term()
    shown = scene.get("show", scene["cmds"])
    outputs = [run_cmd(c, workdir) for c in scene["cmds"]]
    # When a scene's displayed command differs from what runs (heredoc), show
    # the display lines; the last displayed line always maps to the last command.
    steps = []
    if len(shown) != len(scene["cmds"]):
        steps = [(s, "") for s in shown[:-1]] + [(shown[-1], outputs[-1])]
    else:
        steps = list(zip(shown, outputs))
    # timing budget: typing ~ 30 chars/s, then pause, spread over the narration
    typing = sum(len(s) for s, _ in steps) / 32 * FPS
    pause = max(6, int((total - typing) / max(1, len(steps))) - 4)
    lines = []
    for cmd, out in steps:
        prompt = [(PROMPT, (95, 215, 120), True)]
        for k in range(0, len(cmd) + 1, 2):
            frame = t.frame(lines + t.wrap(prompt + [(cmd[:k], FG, False)]), cursor=True)
            w.put(frame)
        lines += t.wrap(prompt + [(cmd, FG, False)])
        for ol in out.splitlines():
            lines += t.wrap(parse_ansi(ol))
        lines.append([])
        hold = min(pause, max(0, total - w.n))
        w.put(t.frame(lines), hold)
    final = t.frame(lines + t.wrap([(PROMPT, (95, 215, 120), True)]), cursor=True)
    if w.n < total:
        w.put(final, total - w.n)
    w.close()
    return path


def main():
    os.makedirs(BUILD, exist_ok=True)
    sandbox = os.environ.get("DEMO_HOME", "/home/dev")  # shown as $HOME in the demo
    shutil.rmtree(sandbox, ignore_errors=True)
    workdir = os.path.join(sandbox, "shop-api")
    subprocess.run(["sh", os.path.join(HERE, "make_repo.sh"), workdir], check=True)
    parts = [render_scene(i, s, workdir) for i, s in enumerate(SCENES)]
    with open(os.path.join(BUILD, "list.txt"), "w") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    os.path.join(BUILD, "list.txt"), "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", OUT], check=True)
    with open(os.path.join(BUILD, "narration.txt"), "w") as fh:
        fh.write("\n\n".join(s["say"] for s in SCENES) + "\n")
    print(OUT, round(duration(OUT), 1), "s")


if __name__ == "__main__":
    main()
