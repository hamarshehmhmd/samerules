"""A tiny YAML-frontmatter reader/writer (the subset rules and skills use).

Supports ``key: value`` scalars, quoted strings, booleans, inline lists
(``[a, b]``) and block lists (``- item``). Anything fancier is kept as a raw
string. No third-party dependency on purpose.
"""

import json
import re

_FM_RE = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)(?:\r?\n)?^---[ \t]*(?:\r?\n|\Z)", re.S | re.M)
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*:(.*)$")


def split(text):
    """Return ``(meta_dict, body)``. Text without frontmatter gives ``({}, text)``."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    return parse(m.group(1)), text[m.end():]


def _scalar(raw):
    v = raw.strip()
    if not v:
        return ""
    if v[0] == '"' and v.endswith('"') and len(v) >= 2:
        try:
            return json.loads(v)
        except ValueError:
            return v[1:-1]
    if v[0] == "'" and v.endswith("'") and len(v) >= 2:
        return v[1:-1].replace("''", "'")
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in _split_commas(inner)]
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    # strip trailing comments ("value  # comment")
    v = re.sub(r"\s+#.*$", "", v)
    return v


def _split_commas(s):
    out, cur, quote = [], "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [p for p in (x.strip() for x in out) if p]


def parse(block):
    meta = {}
    key = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s*(.*)$", line)
        if item and key is not None and (line[:1].isspace() or line.startswith("-")):
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_scalar(item.group(1)))
            continue
        m = _KEY_RE.match(line)
        if m and not line[:1].isspace():
            key = m.group(1)
            meta[key] = _scalar(m.group(2))
        elif key is not None and isinstance(meta.get(key), str) and line[:1].isspace():
            # folded continuation line
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta


_PLAIN_OK = re.compile(r"^[A-Za-z0-9_./][A-Za-z0-9 _./()-]*$")


def quote(value):
    """Quote a string for YAML if it needs it (double quotes == JSON rules)."""
    s = str(value)
    if (
        _PLAIN_OK.match(s)
        and s == s.strip()
        and s.lower() not in ("true", "false", "yes", "no", "on", "off", "null", "~")
        and not re.match(r"^[0-9.+-]+$", s)
    ):
        return s
    return json.dumps(s, ensure_ascii=False)


def as_list(value):
    """Normalise a globs/paths value (list or comma string) into a list."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(as_list(v))
        return out
    return [p.strip().strip("\"'") for p in str(value).split(",") if p.strip()]
