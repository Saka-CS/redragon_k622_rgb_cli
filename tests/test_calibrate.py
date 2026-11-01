import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from k622rgb import calibrate, controller, layout, state

FIXTURE = Path(__file__).parent / "data" / "k622-if1-descriptor.bin"


def scripted(answers):
    iterator = iter(answers)

    def _input(_prompt=""):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError

    return _input


class CalibrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.layout_path = self.root / "layout.json"
        self.state_path = self.root / "last-frame.bin"
        self.node = str(self.root / "hidraw6")
        env = mock.patch.dict(
            os.environ,
            {
                layout.LAYOUT_FILE_ENV: str(self.layout_path),
                state.STATE_FILE_ENV: str(self.state_path),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        layout.clear_calibration_cache()
        self.addCleanup(layout.clear_calibration_cache)

        self.info = controller.DeviceInfo(
            node=self.node,
            sysfs=str(self.root / "sysfs"),
            interface="01",
            hid_id="0003:0000258A:00000049",
        )

        self.descriptor = self._patch(
            "k622rgb.calibrate.controller.load_descriptor",
            return_value=FIXTURE.read_bytes(),
        )
        self._patch(
            "k622rgb.calibrate.controller.iter_devices",
            return_value=[self.info],
        )
        self.opener = self._patch(
            "k622rgb.calibrate.controller.open_device", return_value=-1
        )
        self.writer = self._patch(
            "k622rgb.calibrate.controller.write_feature", return_value=1032
        )
        self._patch("k622rgb.calibrate.os.close")

        self.outputs = []

    def _patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def output(self, text):
        self.outputs.append(text)

    def run_calibrate(self, answers, **kwargs):
        return calibrate.run(
            input_fn=scripted(answers), output=self.output, **kwargs
        )

    def saved_layout(self):
        return json.loads(self.layout_path.read_text(encoding="utf-8"))

    def write_layout(self, slots):
        self.layout_path.write_text(
            json.dumps({"version": 1, "slots": slots}), encoding="utf-8"
        )
        layout.clear_calibration_cache()

    def white_packet(self, slot):
        return controller.build_color_packet({slot: (255, 255, 255)})

    # -- discovery -------------------------------------------------------

    def test_records_answers_and_dead_slots(self):
        code = self.run_calibrate(["G1", "none", "quit"], start=102, end=104)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {"102": "G1", "103": ""})
        self.assertEqual(layout.resolve_key("G1"), 102)

    def test_skip_leaves_a_slot_uncalibrated(self):
        code = self.run_calibrate(["skip", "quit"], start=102, end=103)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {})

    def test_arbitrary_answer_is_recorded(self):
        code = self.run_calibrate(["Bogus", "quit"], start=102, end=102)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {"102": "Bogus"})
        self.assertEqual(layout.describe_value("Bogus"), "Bogus (unexpected)")

    def test_main_key_answer_is_recorded(self):
        code = self.run_calibrate(["escape", "quit"], start=102, end=102)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {"102": "Esc"})
        self.assertEqual(layout.describe_value("Esc"), "Esc (main key!)")

    def test_empty_label_reprompts_the_same_slot(self):
        code = self.run_calibrate([",", "G1", "quit"], start=102, end=102)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {"102": "G1"})
        self.assertTrue(any("empty key name" in line for line in self.outputs))

    def test_undo_goes_back_to_the_previous_slot(self):
        code = self.run_calibrate(
            ["G1", "undo", "G2", "quit"], start=102, end=103
        )
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {"102": "G2"})

    def test_empty_answer_keeps_an_existing_value(self):
        self.write_layout({"102": "G1"})
        code = self.run_calibrate(["", "quit"], start=102, end=102)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {"102": "G1"})

    def test_multi_key_answer_is_stored(self):
        code = self.run_calibrate(["G1,MR", "quit"], start=102, end=102)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.saved_layout()["slots"], {"102": "G1,MR"})
        self.assertEqual(layout.resolve_key("MR"), 102)

    def test_lights_only_the_target_slot(self):
        self.run_calibrate(["quit"], start=102, end=102)
        packet = self.writer.call_args_list[0].args[1]
        self.assertEqual(packet, self.white_packet(102))

    def test_interrupt_saves_progress_and_restores(self):
        def interrupt(_prompt=""):
            raise KeyboardInterrupt

        code = calibrate.run(
            start=102,
            end=102,
            input_fn=interrupt,
            output=self.output,
        )
        self.assertEqual(code, calibrate.EXIT_INTERRUPTED)
        self.assertTrue(self.layout_path.exists())
        self.assertTrue(any("interrupted" in line for line in self.outputs))

    def test_eof_ends_calibration_cleanly(self):
        code = self.run_calibrate([], start=102, end=102)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertTrue(self.layout_path.exists())

    def test_restores_the_previously_saved_frame(self):
        previous = controller.build_color_packet({0: (255, 0, 0)})
        state.save_frame(self.state_path, previous)
        self.run_calibrate(["quit"], start=102, end=102)
        self.assertEqual(self.writer.call_args_list[-1].args[1], previous)
        self.assertTrue(any("restored" in line for line in self.outputs))

    def test_leaves_the_board_off_without_a_saved_frame(self):
        self.run_calibrate(["quit"], start=102, end=102)
        self.assertEqual(
            self.writer.call_args_list[-1].args[1],
            controller.build_color_packet(),
        )

    def test_ignores_a_corrupt_saved_frame(self):
        self.state_path.write_bytes(b"garbage")
        code = self.run_calibrate(["quit"], start=102, end=102)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(
            self.writer.call_args_list[-1].args[1],
            controller.build_color_packet(),
        )

    def test_verbose_prints_the_device(self):
        self.run_calibrate(["quit"], start=102, end=102, verbose=True)
        self.assertTrue(any("device: %s" % self.node in line for line in self.outputs))

    def test_opens_the_device_for_writing(self):
        self.run_calibrate(["quit"], start=102, end=102)
        self.opener.assert_called_once_with(self.node, writable=True)

    def test_refuses_an_unknown_descriptor(self):
        self.descriptor.return_value = bytes(227)
        with self.assertRaises(controller.ProtocolError):
            self.run_calibrate(["quit"], start=102, end=102)
        self.opener.assert_not_called()
        self.writer.assert_not_called()

    # -- verification ----------------------------------------------------

    def test_verify_lights_each_calibrated_slot(self):
        self.write_layout({"102": "G1", "103": "", "104": "Prev"})
        code = self.run_calibrate([""], start=102, end=125, verify=True)
        self.assertEqual(code, calibrate.EXIT_OK)
        packets = [call.args[1] for call in self.writer.call_args_list]
        self.assertEqual(packets[0], self.white_packet(102))
        self.assertEqual(packets[1], self.white_packet(104))
        self.assertEqual(packets[2], controller.build_color_packet())

    def test_verify_without_calibration_lights_nothing(self):
        code = self.run_calibrate([], verify=True)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.assertEqual(self.writer.call_count, 1)
        self.assertEqual(
            self.writer.call_args.args[1], controller.build_color_packet()
        )
        self.assertTrue(any("nothing calibrated" in line for line in self.outputs))

    # -- dry run and validation -----------------------------------------

    def test_dry_run_touches_nothing(self):
        code = self.run_calibrate([], start=102, end=104, dry_run=True)
        self.assertEqual(code, calibrate.EXIT_OK)
        self.opener.assert_not_called()
        self.writer.assert_not_called()
        self.assertTrue(any("dry run" in line for line in self.outputs))
        self.assertFalse(self.layout_path.exists())

    def test_dry_run_lists_existing_calibration(self):
        self.write_layout({"102": "G1"})
        self.run_calibrate([], start=102, end=103, dry_run=True)
        joined = "\n".join(self.outputs)
        self.assertIn("slot 102: G1", joined)
        self.assertIn("slot 103: uncalibrated", joined)

    def test_invalid_range_is_rejected(self):
        for start, end in ((130, 140), (110, 105), (-1, 10), (100, 110)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    self.run_calibrate([], start=start, end=end)

    def test_parse_answer(self):
        self.assertEqual(calibrate.parse_answer("none"), "")
        self.assertEqual(calibrate.parse_answer("dead"), "")
        self.assertEqual(calibrate.parse_answer("g1"), "G1")
        self.assertEqual(calibrate.parse_answer("macro1"), "G1")
        self.assertEqual(calibrate.parse_answer("previous"), "Prev")
        self.assertEqual(calibrate.parse_answer("G1,MR"), "G1,MR")
        self.assertEqual(calibrate.parse_answer("G1,G1"), "G1")
        # Any other string is kept so a mistaken key can be reported.
        self.assertEqual(calibrate.parse_answer("esc"), "Esc")
        self.assertEqual(calibrate.parse_answer("escape"), "Esc")
        self.assertEqual(calibrate.parse_answer("A"), "A")
        self.assertEqual(calibrate.parse_answer("Bogus"), "Bogus")
        self.assertEqual(calibrate.parse_answer("esc,Bogus"), "Esc,Bogus")
        with self.assertRaises(ValueError):
            calibrate.parse_answer("")
        with self.assertRaises(ValueError):
            calibrate.parse_answer(",")


if __name__ == "__main__":
    unittest.main()
