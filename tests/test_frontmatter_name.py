"""The standard-library frontmatter name reader must read exactly what PyYAML reads, or refuse."""

from __future__ import annotations

import random

import pytest

from scripts import install_skills as installer

BACKSLASH_U = chr(92) + "u"  # written this way so no editor or tool turns it into the character

# Frontmatter text (between the `---` lines) -> the name both PyYAML and the reader load.
ACCEPTED = {
    "plain": ("name: alpha\ndescription: Use alpha\n", "alpha"),
    "leading digits": ("name: 13c-metabolic-flux\n", "13c-metabolic-flux"),
    "indicator characters that still start a plain scalar": ("name: -x?y:z\n", "-x?y:z"),
    "colon and hash inside a plain scalar": ("name: a:b#c, [d] {e}\n", "a:b#c, [d] {e}"),
    "trailing comment": ("name: alpha   # the id\n", "alpha"),
    "spaces before the colon": ("name   : spaced key\n", "spaced key"),
    "single-quoted": ("name: 'it''s \"here\"'\n", 'it\'s "here"'),
    "double-quoted with spaces": ('name: "  padded  "\n', "  padded  "),
    "double-quoted escapes": (
        'name: "a\\x41' + BACKSLASH_U + '00e9\\U0001F600\\t\\"\\\\\\/\\N\\_"\n',
        'aA\N{LATIN SMALL LETTER E WITH ACUTE}\N{GRINNING FACE}\t"\\/\x85\xa0',
    ),
    "comment right after the closing quote": ('name: "alpha"# note\n', "alpha"),
    "quoted keys": ("'other': 1\n\"name\": quoted key\n", "quoted key"),
    "a block scalar holding name lines": ("description: |\n  name: not this\n\n  more\nname: real\n", "real"),
    "a block scalar with an indentation indicator": ("description: >2-\n   extra\n  base\nname: real\n", "real"),
    "a multi-line plain value": ("description: plain\n  continued\n\n  on more lines\nname: real\n", "real"),
    "a column-0 line inside a quoted value": ('description: "spans\nname: still quoted"\nname: real\n', "real"),
    "an escaped line break": ('description: "one \\\n  two"\nname: real\n', "real"),
    "a column-0 line inside a nested quoted value": (
        'metadata:\n  note: "spans\nname: still quoted"\nname: real\n',
        "real",
    ),
    "nested collections": (
        "metadata:\n  tools:\n    - a\n    - name: nested\n      b: |\n        text\n  os: [mac, linux]\nname: real\n",
        "real",
    ),
    "an indentless sequence": ("tags:\n- a\n- name: nested\n  b: c\n-\nname: real\n", "real"),
    "a multi-line flow mapping": (
        'metadata:\n  {\n    "openclaw":\n      {\n        "name": "nested",\n      },\n  }\nname: real\n',
        "real",
    ),
    "a plain scalar continuing inside a flow collection": ("tags: [a\n'b, c]\nname: real\n", "real"),
    "a comment inside a flow collection": ("tags: [a, # a comment ]\n  b]\nname: real\n", "real"),
    "comments and blank lines": ("# leading\n\nname: alpha\n  # indented comment\n", "alpha"),
}

