import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install


class EditorLockTest(unittest.TestCase):
    def test_matrix_is_pinned_or_explicitly_runner_provided(self):
        editors = json.loads((ROOT / "config/editors.lock.json").read_text())
        self.assertEqual(len(editors), len({editor["id"] for editor in editors}))
        for editor in editors:
            self.assertTrue(editor["version"])
            self.assertTrue(editor["binary"])
            if editor.get("package"):
                self.assertEqual(editor["id"], "geany")
            else:
                self.assertRegex(editor["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(editor["url"].startswith("https://"))

    def test_download_uses_browser_user_agent_and_verifies_checksum(self):
        payload = b"checksum-verified editor archive"
        entry = {
            "id": "cursor", "version": "3.22.12", "url": "https://example.com/cursor.deb",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.object(
            install.urllib.request, "urlopen", return_value=io.BytesIO(payload)
        ) as urlopen:
            archive = Path(directory) / "cursor.deb"
            install.download(entry, archive)
            self.assertEqual(archive.read_bytes(), payload)
            self.assertEqual(urlopen.call_args.args[0].get_header("User-agent"), "Mozilla/5.0")

    def test_codemirror_apps_are_built_from_locked_dependencies(self):
        self.assertEqual(install.BUILD_APPS, {"codemirror5-electron", "codemirror-electron"})
        editors = json.loads((ROOT / "config/editors.lock.json").read_text())
        self.assertEqual(len(editors), 14)
        self.assertEqual({editor["id"] for editor in editors} & {"codemirror5", "codemirror6"},
                         {"codemirror5", "codemirror6"})
        for app, package in (("codemirror5-electron", "codemirror"),
                             ("codemirror-electron", "@codemirror/view")):
            manifest = json.loads((ROOT / app / "package.json").read_text())
            lock = json.loads((ROOT / app / "package-lock.json").read_text())
            self.assertIn(package, manifest["dependencies"])
            self.assertEqual(lock["packages"][""]["dependencies"], manifest["dependencies"])
            self.assertIn("esbuild", manifest["devDependencies"])
