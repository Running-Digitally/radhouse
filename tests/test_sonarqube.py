"""Merged-source and failure propagation checks; no live SonarQube calls."""
from __future__ import annotations

import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.sonarqube import ScanError, analyze, prerequisites, qualify, verified_coverage


class LocalSonarTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.remote = base / "remote"
        self.remote.mkdir()
        self.command(self.remote, "init", "-b", "main")
        self.command(self.remote, "config", "user.email", "fixture@example.invalid")
        self.command(self.remote, "config", "user.name", "Synthetic fixture")
        (self.remote / "pyproject.toml").write_text('[project]\nversion = "0.0.1"\n')
        (self.remote / "source.py").write_text("MERGED = True\n")
        (self.remote / "sonar-project.properties").write_text("sonar.projectKey=fixture\n")
        self.command(self.remote, "add", ".")
        self.command(self.remote, "commit", "-m", "merged fixture")
        self.revision = self.command(self.remote, "rev-parse", "HEAD")
        self.root = base / "developer"
        self.command(base, "clone", str(self.remote), str(self.root))
        self.command(self.root, "switch", "-c", "feature/unmerged")
        (self.root / "source.py").write_text("UNMERGED = True\n")
        (self.root / "sonar-project.properties").write_text("sonar.projectKey=fixture\n")
        self.scanner = base / "scanner"
        self.scanner.write_text(
            '#!/usr/bin/env python3\n'
            'import os, pathlib, subprocess, sys\n'
            'assert pathlib.Path("source.py").read_text() == "MERGED = True\\n"\n'
            'sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()\n'
            'assert "-Dsonar.scm.revision=" + sha in sys.argv\n'
            'assert not any(a.startswith("-Dproject.settings=") for a in sys.argv)\n'
            'base = next(pathlib.Path(a.split("=", 1)[1]).resolve() for a in sys.argv if a.startswith("-Dsonar.projectBaseDir="))\n'
            'assert base == pathlib.Path.cwd()\n'
            'assert not any("sonar.branch.name" in a or "sonar.pullrequest" in a for a in sys.argv)\n'
            'assert pathlib.Path("sonar-project.properties").read_text() == "sonar.projectKey=fixture\\n"\n'
            'print("synthetic diagnostic " + os.environ["SONAR_TOKEN"])\n'
            'sys.exit(int(os.environ.get("FIXTURE_SCANNER_EXIT", "0")))\n'
        )
        self.scanner.chmod(0o700)
        self.environment = patch.dict(os.environ, {
            "CI": "", "GITHUB_ACTIONS": "", "GITLAB_CI": "", "JENKINS_URL": "",
            "SONAR_SCANNER_JSON_PARAMS": "", "FIXTURE_SCANNER_EXIT": "0",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @staticmethod
    def command(root, *args):
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()

    def scan(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            kwargs.setdefault("coverage", False)
            return analyze(self.root, str(self.scanner), "https://sonar.example.invalid", "synthetic-token", **kwargs)

    def test_dirty_feature_checkout_scans_only_merged_main(self):
        self.assertEqual(self.scan(), 0)
        output = next((self.root / ".sonarqube").iterdir())
        receipt = json.loads((output / "receipt.json").read_text())
        self.assertEqual(receipt["source_commit"], self.revision)
        self.assertFalse(receipt["test_coverage_imported"])
        self.assertNotIn("synthetic-token", (output / "scan.log").read_text())
        self.assertEqual((self.root / "source.py").read_text(), "UNMERGED = True\n")
        self.assertEqual(self.command(self.root, "branch", "--show-current"), "feature/unmerged")

    def test_scanner_failure_is_returned(self):
        os.environ["FIXTURE_SCANNER_EXIT"] = "1"
        self.assertEqual(self.scan(), 1)

    def test_dry_run_needs_no_scanner_or_token(self):
        self.assertEqual(self.scan(dry_run=True), 0)
        self.assertFalse((self.root / ".sonarqube").exists())

    def test_analysis_token_requires_https_even_for_loopback(self):
        with self.assertRaisesRegex(ScanError, "HTTPS"):
            prerequisites(str(self.scanner), "http://localhost:9000", "synthetic-token")

    def test_hosted_ci_is_rejected(self):
        os.environ["GITHUB_ACTIONS"] = "true"
        with self.assertRaisesRegex(ScanError, "local analysis"):
            self.scan()

    def test_scanner_override_environment_is_rejected(self):
        os.environ["SONAR_SCANNER_JSON_PARAMS"] = '{"sonar.branch.name":"feature"}'
        with self.assertRaisesRegex(ScanError, "overrides"):
            self.scan()

    def test_missing_main_is_rejected_without_scanner(self):
        self.command(self.remote, "branch", "-m", "feature-only")
        with self.assertRaisesRegex(ScanError, "main branch"):
            self.scan()

    def coverage_fixture(self):
        directory = self.root / ".vs0" / "synthetic" / "coverage"
        directory.mkdir(parents=True)
        reports = {}
        for name, filename, content in (("python", "python.xml", "<coverage/>"),
                                        ("javascript", "lcov.info", "SF:source.js\nDA:1,1\nend_of_record\n")):
            path = directory / filename
            path.write_text(content)
            reports[name] = {"path": str(path.relative_to(self.root)),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        manifest = {"source_commit": self.revision, "result": "passed", "cleanup": "complete",
                    "tests": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}, "coverage": reports}
        path = directory.parent / "manifest.json"
        path.write_text(json.dumps(manifest))
        return path, manifest

    def test_verified_reports_require_matching_source_and_successful_cleanup(self):
        path, manifest = self.coverage_fixture()
        _, reports = verified_coverage(self.root, self.revision, path)
        self.assertEqual(set(reports), {"python", "javascript"})
        for field, value in (("source_commit", "foreign-head"), ("result", "failed"), ("cleanup", "pending")):
            bad = {**manifest, field: value}
            path.write_text(json.dumps(bad))
            with self.assertRaises(ScanError):
                verified_coverage(self.root, self.revision, path)

    def test_modified_reports_or_external_paths_are_rejected(self):
        path, manifest = self.coverage_fixture()
        report = self.root / manifest["coverage"]["python"]["path"]
        report.write_text("tampered")
        with self.assertRaisesRegex(ScanError, "digest"):
            verified_coverage(self.root, self.revision, path)
        manifest["coverage"]["python"]["path"] = "../../outside.xml"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ScanError, "belong"):
            verified_coverage(self.root, self.revision, path)

    def test_skipped_tests_are_not_qualified_coverage(self):
        path, manifest = self.coverage_fixture()
        manifest["tests"]["skipped"] = 1
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ScanError, "no failures"):
            verified_coverage(self.root, self.revision, path)

    def test_failed_qualification_prevents_scanner_execution(self):
        with patch("scripts.sonarqube.qualify", side_effect=ScanError("fixture failed")):
            with self.assertRaisesRegex(ScanError, "fixture failed"):
                self.scan(coverage=True)
        output = next((self.root / ".sonarqube").iterdir())
        self.assertFalse((output / "scan.log").exists())
        self.assertFalse(json.loads((output / "receipt.json").read_text())["test_coverage_imported"])

    def test_qualification_copies_bound_reports_and_withholds_analysis_token(self):
        path, _ = self.coverage_fixture()
        output = self.root / "proof"
        output.mkdir()
        def run(args, **kwargs):
            self.assertNotIn("SONAR_TOKEN", kwargs["env"])
            locator = f"Sanitized run manifest: {path.relative_to(self.root)}\n"
            return subprocess.CompletedProcess(args, 0, locator, "")
        with patch.dict(os.environ, {"SONAR_TOKEN": "synthetic-secret"}):
            with patch("scripts.sonarqube.subprocess.run", side_effect=run):
                reports, evidence = qualify(self.root, self.revision, output)
        self.assertEqual(evidence["tests"]["tests"], 1)
        self.assertTrue((output / "verification.json").is_file())
        for report in reports.values():
            self.assertEqual(report.parent, output)
            self.assertTrue(report.is_file())

    def test_main_moving_after_tests_prevents_submission(self):
        def move_main(*args):
            (self.remote / "source.py").write_text("MERGED = False\n")
            self.command(self.remote, "add", ".")
            self.command(self.remote, "commit", "-m", "new merged fixture")
            return {"python": self.root / "python.xml", "javascript": self.root / "lcov.info"}, {}
        with patch("scripts.sonarqube.qualify", side_effect=move_main):
            with self.assertRaisesRegex(ScanError, "moved"):
                self.scan(coverage=True)
        output = next((self.root / ".sonarqube").iterdir())
        self.assertFalse((output / "scan.log").exists())


if __name__ == "__main__":
    unittest.main()
