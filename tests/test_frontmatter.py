from samerules import frontmatter as fm


def test_no_frontmatter():
    assert fm.split("# hi\n") == ({}, "# hi\n")


def test_scalars_and_lists():
    meta, body = fm.split('---\ndescription: "API: rules"\nglobs: [a.ts, "b/**"]\nalways: true\nn: null\n---\nbody\n')
    assert meta == {"description": "API: rules", "globs": ["a.ts", "b/**"], "always": True, "n": None}
    assert body == "body\n"


def test_block_list_and_single_quotes():
    meta, _ = fm.split("---\npaths:\n  - 'src/**/*.ts'\n  - lib/*.js\nname: x  # comment\n---\n")
    assert meta["paths"] == ["src/**/*.ts", "lib/*.js"]
    assert meta["name"] == "x"


def test_empty_frontmatter_and_crlf():
    meta, body = fm.split("---\r\ndescription: hi\r\n---\r\nbody")
    assert meta == {"description": "hi"} and body == "body"
    assert fm.split("---\n---\nx")[1] == "x"


def test_folded_continuation():
    meta, _ = fm.split("---\ndescription: one\n  two\n---\n")
    assert meta["description"] == "one two"


def test_as_list():
    assert fm.as_list("a, b ,c") == ["a", "b", "c"]
    assert fm.as_list(["a,b", "c"]) == ["a", "b", "c"]
    assert fm.as_list(None) == [] and fm.as_list("") == []


def test_quote():
    assert fm.quote("plain text") == "plain text"
    assert fm.quote("a: b") == '"a: b"'
    assert fm.quote("**/*.ts") == '"**/*.ts"'
    assert fm.quote("true") == '"true"'
    assert fm.quote("1.5") == '"1.5"'
    assert fm.split("---\nd: %s\n---\n" % fm.quote('say "hi": now'))[0]["d"] == 'say "hi": now'
