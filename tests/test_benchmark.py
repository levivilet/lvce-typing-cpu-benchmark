from pathlib import Path
import sqlite3
import json
import os
import tempfile
import unittest
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import benchmark


class FixtureReadinessTests(unittest.TestCase):
    def test_waits_for_the_saved_clear_instead_of_the_window_title(self):
        fixture = mock.Mock()
        fixture.read_text.side_effect = ["original fixture", "original fixture", ""]
        with mock.patch.object(benchmark.time, "sleep") as sleep:
            benchmark.wait_for_cleared_fixture(fixture)
        self.assertEqual(sleep.call_count, 2)

    def test_rejects_a_clear_sent_to_a_different_widget(self):
        fixture = mock.Mock()
        fixture.read_text.return_value = "original fixture"
        with self.assertRaisesRegex(RuntimeError, "cleared benchmark fixture"):
            benchmark.wait_for_cleared_fixture(fixture, timeout=0)


class CursorBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.editor = benchmark.load_editor("cursor")

    def test_cursor_command_uses_an_isolated_profile_and_skips_welcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / ".tmp/apps/cursor/usr/share/cursor/cursor"
            binary.parent.mkdir(parents=True)
            binary.touch()
            with mock.patch.object(benchmark, "ROOT", root):
                command = benchmark.command_for(self.editor, root / "home")
        self.assertIn("--user-data-dir", command)
        self.assertIn("--skip-welcome", command)
        self.assertIn("--skip-release-notes", command)
        self.assertIn("--disable-workspace-trust", command)
        self.assertIn("--disable-extensions", command)

    def test_profile_welcome_state_is_repeat_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            database = home / "profile/User/globalStorage/state.vscdb"
            database.parent.mkdir(parents=True)
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
                connection.execute("INSERT INTO ItemTable VALUES (?, ?)", (
                    "cursorai/donotchange/privacyMode", "false"
                ))
            benchmark.prepare_cursor_profile(self.editor, home, {}, home / "out.log", home / "err.log")
            benchmark.prepare_cursor_profile(self.editor, home, {}, home / "out.log", home / "err.log")
            with sqlite3.connect(database) as connection:
                values = dict(connection.execute("SELECT key, value FROM ItemTable"))
            self.assertEqual(values, benchmark.CURSOR_WELCOME_VALUES)

    def test_workbench_wait_rejects_missing_fixture_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "typing-cpu.txt"
            with mock.patch.object(benchmark.time, "monotonic", side_effect=[0, 1]), \
                    mock.patch.object(benchmark.subprocess, "run", return_value=mock.Mock(
                        returncode=1, stdout="", stderr="")):
                with self.assertRaisesRegex(RuntimeError, "did not show the benchmark fixture"):
                    benchmark.wait_for_cursor_workbench(fixture, timeout=0.5)

    def test_workbench_wait_requires_fixture_in_visible_window_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "typing-cpu.txt"
            visible = mock.Mock(returncode=0, stdout="17\n", stderr="")
            title = mock.Mock(returncode=0, stdout="typing-cpu.txt - Cursor", stderr="")
            with mock.patch.object(benchmark.subprocess, "run", side_effect=[visible, title]) as run:
                benchmark.wait_for_cursor_workbench(fixture)
            self.assertEqual(run.call_args_list[0].args[0][:4], [
                "xdotool", "search", "--onlyvisible", "--name"
            ])


class LvceProfileTests(unittest.TestCase):
    def test_lvce_preserves_home_and_isolates_application_directories(self):
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.dict(os.environ, {"HOME": "/real-home"}), \
                mock.patch.object(benchmark, "command_for", return_value=["fake-lvce"]), \
                mock.patch.object(benchmark.subprocess, "Popen", return_value=process) as launch, \
                mock.patch.object(benchmark, "make_input"), \
                mock.patch.object(benchmark, "typing_measurement", return_value={}), \
                mock.patch.object(benchmark, "prepare_lvce_fixture"), \
                mock.patch.object(benchmark, "terminate_process_group"), \
                mock.patch.object(benchmark.time, "sleep"):
            result = benchmark.trial(benchmark.load_editor("lvce"), 0, 180, "xdotool", 1)
        self.assertTrue(result["valid"])
        environment = launch.call_args.kwargs["env"]
        self.assertEqual(environment["HOME"], "/real-home")
        directories = [environment[f"XDG_{kind}_HOME"] for kind in ("CONFIG", "DATA", "CACHE", "STATE")]
        self.assertEqual(len(set(directories)), 4)
        for directory in directories:
            self.assertTrue(Path(directory).parent.parent.name.startswith("typing-cpu-lvce-"), directory)
            self.assertNotIn("/real-home", directory)


