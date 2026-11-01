#!/usr/bin/env python3
"""Verify a Codex install against Codex's offline discovery and prompt preview.

Every installed Codex path must be discovered under its ID with a unique name, and the
model's catalog may hold only system skills, the router, the visible selection and skills
outside the library. The fixture copies SKILL.md documents, agents/openai.yaml files,
plugin manifests and directory layout, never credentials or other supporting files. All
HOME, discovery, state, cache and working paths are temporary. No model turns are started.
Missing experimental interfaces produce an explicit JSON skip; a supported interface that
fails validation produces an error. The traversal-limit error Codex logs for a root of more
than 2,000 directories is reported, not failed: top-level skills are read first.
"""

from __future__ import annotations

import argparse
import collections
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
PLUGIN_DIRS = {".claude-plugin", ".codex-plugin", ".cursor-plugin"}


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
    """A run with nothing to change prints one line; any other run prints its JSON plan first,
    or for a large plan one summary line per client."""
    text = output.strip()
    if text == "Already current; selection preserved.":
        return []
    if not text.startswith("{"):
        lines = [line for line in text.splitlines() if line.startswith((f"Updated {client}:", f"Migrated {client}:"))]
        return [line for line in lines if not line.startswith(f"Updated {client}: 0 copied, 0 removed;")]
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


def installed_paths(state: dict) -> dict:
    """Installed SKILL.md (resolved) -> the name it must be discovered under: its ID."""
    roots = [state["destination"], state.get("destination2")]
    return {
        str((Path(roots[record.get("root", 0)]) / entry / "SKILL.md").resolve()): entry
        for entry, record in state["managed"].items()
    }


def catalog_problems(state: dict, skills: list[dict], entries: list[dict]) -> list[str]:
    """Installed paths not discovered under their ID, names discovered twice (a plain `$name`
    then injects neither), and installed skills in the model's catalog that are not in the
    visible selection: nested skills and hidden ones. Skills outside the library may show."""
    installed = installed_paths(state)
    found = {str(Path(skill["path"]).resolve()): skill for skill in skills}
    problems = []
    for path, name in installed.items():
        skill = found.get(path)
        if skill is None or skill["name"] != name:
            problems.append(f"{path}: {'not discovered' if skill is None else 'discovered as ' + skill['name']}")
    names = collections.Counter(skill["name"] for skill in skills if skill.get("enabled", True))
    problems += [f"{name!r} is discovered {count} times" for name, count in sorted(names.items()) if count > 1]
    selection = set(state["selection"])
    visible = set(state["managed"]) if "@all" in selection else selection | ({ROUTER} & set(state["managed"]))
    folders = {str(Path(path).parent) for path in installed}
    shown = {}  # name of an installed skill -> whether the model may see it
    for path, skill in found.items():
        if path in installed or any(str(parent) in folders for parent in Path(path).parents):
            shown[skill["name"]] = path in installed and skill["name"] in visible
    problems += [f"{entry['name']} is in the model's catalog" for entry in entries if shown.get(entry["name"]) is False]
    return problems


def measure(
    codex: str, env: dict[str, str], work: Path, overrides: list[str] | None = None, state: dict | None = None
) -> dict:
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
    problems = {} if state is None else {"catalog_problems": catalog_problems(state, skills, entries)}
    return problems | {
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
        elif metadata_file(entry.relative_to(source)) and entry.is_file() and not entry.is_symlink():
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
    for name in ("search_skills.py", "sync_skills.py"):  # the installer checks a local tree with the sync
        if helper.with_name(name).is_file():
            shutil.copyfile(helper.with_name(name), scripts / name)
    bootstrap = helper.parent.parent / "install.sh"
    if not bootstrap.is_file():
        raise VerificationError(f"Missing local installer bootstrap: {bootstrap}")
    shutil.copyfile(bootstrap, bundle / "install.sh")
    for name in ("library_sources.json", "library_index.json"):
        if (source.parent / name).is_file():
            shutil.copyfile(source.parent / name, bundle / name)
    home = root / "home"
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
        "content": "SKILL.md, agents/openai.yaml, plugin manifests and directory layout only",
    }


def metadata_file(rel: Path) -> bool:
    """What the installer edits or drops: copied into the fixture, unlike other support files."""
    return rel.name == "SKILL.md" or rel.parts[-2:] == ("agents", "openai.yaml") or bool(PLUGIN_DIRS & set(rel.parts))


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
        run(["bash", str(bundle / "install.sh"), "--codex-only"], env, work, timeout=900)
        state_path = Path(env["SKILLS_STATE_DIR"]) / "codex.json"
        state_before = json.loads(state_path.read_text())
        after = measure(codex, env, work, state=state_before)
        # Deliberately no installer flags: this is the updater's invocation.
        output = run(["bash", str(bundle / "install.sh")], env, work, timeout=900)
        codex_actions = updater_actions(output, "codex")
        state_after = json.loads(state_path.read_text())
        updated = measure(codex, env, work, state=state_after)
        selection_preserved = state_before["selection"] == state_after["selection"]
        agents_after = {name: (home / ".agents/skills" / name / "SKILL.md").read_bytes() for name in FIXTURES}
        protected_fixtures_preserved = (
            fixture_link.is_symlink() and os.readlink(fixture_link) == link_before and agents_before == agents_after
        )
        for label, measurement in (("after", after), ("after_no_argument_update", updated)):
            if measurement["load_errors"] or measurement["catalog_problems"]:
                found = measurement["load_errors"][:5] or measurement["catalog_problems"][:5]
                raise VerificationError(f"{label}: discovery or catalog problems: {found}")
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
    parser.add_argument(
        "--compare-budget", type=int, help="also measure the fixture before installing with this budget"
    )
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