# Frontmatter the reader refuses, with the reason it gives. PyYAML reads a name from most of
# these too; the reader refuses them because it does not follow them or the name is no string.
REFUSED = {
    "block scalar name": ("name: |\n  block\n", "not a plain or quoted scalar"),
    "flow name": ("name: [alpha]\n", "not a plain or quoted scalar"),
    "anchored name": ("name: &a alpha\n", "anchor, tag or alias"),
    "tagged name": ("name: !!str alpha\n", "anchor, tag or alias"),
    "alias name": ("base: x\nname: *a\n", "anchor, tag or alias"),
    "anchor elsewhere": ("name: alpha\nmetadata: {a: &b 1}\n", "unexpected '&'"),
    "multi-line plain name": ("name: alpha\n  beta\n", "multi-line name"),
    "multi-line quoted name": ('name: "alpha\n  beta"\n', "multi-line name"),
    "duplicate name": ("name: alpha\nname: beta\n", "duplicate top-level name"),
    "duplicate quoted name": ("name: alpha\n'name': beta\n", "duplicate top-level name"),
    "boolean": ("name: yes\n", "does not load as a string"),
    "integer": ("name: 0x1F\n", "does not load as a string"),
    "sexagesimal": ("name: 1:20\n", "does not load as a string"),
    "float": ("name: .inf\n", "does not load as a string"),
    "date": ("name: 2026-10-27\n", "does not load as a string"),
    "null": ("name: ~\n", "does not load as a string"),
    "missing value": ("name:\n", "empty name"),
    "empty string": ("name: ''\n", "empty name"),
    "blank string": ('name: "  "\n', "empty name"),
    "no name": ("description: x\n", "no top-level name"),
    "nested name only": ("metadata:\n  name: alpha\n", "no top-level name"),
    "indented document": ("  name: alpha\n", "does not start with a top-level key"),
    "top-level sequence": ("- name: alpha\n", "does not start with a top-level key"),
    "top-level flow mapping": ("{name: alpha}\n", "unexpected value"),
    "explicit key": ("? name\n: alpha\n", "unexpected value"),
    "merge key": ("<<: {name: alpha}\n", "merge key"),
    "tab after a value": ("name: alpha\t\n", "tab outside a quoted scalar"),
    "tab indentation": ("name: alpha\n\tdescription: x\n", "tab outside a quoted scalar"),
    "document end": ("name: alpha\n...\n", "document marker"),
    "second document": ("name: alpha\n--- beta\n", "document marker"),
    "directive": ("%YAML 1.1\nname: alpha\n", "unexpected value at column 0"),
    "non-printable": ("name: alpha\x07\n", "non-printable character"),
    "unknown escape": ('name: "a\\q"\n', "invalid escape"),
    "unterminated quote": ('name: alpha\ndescription: "open\n', "unterminated quoted scalar"),
    "unterminated flow": ("name: alpha\ntags: [a,\n", "unterminated flow collection"),
    "mapping value in a plain scalar": ("description: a: b\nname: alpha\n", "mapping value inside a plain scalar"),
    "indented key after a value": ('name: alpha\ndescription: "x"\n  stray: y\n', "unexpected key at column 2"),
    "bad indentation": ("metadata:\n    a: 1\n  b: 2\nname: alpha\n", "unexpected key at column 2"),
    "key without colon": ("metadata:\n  a: 1\n  b\nname: alpha\n", "unexpected value at column 2"),
}


def read(text: str) -> str:
    return installer.frontmatter_name(f"---\n{text}---\nbody\n".encode(), "fixture")


@pytest.mark.parametrize("text, name", ACCEPTED.values(), ids=ACCEPTED)
def test_accepted_forms_read_as_pyyaml_reads_them(text, name):
    assert read(text) == name
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(text)["name"] == name


@pytest.mark.parametrize("text, reason", REFUSED.values(), ids=REFUSED)
def test_refused_forms(text, reason):
    with pytest.raises(installer.InstallError, match="Unreadable frontmatter name at fixture: .*" + reason):
        read(text)


@pytest.mark.parametrize(
    "value",
    [
        *["y", "n", "Yes", "NO", "on", "Off", "true", "FALSE", "yes!", "nope", "online"],
        *["0", "07", "08", "0b101", "0x_1f", "1_000", "-1", "+12", "1:2:3", "190:20:30", "1.0.0", "v1", "3d"],
        *["1.5", "1e3", "1.e+3", "-.5", ".5", ".nan", ".NaN", ".Inf", "+.inf", ".", "..", "1.2.3", "1_0.5"],
        *["2026-10-27", "2026-1-2 3:04:05", "2026-10-27t12:00:00Z", "2026-10-27 12:00:00 +2", "2026-10-27x"],
        *["~", "null", "Null", "NULL", "nul", "None", "<", "<<", "=", "-", "x=y", "13c-metabolic-flux"],
    ],
)
def test_plain_name_typing_matches_pyyaml(value):
    yaml = pytest.importorskip("yaml")
    try:
        loaded = yaml.safe_load(f"name: {value}\n")["name"]
    except yaml.YAMLError:
        loaded = None  # "-", "<<" and "=" do not load at all
    if isinstance(loaded, str):
        assert read(f"name: {value}\n") == loaded == value
    else:
        with pytest.raises(installer.InstallError, match="does not load|not a plain or quoted scalar"):
            read(f"name: {value}\n")


