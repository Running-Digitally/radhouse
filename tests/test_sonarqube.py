"""Merged-source and failure propagation checks; no live SonarQube calls."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.sonarqube import ScanError, analyze


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
            'assert not any("sonar.branch.name" in a or "sonar.pullrequest" in a for a in sys.argv)\n'
            'assert not pathlib.Path("sonar-project.properties").exists()\n'
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


if __name__ == "__main__":
    unittest.main()
