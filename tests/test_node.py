import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from support import runner
from test_runner import fixture_archive


def node_archive(version):
    filename = f"node-v{version}-darwin-arm64.tar.gz"
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        member = tarfile.TarInfo(filename.removesuffix(".tar.gz") + "/bin/node")
        member.size = 4
        tar.addfile(member, io.BytesIO(b"node"))
    return filename, data.getvalue()


class NodeTests(unittest.TestCase):
    def test_version_files_engines_and_ci_agree(self):
        baseline = runner.load_scenario()["baseline"]
        version = (baseline / ".node-version").read_text().strip()
        self.assertRegex(version, r"^26\.\d+\.\d+$")
        self.assertFalse((runner.ROOT / ".node-version").exists())
        manifest = json.loads((baseline / "frontend/package.json").read_text())
        lock = json.loads((baseline / "frontend/package-lock.json").read_text())
        self.assertEqual(manifest["engines"], {"node": ">=26 <27"})
        self.assertEqual(lock["packages"][""]["engines"], manifest["engines"])
        ci = (baseline / ".github/workflows/ci.yml").read_text()
        self.assertIn("node-version-file: .node-version", ci)
        checks = (baseline / "scripts/check.sh").read_text()
        self.assertIn("process.versions.node !== expected", checks)
        ci = (runner.ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("node-version-file: scenarios/field-notes/baseline/.node-version", ci)
        checks = (runner.ROOT / "scripts/check.sh").read_text()
        self.assertNotIn("process.versions.node", checks)
        self.assertNotIn(".node-version", checks)
        self.assertIn("bash scenarios/field-notes/baseline/scripts/check.sh", checks)

    def test_staging_uses_archive_pin_and_checks_executable(self):
        for version in ["26.5.0", "26.6.0"]:
            filename, archive = node_archive(version)
            checksum = f"{hashlib.sha256(archive).hexdigest()}  {filename}\n".encode()
            for actual in [f"v{version}\n", "v25.0.0\n"]:
                with (
                    self.subTest(version=version, actual=actual),
                    tempfile.TemporaryDirectory() as temp,
                ):
                    root = Path(temp)
                    with (
                        patch("runner.os.uname") as uname,
                        patch(
                            "runner.urllib.request.urlopen",
                            side_effect=[io.BytesIO(checksum), io.BytesIO(archive)],
                        ) as request,
                        patch("runner.command", return_value=actual) as command,
                    ):
                        uname.return_value.machine = "arm64"
                        if actual == f"v{version}\n":
                            self.assertEqual(
                                runner.prepare_tools(root, fixture_archive(version)), root
                            )
                            self.assertEqual((root / "node/bin/node").read_bytes(), b"node")
                        else:
                            with self.assertRaisesRegex(RuntimeError, "Staged Node version"):
                                runner.prepare_tools(root, fixture_archive(version))
                        base = f"https://nodejs.org/dist/v{version}/"
                        self.assertEqual(
                            request.call_args_list,
                            [
                                call(base + "SHASUMS256.txt", timeout=30),
                                call(base + filename, timeout=120),
                            ],
                        )
                        command.assert_called_once_with([str(root / "node/bin/node"), "--version"])

    def test_staging_rejects_checksum_mismatch_before_extraction(self):
        version = "26.6.0"
        filename, archive = node_archive(version)
        checksum = f"{'0' * 64}  {filename}\n".encode()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch("runner.os.uname") as uname,
                patch(
                    "runner.urllib.request.urlopen",
                    side_effect=[io.BytesIO(checksum), io.BytesIO(archive)],
                ),
                patch("runner.command") as command,
            ):
                uname.return_value.machine = "arm64"
                with self.assertRaisesRegex(RuntimeError, "Node archive checksum mismatch"):
                    runner.prepare_tools(root, fixture_archive(version))
                command.assert_not_called()
                self.assertFalse((root / "node").exists())
                self.assertFalse((root / filename.removesuffix(".tar.gz")).exists())

    def test_archive_without_node_pin_skips_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch("runner.urllib.request.urlopen") as request,
                patch("runner.command") as command,
            ):
                self.assertEqual(runner.prepare_tools(root, fixture_archive()), root)
                request.assert_not_called()
                command.assert_not_called()
            self.assertTrue((root / "bin").is_dir())
            self.assertFalse((root / "node").exists())