if __name__ == "__main__":
    unittest.main()


class ZedProfileTests(unittest.TestCase):
    def test_trust_setting_is_scoped_to_the_custom_disposable_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            benchmark.prepare_zed_profile(home)
            settings = json.loads((home / "profile/config/settings.json").read_text())
            self.assertEqual(settings, {"session": {"trust_all_worktrees": True}})
            self.assertFalse((home / "config/zed/settings.json").exists())

    def test_profile_is_ready_before_launching_zed(self):
        process = mock.Mock()
        process.poll.return_value = None
        def launch(command, **options):
            home = Path(options["env"]["HOME"])
            self.assertTrue((home / "profile/config/settings.json").exists())
            self.assertEqual(json.loads((home / "profile/config/settings.json").read_text()),
                             {"session": {"trust_all_worktrees": True}})
            return process
        with (
            mock.patch.object(benchmark, "command_for", return_value=["fake-zed"]),
            mock.patch.object(benchmark.subprocess, "Popen", side_effect=launch),
            mock.patch.object(benchmark, "make_input"),
            mock.patch.object(benchmark, "typing_measurement", return_value={}),
            mock.patch.object(benchmark, "terminate_process_group"),
            mock.patch.object(benchmark.time, "sleep"),
        ):
            result = benchmark.trial(benchmark.load_editor("zed"), 0, 180, "xdotool", 1)
        self.assertTrue(result["valid"])


class LvceFixturePreparationTests(unittest.TestCase):
    def test_waits_for_saved_empty_buffer_before_measurement(self):
        keyboard = mock.Mock()
        with mock.patch.object(benchmark, "wait_for_cleared_fixture") as wait:
            benchmark.prepare_lvce_fixture(keyboard, mock.Mock(), "initial")
        keyboard.clear.assert_called_once()
        keyboard.save.assert_called_once()
        keyboard.press_key.assert_not_called()
        wait.assert_called_once()

    def test_recovers_unchanged_initial_fixture_once_after_readiness_failure(self):
        keyboard = mock.Mock()
        fixture = mock.Mock()
        fixture.read_text.return_value = "initial"
        with mock.patch.object(benchmark, "wait_for_cleared_fixture",
                               side_effect=[RuntimeError("not cleared"), None]) as wait:
            benchmark.prepare_lvce_fixture(keyboard, fixture, "initial")
        self.assertEqual(keyboard.press_key.call_args_list, [
            mock.call("ctrl+Home"), mock.call("ctrl+a"), mock.call("ctrl+x")
        ])
        self.assertEqual(keyboard.save.call_count, 2)
        self.assertEqual(wait.call_count, 2)

    def test_rejects_unexpected_buffer_changes(self):
        keyboard = mock.Mock()
        fixture = mock.Mock()
        fixture.read_text.return_value = "unexpected"
        with mock.patch.object(benchmark, "wait_for_cleared_fixture",
                               side_effect=RuntimeError("not cleared")):
            with self.assertRaisesRegex(RuntimeError, "not cleared"):
                benchmark.prepare_lvce_fixture(keyboard, fixture, "initial")
        keyboard.press_key.assert_not_called()

    def test_second_clear_failure_still_invalidates_trial(self):
        keyboard = mock.Mock()
        fixture = mock.Mock()
        fixture.read_text.return_value = "initial"
        with mock.patch.object(benchmark, "wait_for_cleared_fixture",
                               side_effect=RuntimeError("not cleared")) as wait:
            with self.assertRaisesRegex(RuntimeError, "not cleared"):
                benchmark.prepare_lvce_fixture(keyboard, fixture, "initial")
        self.assertEqual(wait.call_count, 2)
