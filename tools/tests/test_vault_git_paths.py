"""Git path parsing must not leave Git's quoting on paths with spaces or non-ASCII names.

Run with: uv run python -m unittest discover -s tools/tests
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import vault

SPACED = "notes/my file.md"
ACCENTED = "notes/café.md"
PLAIN = "notes/plain.md"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class GitPathParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "test")
        git(self.root, "config", "core.quotePath", "true")
        (self.root / "notes").mkdir()
        for name in (SPACED, ACCENTED, PLAIN):
            (self.root / name).write_text("x\n", encoding="utf-8")
        patcher = mock.patch.object(vault, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_status_paths_untracked(self) -> None:
        self.assertEqual(sorted(vault.status_paths()), sorted([SPACED, ACCENTED, PLAIN]))

    def test_status_paths_rename_reports_new_path_only(self) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "init")
        git(self.root, "mv", SPACED, "notes/renamed file.md")
        self.assertEqual(vault.status_paths(), ["notes/renamed file.md"])

    def test_staged_and_tracked_names(self) -> None:
        git(self.root, "add", "-A")
        self.assertEqual(sorted(vault.staged_names()), sorted([SPACED, ACCENTED, PLAIN]))
        git(self.root, "commit", "-qm", "init")
        self.assertEqual(vault.tracked_names(), {SPACED, ACCENTED, PLAIN})

    def test_parse_porcelain_z_copy_and_rename(self) -> None:
        output = b"R  new name.md\0old name.md\0C  copy.md\0src.md\0?? a b.md\0"
        self.assertEqual(vault.parse_porcelain_z(output), ["new name.md", "copy.md", "a b.md"])


if __name__ == "__main__":
    unittest.main()
