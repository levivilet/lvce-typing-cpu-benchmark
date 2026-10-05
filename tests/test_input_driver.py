from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from input_driver import XdotoolInput, check_cadence, expected_text, type_at_cadence


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class InputDriverTests(unittest.TestCase):
    def test_expected_text_is_deterministic_and_ascii(self):
        self.assertEqual(expected_text(40), "abcdefghijklmnopqrstuvwxyz0123456789abcd")

    def test_schedule_sends_every_character_at_the_requested_cadence(self):
        clock = Clock()
        sent = []
        samples = []
        offsets = type_at_cadence(
            "abc", 1, 3, sent.append, samples.append,
            clock=clock.monotonic, sleep=clock.sleep,
        )
        self.assertEqual(sent, list("abc"))
        self.assertEqual(offsets, [0, 1, 2])
        self.assertEqual(samples[0], 0)
        self.assertEqual(samples[-1], 3)

    def test_cadence_validation_rejects_missed_or_reversed_input(self):
        check_cadence([0, 1, 2], 1)
        for offsets in ([0, 1.6, 2], [0, 1, .5]):
            with self.subTest(offsets=offsets), self.assertRaisesRegex(ValueError, "cadence"):
                check_cadence(offsets, 1)

    def test_xdotool_driver_focuses_fixture_window_and_verifies_focus(self):
        search = mock.Mock(returncode=0, stdout="123\n", stderr="")
        focus = mock.Mock(returncode=0, stdout="typing-cpu.txt - Editor\n", stderr="")
        with mock.patch("input_driver.subprocess.run", side_effect=[
                search, mock.Mock(), mock.Mock(), mock.Mock(), focus, focus,
                mock.Mock(), mock.Mock()]) as run:
            keyboard = XdotoolInput("typing-cpu.txt")
            keyboard.clear()
        self.assertEqual(keyboard.window_id, "123")
        self.assertEqual(run.call_args_list[1].args[0], ["xdotool", "windowfocus", "--sync", "123"])
        self.assertEqual(run.call_args_list[2].args[0], ["xdotool", "mousemove", "--window", "123", "800", "250"])
        self.assertEqual(run.call_args_list[4].args[0], ["xdotool", "getwindowfocus", "getwindowname"])

    def test_editor_click_uses_pointer_input_instead_of_top_level_send_event(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        keyboard.window_id = "123"
        with mock.patch.object(keyboard, "_require_focus"), \
                mock.patch("input_driver.subprocess.run") as run:
            keyboard.click_editor((800, 250))
        self.assertEqual(run.call_args_list[-1].args[0], ["xdotool", "click", "1"])

    def test_clear_waits_for_selection_and_cut_before_save(self):
        clock = Clock()
        initial = "First fixture line.\nSecond fixture line.\n"
        keyboard = XdotoolInput.__new__(XdotoolInput)
        keyboard.window_id = "123"
        events = []
        def selection(expected):
            events.append(("selection", expected))
            clock.sleep(.2)
        def cut(deadline, key):
            self.assertEqual(events[-1], ("selection", {initial}))
            self.assertEqual(key, "ctrl+x")
            clock.sleep(.3)
            events.append(("cut", initial))
            return initial
        with mock.patch.object(keyboard, "_require_focus"), \
                mock.patch.object(keyboard, "press_key", side_effect=lambda key: events.append(key)), \
                mock.patch.object(keyboard, "_wait_for_selection", side_effect=selection), \
                mock.patch.object(keyboard, "_clipboard_text", side_effect=cut), \
                mock.patch("input_driver.subprocess.run"), \
                mock.patch("input_driver.time.monotonic", clock.monotonic):
            keyboard.clear(initial)
        self.assertEqual(events, [("selection", {"First", initial}), "ctrl+a",
                                  ("selection", {initial}), ("cut", initial)])

    def test_copied_text_rejects_a_stale_clipboard_value(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        clock = Clock()
        marker = "typing-cpu-clipboard-123"
        responses = [mock.Mock(), mock.Mock(returncode=0, stdout=marker),
                     mock.Mock(returncode=0, stdout="selected fixture")]
        with mock.patch.object(keyboard, "press_key"), \
                mock.patch("input_driver.time.monotonic_ns", return_value=123), \
                mock.patch("input_driver.time.monotonic", clock.monotonic), \
                mock.patch("input_driver.time.sleep", clock.sleep), \
                mock.patch("input_driver.subprocess.run", side_effect=responses):
            self.assertEqual(keyboard._clipboard_text(1), "selected fixture")
        self.assertGreater(clock.now, 0)

    def test_cut_is_sent_only_once_while_waiting_for_its_acknowledgement(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        clock = Clock()
        marker = "typing-cpu-clipboard-123"
        responses = [mock.Mock(), mock.Mock(returncode=0, stdout=marker),
                     mock.Mock(returncode=0, stdout=marker),
                     mock.Mock(returncode=0, stdout="selected fixture")]
        with mock.patch.object(keyboard, "press_key") as press, \
                mock.patch("input_driver.time.monotonic_ns", return_value=123), \
                mock.patch("input_driver.time.monotonic", clock.monotonic), \
                mock.patch("input_driver.time.sleep", clock.sleep), \
                mock.patch("input_driver.subprocess.run", side_effect=responses):
            self.assertEqual(keyboard._clipboard_text(1, "ctrl+x"), "selected fixture")
        press.assert_called_once_with("ctrl+x")

    def test_selection_readback_waits_without_sending_copy_or_changing_selection(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        clock = Clock()
        selected = "First fixture line.\nSecond fixture line.\n"
        responses = [mock.Mock(returncode=0, stdout="typing-cpu-selection"),
                     mock.Mock(returncode=0, stdout="First"),
                     mock.Mock(returncode=0, stdout=selected)]
        with mock.patch("input_driver.subprocess.run", side_effect=responses) as run, \
                mock.patch.object(keyboard, "press_key") as press, \
                mock.patch("input_driver.time.monotonic", clock.monotonic), \
                mock.patch("input_driver.time.sleep", clock.sleep):
            keyboard._wait_for_selection({selected})
        self.assertGreater(clock.now, 0)
        press.assert_not_called()
        self.assertTrue(all(call.args[0] == ["xclip", "-selection", "primary", "-o"]
                            for call in run.call_args_list))

    def test_selection_readiness_rejects_input_in_another_widget(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        clock = Clock()
        with mock.patch("input_driver.subprocess.run", return_value=mock.Mock(returncode=0, stdout="project/file.txt")), \
                mock.patch("input_driver.time.monotonic", clock.monotonic), \
                mock.patch("input_driver.time.sleep", clock.sleep):
            with self.assertRaisesRegex(RuntimeError, "expected selection state"):
                keyboard._wait_for_selection({"First fixture line.\nSecond fixture line.\n"})

    def test_xdotool_driver_rejects_missing_fixture_window(self):
        with mock.patch("input_driver.subprocess.run", return_value=mock.Mock(
                returncode=1, stdout="", stderr="")):
            with self.assertRaisesRegex(RuntimeError, "no visible editor window"):
                XdotoolInput("typing-cpu.txt", wait_seconds=0)

    def test_open_file_uses_editor_specific_shortcut(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        keyboard.window_pattern = "IntelliJ"
        with mock.patch.object(keyboard, "_require_focus"), \
                mock.patch("input_driver.subprocess.run") as run, \
                mock.patch("input_driver.time.sleep"):
            keyboard.open_file("typing-cpu.txt", "ctrl+shift+n")
        self.assertEqual(run.call_args_list[0].args[0],
                         ["xdotool", "key", "--clearmodifiers", "ctrl+shift+n"])
        self.assertEqual(run.call_args_list[1].args[0][0:4],
                         ["xdotool", "type", "--clearmodifiers", "--delay"])
        self.assertEqual(run.call_args_list[2].args[0],
                         ["xdotool", "key", "--clearmodifiers", "Return"])

    def test_dialog_click_uses_client_coordinates_for_decorated_windows(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        geometry = mock.Mock(stdout="X=425\nY=117\nWIDTH=424\nHEIGHT=458\n")
        with mock.patch("input_driver.subprocess.run", side_effect=[
                geometry, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock(stdout=""), mock.Mock()]) as run, \
                mock.patch.object(keyboard, "_visible_window", return_value="456"), \
                mock.patch("input_driver.time.sleep"):
            keyboard.accept_idea_project_root()
        self.assertEqual(run.call_args_list[2].args[0],
                         ["xdotool", "mousemove", "--window", "456", "289", "431"])
        self.assertEqual(run.call_args_list[3].args[0], ["xdotool", "click", "1"])

    def test_idea_navigates_to_the_fixture_before_relying_on_editor_focus(self):
        keyboard = XdotoolInput.__new__(XdotoolInput)
        keyboard.window_id = "123"
        with mock.patch.object(keyboard, "_require_focus"), \
                mock.patch.object(keyboard, "_visible_window", return_value="456"), \
                mock.patch.object(keyboard, "open_file") as open_file, \
                mock.patch("input_driver.subprocess.run") as run:
            keyboard.open_idea_file("typing-cpu.txt")
        self.assertEqual(keyboard.window_id, "456")
        self.assertEqual(run.call_args_list[0].args[0],
                         ["xdotool", "windowfocus", "--sync", "456"])
        self.assertEqual(keyboard.focus_patterns, [r"^typing-cpu .*typing\-cpu\.txt$"])
        open_file.assert_called_once_with("typing-cpu.txt", "ctrl+shift+n")


if __name__ == "__main__":
    unittest.main()
