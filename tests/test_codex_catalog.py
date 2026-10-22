"""Offline catalog parsing, isolation, interface gates, and opt-in local integration."""

from __future__ import annotations

import io
import json
import os
import shutil
from pathlib import Path

import pytest

from scripts import verify_codex_catalog as verifier


def test_catalog_parser_reads_model_input_and_preserves_missing_descriptions():
    prompt = [
        {
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": """<skills_instructions>
### Skill roots
- `r0` = `/temporary/skills`
### Available skills
- external-linked: Description with: a colon. (file: r0/external-linked/SKILL.md)
- external-copied: (file: r0/external-copied/SKILL.md)
</skills_instructions>""",
                }
            ],
        }
    ]
    entries = verifier.catalog_entries(prompt)
    assert entries == [
        {"name": "external-linked", "description": "Description with: a colon.", "path": "r0/external-linked/SKILL.md"},
        {"name": "external-copied", "description": "", "path": "r0/external-copied/SKILL.md"},
    ]


@pytest.mark.parametrize(
    "prompt", [{"unexpected": "shape"}, [{"content": [{"type": "input_text", "text": "No catalog"}]}]]
)
def test_unrecognized_preview_is_not_reported_as_success(prompt):
    with pytest.raises(verifier.VerificationError):
        verifier.catalog_entries(prompt)


def test_isolation_omits_authentication_and_live_home(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret-never-forwarded")
    monkeypatch.setenv("CODEX_HOME", "/live/codex")
    monkeypatch.setenv("SKILLS_CODEX_DEST", "/live/skills")
    env = verifier.isolated_env(tmp_path / "home", tmp_path / "tmp")
    assert "OPENAI_API_KEY" not in env
    assert "SKILLS_CODEX_DEST" not in env
    assert env["CODEX_HOME"] == str(tmp_path / "home/.codex")
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:9"
    assert env["NO_PROXY"] == ""


def test_capability_detection_accepts_new_versions_without_pinning_counts(monkeypatch, tmp_path):
    def fake_run(command, env, cwd, timeout=45):
        arguments = command[1:]
        if arguments == ["--version"]:
            return "codex-cli 9.999.1\n"
        if arguments == ["debug", "--help"]:
            return "prompt-input"
        if arguments == ["app-server", "--help"]:
            return "--stdio generate-json-schema"
        if arguments == ["features", "list"]:
            return "\n".join(f"{feature} stable true" for feature in verifier.REMOTE_FEATURES)
        if arguments[:2] == ["app-server", "generate-json-schema"]:
            schema = Path(arguments[-1])
            (schema / "v2").mkdir(parents=True)
            (schema / "v2/SkillsListParams.json").write_text(
                json.dumps({"properties": {"cwds": {}, "forceReload": {}}})
            )
            (schema / "ClientRequest.json").write_text('{"method": "skills/list"}')
            return ""
        pytest.fail(f"Unexpected interface: {command}")

    monkeypatch.setattr(verifier, "run", fake_run)
    result = verifier.detect_capabilities("fixture-codex", {}, tmp_path, tmp_path)
    assert result["version"] == "codex-cli 9.999.1"


def test_missing_prompt_interface_explicitly_skips(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(verifier.shutil, "which", lambda _: "/fixture/codex")
    monkeypatch.setattr(
        verifier,
        "run",
        lambda command, *args, **kwargs: "codex-cli 0.100.0" if command[-1] == "--version" else "models app-server",
    )
    assert verifier.main(["--source", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "skipped"
    assert "prompt-input" in output["reason"]


def test_fixture_copies_documents_and_layout_without_support_files(tmp_path):
    source = tmp_path / "source/skills"
    skill = source / "real-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: real-skill\ndescription: Real document.\n---\n")
    (skill / "references/private-data.txt").write_text("never copied")
    installer = tmp_path / "installer/scripts/install_skills.py"
    installer.parent.mkdir(parents=True)
    installer.write_text("# installer fixture\n")
    (installer.parent.parent / "install.sh").write_text("# bootstrap fixture\n")
    root = tmp_path / "temporary"
    root.mkdir()
    bundle, summary = verifier.prepare_fixture(source, installer, root)
    assert summary["top_level_skill_documents"] == 1
    assert (bundle / "skills/real-skill/SKILL.md").read_bytes() == (skill / "SKILL.md").read_bytes()
    assert (bundle / "skills/real-skill/references").is_dir()
    assert not (bundle / "skills/real-skill/references/private-data.txt").exists()
    link = root / "home/.agents/skills/external-linked"
    assert link.is_symlink()
    assert link.resolve().is_relative_to(root / "home")
    assert verifier.FIXTURES["external-linked"] in (link / "SKILL.md").read_text()


def test_discovery_rejects_operating_system_home_fallback(monkeypatch, tmp_path):
    env = verifier.isolated_env(tmp_path / "home", tmp_path / "tmp")

    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(
                "\n".join(
                    json.dumps(message)
                    for message in [
                        {"id": 1, "result": {"codexHome": env["CODEX_HOME"]}},
                        {
                            "id": 2,
                            "result": {
                                "data": [
                                    {"skills": [{"path": "/live/home/.agents/skills/private/SKILL.md"}], "errors": []}
                                ]
                            },
                        },
                    ]
                )
                + "\n"
            )
            self.stderr = io.StringIO()

        def terminate(self):
            pass

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(verifier.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    with pytest.raises(verifier.VerificationError, match="escaped the isolated HOME"):
        verifier.discover("fixture-codex", env, tmp_path)


def test_temporary_home_is_removed_when_interface_is_unsupported(monkeypatch, tmp_path):
    paths = []

    def unsupported(codex, env, work, temporary):
        paths.append(temporary)
        raise verifier.UnsupportedCodex("fixture unsupported interface")

    monkeypatch.setattr(verifier, "detect_capabilities", unsupported)
    with pytest.raises(verifier.UnsupportedCodex):
        verifier.verify("fixture-codex", tmp_path, tmp_path / "installer.py")
    assert len(paths) == 1
    assert not paths[0].exists()


@pytest.mark.skipif(
    os.environ.get("AWESOME_SKILLS_CODEX_INTEGRATION") != "1",
    reason="Set AWESOME_SKILLS_CODEX_INTEGRATION=1 for local offline Codex integration",
)
def test_local_codex_discovery_and_model_visible_catalog(tmp_path):
    codex = shutil.which("codex")
    if not codex:
        pytest.skip("Local Codex unavailable")
    source = tmp_path / "skills"
    skill = source / "fixture-repository-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: fixture-repository-skill\ndescription: Fixture repository skill.\n---\n"
    )
    installer = Path(os.environ.get("AWESOME_SKILLS_INSTALLER", str(verifier.ROOT / "scripts/install_skills.py")))
    try:
        result = verifier.verify(codex, source, installer)
    except verifier.UnsupportedCodex as exc:
        pytest.skip(str(exc))
    assert result["status"] == "passed"
    assert result["after"]["library_visible_with_description"]
    assert all(result["after"]["fixtures_visible_with_description"].values())
    assert result["no_argument_update_preserved_selection"]
    assert result["no_argument_update_codex_actions"] == 0
    assert result["temporary_artifacts_removed"]
