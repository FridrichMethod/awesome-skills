#!/usr/bin/env python3
"""Dependency-free synthetic tests for all bundled PufferLib CLIs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import env_template  # noqa: E402
import validate_plan  # noqa: E402


def run_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / name), *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=30,
    )


class SyntheticEnvironmentTests(unittest.TestCase):
    def test_seeded_trace_is_deterministic(self) -> None:
        first = env_template.SyntheticGymEnv(max_steps=8)
        second = env_template.SyntheticGymEnv(max_steps=8)
        self.assertEqual(first.reset(seed=7), second.reset(seed=7))
        for action in (0, 2, 1, 0):
            self.assertEqual(first.step(action), second.step(action))

    def test_contract_validator(self) -> None:
        result = run_script(
            "env_contract_validator.py",
            "--steps",
            "24",
            "--episodes",
            "4",
            "--compact",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["network_used"])


class CliTests(unittest.TestCase):
    def test_all_help_commands_are_dependency_free(self) -> None:
        names = (
            "env_template.py",
            "env_contract_validator.py",
            "benchmark_vectorization.py",
            "train_template.py",
            "validate_plan.py",
            "inspect_checkpoint.py",
            "repro_plan.py",
        )
        for name in names:
            with self.subTest(name=name):
                result = run_script(name, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.lower())

    def test_serial_benchmark_is_bounded_json(self) -> None:
        result = run_script(
            "benchmark_vectorization.py",
            "--envs",
            "2",
            "--steps-per-env",
            "8",
            "--repeats",
            "1",
            "--warmup-steps",
            "0",
            "--compact",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["total_agent_steps_per_repeat"], [16])
        self.assertFalse(report["network_used"])

    def test_train_template_defaults_to_dry_run(self) -> None:
        result = run_script("train_template.py", "--compact")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["command_preview"], [])
        self.assertEqual(report["plan"]["logging"]["backend"], "none")

    def test_source_profile_uses_torch_dry_run(self) -> None:
        result = run_script(
            "train_template.py", "--profile", "source-4.0", "--compact"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["plan"]["vectorization"]["backend"], "torch")
        self.assertEqual(report["plan"]["checkpoint"]["format"], "state_dict")

    def test_external_logger_requires_two_opt_ins(self) -> None:
        result = run_script("train_template.py", "--logger", "wandb", "--compact")
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "invalid")
        self.assertTrue(report["errors"])

    def test_external_logger_never_reads_credential_value(self) -> None:
        result = run_script(
            "train_template.py",
            "--logger",
            "wandb",
            "--enable-external-logging",
            "--acknowledge-external-disclosure",
            "--compact",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["credential"]["environment_variable"], "WANDB_API_KEY")
        self.assertFalse(report["credential"]["value_read_or_logged"])

    def test_source_profile_rejects_neptune(self) -> None:
        result = run_script(
            "train_template.py",
            "--profile",
            "source-4.0",
            "--logger",
            "neptune",
            "--enable-external-logging",
            "--acknowledge-external-disclosure",
            "--compact",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a current source-4.0 integration", result.stdout)

    def test_repro_plan_separates_seeds(self) -> None:
        result = run_script(
            "repro_plan.py", "--replicates", "2", "--eval-episodes", "3", "--compact"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(
            set(report["training"]["seeds"]).isdisjoint(
                report["evaluation"]["seeds"]
            )
        )


class PlanValidationTests(unittest.TestCase):
    def test_default_plans_validate(self) -> None:
        for profile in validate_plan.PROFILES:
            with self.subTest(profile=profile):
                self.assertEqual(validate_plan.validate_plan(validate_plan.default_plan(profile)), [])

    def test_secret_key_is_rejected(self) -> None:
        plan = validate_plan.default_plan()
        plan["logging"]["api_token"] = None
        errors = validate_plan.validate_plan(plan)
        self.assertTrue(any("credential-bearing" in error for error in errors))

    def test_external_environment_requires_attested_provenance(self) -> None:
        result = run_script(
            "train_template.py",
            "--environment",
            "reviewed-env",
            "--adapter",
            "gymnasium",
            "--compact",
        )
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertTrue(any("provenance_verified" in error for error in report["errors"]))

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.json").write_text(
                '{"schema_version":1,"schema_version":1}', encoding="utf-8"
            )
            result = run_script(
                "validate_plan.py",
                "--root",
                str(root),
                "--config",
                "plan.json",
                "--compact",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("duplicate JSON key", result.stdout)


class CheckpointInspectorTests(unittest.TestCase):
    def test_inspector_hashes_without_deserialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"\x80\x04synthetic-not-executable"
            checkpoint = root / "sample.pt"
            checkpoint.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            sidecar = root / "sample.metadata.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "format": "state_dict",
                        "sha256": digest,
                        "seed": 42,
                    }
                ),
                encoding="utf-8",
            )
            result = run_script(
                "inspect_checkpoint.py",
                "sample.pt",
                "--root",
                str(root),
                "--metadata",
                "sample.metadata.json",
                "--expected-sha256",
                digest,
                "--compact",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["deserialized"])
            self.assertTrue(report["expected_sha256_matches"])
            self.assertTrue(report["metadata_sha256_matches"])
            self.assertEqual(
                report["checkpoint"]["format_detection"]["family"], "pickle-like"
            )


if __name__ == "__main__":
    unittest.main()
