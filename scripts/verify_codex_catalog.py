#!/usr/bin/env python3
"""Verify a legacy migration against Codex's offline discovery and prompt preview.

The fixture copies SKILL.md documents and directory layout, never credentials or
supporting files. All HOME, discovery, state, cache and working paths are temporary.
No model turns are started. Missing experimental interfaces produce an explicit
JSON skip; a supported interface that fails validation produces an error.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = {
    "external-linked": "Offline fixture for a symlinked skill outside the library; no credentials or network access.",
    "external-copied": "Offline fixture for a copied skill outside the library; no credentials or API calls.",
}
ROUTER = "awesome-skills-library"
REMOTE_FEATURES = ("plugins", "apps", "remote_plugin")


class UnsupportedCodex(Exception):
    """The installed Codex cannot safely run this version of the offline probe."""


class VerificationError(Exception):
    """A supported interface or the migration did not meet the acceptance criteria."""


def isolated_env(home: Path, temporary: Path) -> dict[str, str]:
    """Allow only required local variables; omit authentication and live config."""
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "TMPDIR": str(temporary),
        "SKILLS_STATE_DIR": str(home / ".local/share/awesome-skills"),
        "SKILLS_DATA_DIR": str(home / ".local/share/awesome-skills"),
        "SKILLS_CACHE_DIR": str(home / ".cache/awesome-skills"),
        "SKILLS_PYTHON": sys.executable,
        "RUST_LOG": "warn",
    }
    # App-server can otherwise warm a remote featured-plugin cache during startup.
    # Feature gates are checked before startup, and these proxies are a second guard.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = "http://127.0.0.1:9"
    env.update(NO_PROXY="", no_proxy="")
    return env


def updater_actions(output: str, client: str) -> list:
    """A run with nothing to change prints one line; any other run prints its JSON plan first."""
    text = output.strip()
    if text == "Already current; selection preserved.":
        return []
    plan, _ = json.JSONDecoder().raw_decode(text)
    return next(item for item in plan["clients"] if item["client"] == client)["actions"]


def run(command: list[str], env: dict[str, str], cwd: Path, timeout: int = 45) -> str:
    result = subprocess.run(command, env=env, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise VerificationError(f"{command[0]} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def detect_capabilities(codex: str, env: dict[str, str], work: Path, temporary: Path) -> dict:
    version = run([codex, "--version"], env, work).strip()
    if not re.search(r"\b\d+\.\d+\.\d+\b", version):
        raise UnsupportedCodex(f"Unrecognized Codex version response: {version!r}")

    def capability_output(arguments: list[str]) -> str:
        try:
            return run([codex, *arguments], env, work)
        except VerificationError as exc:
            if any(
                marker in str(exc) for marker in ("unrecognized subcommand", "unknown command", "unexpected argument")
            ):
                raise UnsupportedCodex(f"{version} lacks a required local interface: {exc}") from exc
            raise

    if "prompt-input" not in capability_output(["debug", "--help"]):
        raise UnsupportedCodex(f"{version} has no debug prompt-input interface")
    app_help = capability_output(["app-server", "--help"])
    if "--stdio" not in app_help or "generate-json-schema" not in app_help:
        raise UnsupportedCodex(f"{version} has no supported stdio app-server/schema interface")
    features = {line.split()[0] for line in capability_output(["features", "list"]).splitlines() if line.split()}
    missing = set(REMOTE_FEATURES) - features
    if missing:
        raise UnsupportedCodex(f"{version} lacks verified offline feature gates: {sorted(missing)}")
    schema = temporary / "protocol"
    capability_output(["app-server", "generate-json-schema", "--out", str(schema)])
    params = schema / "v2/SkillsListParams.json"
    requests = schema / "ClientRequest.json"
    if not params.is_file() or not requests.is_file():
        raise UnsupportedCodex(f"{version} generated an unfamiliar app-server schema layout")
    properties = json.loads(params.read_text())["properties"]
    if not {"cwds", "forceReload"}.issubset(properties) or '"skills/list"' not in requests.read_text():
        raise UnsupportedCodex(f"{version} has an unsupported skills/list protocol")
    return {"version": version, "prompt_preview": "debug prompt-input", "discovery": "app-server skills/list"}


def discover(codex: str, env: dict[str, str], work: Path) -> tuple[list[dict], list[dict], str]:
    command = [codex, "app-server", "--stdio"]
    for feature in REMOTE_FEATURES:
        command.extend(["--disable", feature])
    process = subprocess.Popen(
        command, env=env, cwd=work, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    messages: queue.Queue[str | None] = queue.Queue()
    errors: list[str] = []

    def read_stdout():
        for line in process.stdout:
            messages.put(line)
        messages.put(None)

    def read_stderr():
        errors.extend(process.stderr)

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for reader in readers:
        reader.start()

    def request(value: dict):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    def response(request_id: int) -> dict:
        deadline = time.monotonic() + 30
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VerificationError("Timed out waiting for offline skills/list")
            try:
                line = messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise VerificationError("Timed out waiting for offline skills/list") from exc
            if line is None:
                raise VerificationError("Offline app-server exited before its response")
            value = json.loads(line)
            if value.get("id") == request_id:
                if "error" in value:
                    raise VerificationError(f"Offline app-server error: {value['error']}")
                return value["result"]

    try:
        request(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "awesome-skills-offline-verifier", "version": "1"}},
            }
        )
        initialized = response(1)
        if Path(initialized.get("codexHome", "")) != Path(env["CODEX_HOME"]):
            raise VerificationError("App-server did not use the isolated CODEX_HOME")
        request({"method": "initialized", "params": {}})
        request({"id": 2, "method": "skills/list", "params": {"cwds": [str(work)], "forceReload": True}})
        groups = response(2)["data"]
        skills = [skill for group in groups for skill in group["skills"]]
        load_errors = [error for group in groups for error in group["errors"]]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
    for skill in skills:
        if not Path(skill["path"]).is_relative_to(Path(env["HOME"])):
            raise VerificationError(f"Discovery escaped the isolated HOME: {skill['path']}")
    return skills, load_errors, "".join(errors)


def catalog_entries(prompt: list[dict]) -> list[dict]:
    if not isinstance(prompt, list):
        raise VerificationError("Unrecognized debug prompt-input JSON shape")
    catalogs = [
        item["text"]
        for message in prompt
        for item in message.get("content", [])
        if item.get("type") == "input_text" and "<skills_instructions>" in item.get("text", "")
    ]
    if not catalogs:
        raise VerificationError("Prompt preview contains no skills catalog")
    entries = []
    for text in catalogs:
        for line in text.splitlines():
            if not line.startswith("- ") or " (file: " not in line:
                continue
            prefix, path = line[2:].rsplit(" (file: ", 1)
            name, separator, description = prefix.partition(":")
            if not separator or not path.endswith(")"):
                raise VerificationError(f"Unrecognized catalog entry: {line}")
            entries.append({"name": name, "description": description.strip(), "path": path[:-1]})
    return entries


def measure(codex: str, env: dict[str, str], work: Path, overrides: list[str] | None = None) -> dict:
    skills, errors, stderr = discover(codex, env, work)
    disabled = [arg for feature in REMOTE_FEATURES for arg in ("--disable", feature)]
    prompt = json.loads(
        run(
            [codex, "debug", "prompt-input", *disabled, *(overrides or []), "Offline skill catalog verification"],
            env,
            work,
        )
    )
    entries = catalog_entries(prompt)
    descriptions = {entry["name"]: entry["description"] for entry in entries}
    return {
        "discovered": len(skills),
        "discovered_enabled": sum(skill["enabled"] for skill in skills),
        "discovered_unique_names": len({skill["name"] for skill in skills}),
        "model_visible": len(entries),
        "with_description": sum(bool(entry["description"]) for entry in entries),
        "traversal_limit": "skills scan reached its traversal limit" in stderr,
        "load_errors": errors,
        "fixtures_discovered": {
            name: any(skill["name"] == name and skill["description"] == desc for skill in skills)
            for name, desc in FIXTURES.items()
        },
        "fixtures_visible_with_description": {name: descriptions.get(name) == desc for name, desc in FIXTURES.items()},
        "library_visible_with_description": bool(descriptions.get(ROUTER)),
    }


def prepare_fixture(source: Path, installer: Path, root: Path) -> tuple[Path, dict]:
    bundle = root / "bundle"
    library = bundle / "skills"
    library.mkdir(parents=True)
    directory_count = 0
    for entry in source.rglob("*"):
        if entry.is_dir() and not entry.is_symlink():
            (library / entry.relative_to(source)).mkdir(parents=True, exist_ok=True)
            directory_count += 1
        elif entry.name == "SKILL.md" and entry.is_file() and not entry.is_symlink():
            destination = library / entry.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(entry.read_bytes())
    if not list(library.glob("*/SKILL.md")):
        raise VerificationError(f"No top-level skill documents at {source}")
    scripts = bundle / "scripts"
    scripts.mkdir()
    helper = installer.parent / "scripts/install_skills.py" if installer.suffix == ".sh" else installer
    if not helper.is_file():
        raise VerificationError(f"Missing new installer helper: {helper}")
    shutil.copyfile(helper, scripts / "install_skills.py")
    bootstrap = helper.parent.parent / "install.sh"
    if not bootstrap.is_file():
        raise VerificationError(f"Missing local installer bootstrap: {bootstrap}")
    shutil.copyfile(bootstrap, bundle / "install.sh")
    provenance = source.parent / "library_sources.json"
    if provenance.is_file():
        shutil.copyfile(provenance, bundle / provenance.name)
    home = root / "home"
    for client in ("codex", "claude"):
        shutil.copytree(library, home / f".{client}/skills")
    agents = home / ".agents/skills"
    agents.mkdir(parents=True)
    for name, description in FIXTURES.items():
        target = home / "fixture-skill-content" / name if name == "external-linked" else agents / name
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {json.dumps(description)}\n---\nOffline fixture only.\n"
        )
        if name == "external-linked":
            (agents / name).symlink_to(target, target_is_directory=True)
    return bundle, {
        "top_level_skill_documents": len(list(library.glob("*/SKILL.md"))),
        "directories": directory_count,
        "content": "SKILL.md documents and directory layout only",
    }


def verify(codex: str, source: Path, installer: Path, compare_budget: int | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="awesome-skills-catalog-") as temporary:
        root = Path(temporary)
        home, work, scratch = root / "home", root / "work", root / "tmp"
        for path in (home, work, scratch):
            path.mkdir()
        (home / ".codex").mkdir()
        env = isolated_env(home, scratch)
        capabilities = detect_capabilities(codex, env, work, root)
        bundle, fixture = prepare_fixture(source, installer, root)
        before = measure(codex, env, work)
        larger_budget = (
            measure(codex, env, work, ["-c", f"skills.max_context_tokens={compare_budget}"]) if compare_budget else None
        )
        fixture_link = home / ".agents/skills/external-linked"
        link_before = os.readlink(fixture_link)
        agents_before = {name: (home / ".agents/skills" / name / "SKILL.md").read_bytes() for name in FIXTURES}
        run(["bash", str(bundle / "install.sh"), "--codex-only"], env, work, timeout=120)
        after = measure(codex, env, work)
        state_path = Path(env["SKILLS_STATE_DIR"]) / "codex.json"
        state_before = json.loads(state_path.read_text())
        # Deliberately no installer flags: this is the updater's invocation.
        output = run(["bash", str(bundle / "install.sh")], env, work, timeout=120)
        codex_actions = updater_actions(output, "codex")
        state_after = json.loads(state_path.read_text())
        updated = measure(codex, env, work)
        selection_preserved = state_before["selection"] == state_after["selection"]
        agents_after = {name: (home / ".agents/skills" / name / "SKILL.md").read_bytes() for name in FIXTURES}
        protected_fixtures_preserved = (
            fixture_link.is_symlink() and os.readlink(fixture_link) == link_before and agents_before == agents_after
        )
        for label, measurement in (("after", after), ("after_no_argument_update", updated)):
            if measurement["traversal_limit"] or measurement["load_errors"]:
                raise VerificationError(f"{label}: discovery still has errors or a traversal limit")
            if (
                not all(measurement["fixtures_visible_with_description"].values())
                or not measurement["library_visible_with_description"]
            ):
                raise VerificationError(f"{label}: library or external fixture descriptions are missing")
            if measurement["with_description"] != measurement["model_visible"]:
                raise VerificationError(f"{label}: model-visible descriptions were omitted")
        if not selection_preserved or codex_actions or not protected_fixtures_preserved:
            raise VerificationError("No-argument updater changed Codex selection or protected fixtures")
        summary = {
            "status": "passed",
            **capabilities,
            "fixture": fixture,
            "before": before,
            "after": after,
            "after_no_argument_update": updated,
            "no_argument_update_preserved_selection": selection_preserved,
            "no_argument_update_codex_actions": len(codex_actions),
            "protected_symlink_and_agents_preserved": protected_fixtures_preserved,
        }
        if larger_budget is not None:
            summary["before_with_larger_budget"] = {"requested_max_context_tokens": compare_budget, **larger_budget}
    summary["temporary_artifacts_removed"] = not root.exists()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex", help="local Codex executable (no model API requests)")
    parser.add_argument("--source", type=Path, default=ROOT / "skills")
    parser.add_argument("--installer", type=Path, default=ROOT / "scripts/install_skills.py")
    parser.add_argument("--compare-budget", type=int, help="also measure the old fixture with this context budget")
    args = parser.parse_args(argv)
    codex = shutil.which(args.codex)
    if not codex:
        print(json.dumps({"status": "skipped", "reason": f"Codex executable unavailable: {args.codex}"}))
        return 0
    try:
        summary = verify(codex, args.source.resolve(), args.installer.resolve(), args.compare_budget)
    except UnsupportedCodex as exc:
        summary = {"status": "skipped", "reason": str(exc)}
    except (VerificationError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