def test_frontmatter_delimiters_are_shared_with_metadata():
    for data in (b"", b"name: alpha\n", b"---\nname: alpha\n", b"\xff---\n"):
        with pytest.raises(installer.InstallError, match="Invalid frontmatter at fixture"):
            installer.frontmatter_name(data, "fixture")
    # Every line break str.splitlines() knows ends a line for both readers.
    data = b"---\r\ndescription: x\x0bname: alpha\r\n---\r\n"
    assert installer.frontmatter_name(data, "fixture") == "alpha"
    pytest.importorskip("yaml")
    assert installer.metadata(data, "fixture")["name"] == "alpha"


WORDS = ["alpha", "it's", 'say "hi"', "a#b", "x:y", "[a]", "{b}", "c, d", "-e", "13c", "yes", "1.5", "~"]
FRAGMENTS = [
    *["'", '"', "''", "#", " #c", ": ", ":", "-", "- ", "[", "]", "{", "}", ",", "?", " ", "  ", "\t", "|", ">"],
    *["&x", "*x", "!t", "\\", "...", "---", "<<", "=", "\N{LATIN SMALL LETTER E WITH ACUTE}", "\n", "\n  "],
    *["\n- ", "\nname: ", "\n  name: ", "\n'name': "],
]


def generated(rng: random.Random) -> str:
    """Frontmatter shaped like real SKILL.md files, often corrupted with YAML punctuation."""

    def words():
        return " ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 3)))

    shapes = [
        lambda k: f"{k}: {words()}",
        lambda k: f"{k}: '{words()}'",
        lambda k: f'{k}: "{words()}"',
        lambda k: f'{k}: "{words()}\n{rng.choice(["name: inner", words(), "  " + words()])}"',
        lambda k: f"{k}: {rng.choice(['|', '>-', '|2'])}\n  {words()}\n{rng.choice(['  name: inner', '', '   x'])}",
        lambda k: f"{k}:\n  a: {words()}\n  b:\n    - {words()}\n    - c: {words()}",
        lambda k: f"{k}:\n- {words()}\n- name: {words()}",
        lambda k: f"{k}: [{words()}, {words()}]",
        lambda k: f"{k}: {{a: [{words()},\n{rng.choice(['name: inner', words()])}]}}",
        lambda k: f"{k}: {words()}\n  {words()}",
        lambda k: "# a comment\n",
    ]
    keys = ["description", "metadata", "x", "'quoted'", "name"]
    parts = [rng.choice(shapes)(rng.choice(keys)) for _ in range(rng.randint(0, 4))]
    parts.insert(rng.randint(0, len(parts)), f"name: {rng.choice(['alpha', 'it-s', 'q #c', 'x:y', 'A b'])}")
    text = list("\n".join(parts) + "\n")
    for _ in range(rng.choice([0, 0, 1, 2])):
        k = rng.randint(0, len(text))
        text[k:k] = rng.choice(FRAGMENTS) if rng.random() < 0.8 else []
        if rng.random() < 0.2:
            del text[k : k + 1]
    return "".join(text)


def test_the_reader_never_reads_a_name_pyyaml_would_not():
    """Differential check on generated near-YAML: whenever the reader returns a name, PyYAML loads
    the same name. The one known gap: a flow collection PyYAML cannot parse or construct
    (`[a: b: c]`, `{[a]: b}`), which makes it reject the whole frontmatter, does not stop the reader."""
    yaml = pytest.importorskip("yaml")
    rng, accepted = random.Random(20261027), 0
    for _ in range(4000):
        text = generated(rng)
        try:
            name = installer.NameReader(text).read()
        except ValueError:
            continue
        accepted += 1
        try:
            loaded = yaml.safe_load(text)
        except yaml.MarkedYAMLError as error:
            assert "while parsing a flow" in (error.context or "") or error.problem == "found unhashable key", text
            continue
        assert isinstance(loaded, dict) and loaded.get("name") == name, text
    assert accepted > 1000, "the generator must also produce readable frontmatter"
