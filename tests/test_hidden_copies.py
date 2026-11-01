"""The line-by-line edits that hide an installed skill from the model, and the sync rule that
refuses library skills those edits could not make safely."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import install_skills as installer
from scripts import sync_skills as ss

HIDDEN = installer.HIDDEN_KEY


def frontmatter(data: bytes) -> dict:
    return yaml.safe_load(installer.frontmatter(data, "fixture"))


# --- SKILL.md: disable-model-invocation ------------------------------------------------


def test_the_key_goes_first_and_the_rest_is_untouched():
    data = b"---\nname: alpha\ndescription: First.\n---\nbody\n"
    assert installer.hidden_skill_md(data, "alpha") == (
        b"---\ndisable-model-invocation: true\nname: alpha\ndescription: First.\n---\nbody\n"
    )


@pytest.mark.parametrize("value", ["true", "false", "True", "FALSE", "false  # upstream"])
def test_every_existing_top_level_line_of_the_key_is_replaced(value):
    """The last duplicate key wins, so an upstream `false` must not survive below the new line."""
    data = f"---\nname: alpha\n{HIDDEN}: {value}\ndescription: First.\n{HIDDEN}: true\n---\n".encode()
    hidden = installer.hidden_skill_md(data, "alpha")
    assert hidden == f"---\n{HIDDEN}: true\nname: alpha\ndescription: First.\n---\n".encode()
    assert frontmatter(hidden)[HIDDEN] is True


def test_bom_and_crlf_are_kept():
    data = b"\xef\xbb\xbf---\r\nname: alpha\r\ndescription: First.\r\n---\r\nbody\r\n"
    assert installer.hidden_skill_md(data, "alpha") == (
        b"\xef\xbb\xbf---\r\ndisable-model-invocation: true\r\nname: alpha\r\ndescription: First.\r\n---\r\nbody\r\n"
    )


def test_nested_keys_and_body_text_are_not_the_top_level_key():
    data = f"---\nname: alpha\nmetadata:\n  {HIDDEN}: false\n---\n{HIDDEN}: false\n".encode()
    hidden = installer.hidden_skill_md(data, "alpha")
    assert hidden.endswith(f"metadata:\n  {HIDDEN}: false\n---\n{HIDDEN}: false\n".encode())
    assert frontmatter(hidden) == {HIDDEN: True, "name": "alpha", "metadata": {HIDDEN: False}}


@pytest.mark.parametrize(
    "line",
    [
        f'{HIDDEN}: "true"',
        f"{HIDDEN}: yes",
        f"{HIDDEN}:",
        f"{HIDDEN} : true",
        f'"{HIDDEN}": false',
        f"'{HIDDEN}': true",
        f"{HIDDEN}: !!bool true",
    ],
)
def test_a_key_that_is_not_a_plain_one_line_boolean_is_refused(line):
    data = f"---\nname: alpha\n{line}\n  true\n---\n".encode() if line.endswith(":") else None
    data = data or f"---\nname: alpha\n{line}\n---\n".encode()
    with pytest.raises(installer.InstallError, match="not a plain one-line true or false"):
        installer.hidden_skill_md(data, "alpha")


def test_missing_frontmatter_is_refused():
    with pytest.raises(installer.InstallError, match="missing frontmatter"):
        installer.hidden_skill_md(b"# no frontmatter\n", "alpha")


# --- agents/openai.yaml: policy.allow_implicit_invocation ------------------------------


def policy(data: bytes) -> object:
    return yaml.safe_load(installer.hidden_policy(data, "alpha"))


def test_a_missing_file_is_created():
    assert installer.hidden_policy(None, "alpha") == b"policy:\n  allow_implicit_invocation: false\n"


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"interface:\n  display_name: Alpha\n", b"interface:\n  display_name: Alpha\npolicy:\n"),
        (b"interface:\n  display_name: Alpha", b"interface:\n  display_name: Alpha\npolicy:\n"),
        (b"interface:\r\n  display_name: Alpha\r\n", b"interface:\r\n  display_name: Alpha\r\npolicy:\r\n"),
    ],
)
def test_a_policy_block_is_appended_when_there_is_none(data, expected):
    merged = installer.hidden_policy(data, "alpha")
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    assert merged == expected + b"  allow_implicit_invocation: false" + eol
    assert yaml.safe_load(merged)["policy"] == {"allow_implicit_invocation": False}


@pytest.mark.parametrize(
    "block",
    [
        "policy:\n  allow_implicit_invocation: true\n  products: []\n",
        "policy:  # upstream\n    products: []\n    allow_implicit_invocation: yes  # was\n",
        "policy:\n  products: []\n",
        "policy:\n\n  # comment\n  products:\n    - codex\n",
    ],
)
def test_the_key_is_set_inside_a_block_policy(block):
    data = f"interface:\n  display_name: Alpha\n{block}dependencies:\n  tools: []\n".encode()
    merged = yaml.safe_load(installer.hidden_policy(data, "alpha"))
    original = yaml.safe_load(data)
    assert merged["policy"] == {**original["policy"], "allow_implicit_invocation": False}
    assert {k: v for k, v in merged.items() if k != "policy"} == {k: v for k, v in original.items() if k != "policy"}


def test_an_existing_false_is_left_byte_for_byte():
    data = b"policy:\n  allow_implicit_invocation: false  # already hidden\n"
    assert installer.hidden_policy(data, "alpha") is data


@pytest.mark.parametrize(
    "data, reason",
    [
        (b"policy:\n  products: []\npolicy:\n  products: []\n", "more than one top-level policy key"),
        (b"policy: {allow_implicit_invocation: true}\n", "not a block-style mapping"),
        (b"policy: true\n", "not a block-style mapping"),
        (b"policy:\ninterface: {}\n", "not a block-style mapping"),
        (b"policy:\n  - allow_implicit_invocation\n", "not a block-style mapping"),
        (b'"policy":\n  products: []\n', "not a block-style mapping"),
        (
            b"policy:\n  allow_implicit_invocation: true\n  allow_implicit_invocation: true\n",
            "more than once",
        ),
        (b"policy:\n  allow_implicit_invocation:\n    true\n", "not a plain one-line value"),
        (b"policy:\n  allow_implicit_invocation: [\n    true]\n", "not a plain one-line value"),
        (b'policy:\n  "allow_implicit_invocation": true\n', "not a plain one-line value"),
        # A `policy:` block appended to these would be invalid YAML, which Codex ignores as a whole.
        (b"  interface:\n    display_name: Alpha\n", "not one block mapping at column 0"),
        (b"interface:\n  display_name: Alpha\n...\n", "not one block mapping at column 0"),
        (b"interface: {}\n---\nother: 1\n", "not one block mapping at column 0"),
        (b"%YAML 1.1\n---\ninterface: {}\n", "not one block mapping at column 0"),
        (b"# flow\n{interface: {display_name: Alpha}}\n", "not one block mapping at column 0"),
        (b"- interface\n", "not one block mapping at column 0"),
        (b"&root\ninterface: {}\n", "not one block mapping at column 0"),
    ],
)
def test_other_policy_shapes_are_refused(data, reason):
    with pytest.raises(installer.InstallError, match=reason):
        installer.hidden_policy(data, "alpha")


# --- The sync rule ---------------------------------------------------------------------


def skill(root: Path, frontmatter_lines: str = "", files: dict | None = None) -> Path:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"---\nname: {root.name}\ndescription: Fixture.\n{frontmatter_lines}---\nbody\n")
    for rel, text in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode())
    return root


# agents/openai.yaml shapes Codex 0.165 reads (probed with `codex debug prompt-input`): unknown keys,
# any scalar as a string, null sections, known products, an oauth callback port.
CODEX_READS = [
    "interface:\n  display_name: 12\n  brand_color: true\n  unknown: [1, {a: 2}]\nextra: {b: [3]}\n",
    "interface:\ndependencies:\npolicy:\n  products:\n",
    "policy:\n  products: [codex, chatgpt, atlas, CODEX]\n",
    "policy:\n  products: [CHATGPT, ATLAS]\n",
    "dependencies:\n  tools:\n    - type: mcp\n      transport: carrier-pigeon\n      oauth: {callbackPort: 8080, x: [1]}\n",
]
# Shapes Codex 0.165 cannot read into its typed schema: it ignores the whole file, policy included.
CODEX_IGNORES = {
    "policy:\n  products:\n    - nonsense\n": "policy.products is not a list of",
    "policy:\n  products: [codex, Codex]\n": "policy.products is not a list of",
    "policy:\n  products: codex\n": "policy.products is not a list of",
    "interface:\n  display_name: [a, b]\n": "interface.display_name is not a single value",
    "interface:\n  default_prompt: {a: b}\n": "interface.default_prompt is not a single value",
    "interface:\n  short_description: [a]\n": "interface.short_description is not a single value",
    "interface:\n  icon_small: {a: b}\n": "interface.icon_small is not a single value",
    "interface:\n  icon_large: [a]\n": "interface.icon_large is not a single value",
    "interface:\n  brand_color: [a]\n": "interface.brand_color is not a single value",
    "interface: hello\n": "interface is not a mapping",
    "dependencies: []\n": "dependencies is not a mapping",
    "dependencies:\n  tools: x\n": "dependencies.tools is not a list",
    "dependencies:\n  tools:\n    - x\n": "dependencies.tools[0] is not a mapping",
    "dependencies:\n  tools:\n    - command: [a, b]\n": "dependencies.tools[0].command is not a single value",
    "dependencies:\n  tools:\n    - type: [mcp]\n": "dependencies.tools[0].type is not a single value",
    "dependencies:\n  tools:\n    - value: {a: b}\n": "dependencies.tools[0].value is not a single value",
    "dependencies:\n  tools:\n    - description: [a]\n": "dependencies.tools[0].description is not a single value",
    "dependencies:\n  tools:\n    - transport: {a: b}\n": "dependencies.tools[0].transport is not a single value",
    "dependencies:\n  tools:\n    - url: {a: b}\n": "dependencies.tools[0].url is not a single value",
    "dependencies:\n  tools:\n    - oauth: {callbackPort: true}\n": "oauth.callbackPort is not one port number",
    "dependencies:\n  tools:\n    - oauth: true\n": "dependencies.tools[0].oauth is not a mapping",
    "dependencies:\n  tools:\n    - oauth: {callbackPort: 65536}\n": "oauth.callbackPort is not one port number",
    "dependencies:\n  tools:\n    - oauth: {callback_port: '80'}\n": "oauth.callbackPort is not one port number",
    "dependencies:\n  tools:\n    - oauth: {callbackPort: 1, callback_port: 2}\n": "is not one port number",
}


@pytest.mark.parametrize(
    "lines, files",
    [
        ("", {}),
        (f"{HIDDEN}: true\n", {}),
        ("user-invocable: true\n", {}),
        (f"{HIDDEN}: false\n", {"agents/openai.yaml": "interface:\n  display_name: Alpha\n"}),
        ("", {"agents/openai.yaml": "policy:\n  allow_implicit_invocation: true\n"}),
        ("", {"nested/SKILL.md": "---\nname: nested\ndescription: x\n---\n", "nested/agents/openai.yaml": "a: 1\n"}),
        *(("", {"agents/openai.yaml": text}) for text in CODEX_READS),
    ],
)
def test_skills_the_installer_can_hide_pass(tmp_path, lines, files):
    root = skill(tmp_path / "alpha", lines, files)
    assert ss.candidate_problems(root, "alpha") == []


@pytest.mark.parametrize(
    "lines, files, expected",
    [
        (f'{HIDDEN}: "true"\n', {}, f"Cannot hide alpha: top-level {HIDDEN} is not a plain one-line true or false"),
        (f'"{HIDDEN}": false\n', {}, "is not a plain one-line true or false"),
        ("user-invocable: false\n", {}, "user-invocable is not true: its hidden copy could not be run at all"),
        ("user-invocable: maybe\n", {}, "user-invocable is not true"),
        ('summary: "split notes on --- lines"\n', {}, "frontmatter holds `---` before its closing line"),
        ("notes: |\n  ----\n  a rule\n", {}, "frontmatter holds `---` before its closing line"),
        ("", {"agents/openai.yaml": "policy: {allow_implicit_invocation: true}\n"}, "not a block-style mapping"),
        ("", {"agents/openai.yaml": "- a\n- b\n"}, "agents/openai.yaml is not a block-style mapping"),
        ("", {"agents/openai.yaml": "{interface: {display_name: A}}\n"}, "is not a block-style mapping"),
        ("", {"agents/openai.yaml": ""}, "is not a block-style mapping"),
        ("", {"agents/openai.yaml": "interface: [\n"}, "is not valid YAML"),
        ("", {"agents/openai.yaml": "interface: 1\n---\ninterface: 2\n"}, "is not valid YAML"),
        ("", {"agents/openai.yaml": "interface: {}\ninterface: {}\n"}, "has duplicate keys: interface"),
        (
            "",
            {"agents/openai.yaml": "policy:\n  products: []\n  products: []\n"},
            "has duplicate keys: policy.products",
        ),
        # Codex reads the file with serde_yaml, which refuses a duplicate at any depth: it then ignores the
        # whole file, the policy included.
        (
            "",
            {"agents/openai.yaml": 'interface:\n  display_name: "One"\n  display_name: "Two"\n'},
            "has duplicate keys: interface.display_name",
        ),
        (
            "",
            {"agents/openai.yaml": "interface:\n  default_prompt: a\n  default_prompt: b\n"},
            "has duplicate keys: interface.default_prompt",
        ),
        (
            "",
            {"agents/openai.yaml": "dependencies:\n  tools:\n    - type: mcp\n      value: x\n      value: y\n"},
            "has duplicate keys: dependencies.tools[0].value",
        ),
        ("", {"agents/openai.yaml": "interface:\n  extra: 1\n  extra: 2\n"}, "has duplicate keys: interface.extra"),
        (
            "",
            {"agents/openai.yaml": 'interface:\n  default_prompt: "a\npolicy:\n  b"\n'},
            "would read differently once policy.allow_implicit_invocation is false",
        ),
        (
            "",
            {"deep/SKILL.md": "---\nname: deep\ndescription: x\n---\n", "deep/agents/openai.yaml": "policy: true\n"},
            "Cannot hide alpha/deep: agents/openai.yaml has a policy that is not a block-style mapping",
        ),
    ],
)
def test_skills_the_installer_could_not_hide_are_rejected(tmp_path, lines, files, expected):
    root = skill(tmp_path / "alpha", lines, files)
    problems = ss.candidate_problems(root, "alpha")
    assert any(expected in problem for problem in problems), problems
    assert not any(problem.startswith("Invalid frontmatter") for problem in problems)


@pytest.mark.parametrize("text", CODEX_IGNORES, ids=list(CODEX_IGNORES.values()))
def test_a_policy_file_codex_would_ignore_as_a_whole_is_rejected(tmp_path, text):
    root = skill(tmp_path / "alpha", files={"agents/openai.yaml": text})
    problems = ss.candidate_problems(root, "alpha")
    prefix = "Cannot hide alpha: agents/openai.yaml is ignored as a whole by Codex, its policy included: "
    assert len(problems) == 1 and problems[0].startswith(prefix) and CODEX_IGNORES[text] in problems[0], problems


def test_library_problems_name_the_skill(tmp_path):
    skill(tmp_path / "skills/alpha", files={"agents/openai.yaml": "policy: true\n"})
    skill(tmp_path / "skills/beta")
    assert ss.library_problems(tmp_path / "skills") == [
        "alpha: Cannot hide alpha: agents/openai.yaml has a policy that is not a block-style mapping"
    ]
