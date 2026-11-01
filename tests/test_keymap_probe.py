import unittest

from tools import keymap_probe as probe


class SlotMathTests(unittest.TestCase):
    def test_known_examples(self):
        self.assertEqual(probe.packet_to_cfg(14), 84)
        self.assertEqual(probe.cfg_to_packet(84), 14)
        self.assertEqual(probe.cfg_to_packet(14), 44)
        self.assertEqual(probe.cfg_to_packet(5), 105)
        self.assertEqual(probe.cfg_to_packet(36), 6)
        self.assertEqual(probe.cfg_to_packet(7), 22)

    def test_round_trip(self):
        for slot in range(probe.NUM_SLOTS):
            with self.subTest(slot=slot):
                self.assertEqual(
                    probe.packet_to_cfg(probe.cfg_to_packet(slot)), slot
                )
                self.assertEqual(
                    probe.cfg_to_packet(probe.packet_to_cfg(slot)), slot
                )

    def test_expected_values(self):
        self.assertEqual(probe.expected_for(14), ("PrtSc", "main", 84))
        self.assertEqual(probe.expected_for(6), ("F5", "main", 36))
        self.assertEqual(probe.expected_for(105), ("LCtrl", "main", 5))
        self.assertEqual(probe.expected_for(17), (None, "extra", 102))
        self.assertEqual(probe.expected_for(1), (None, "dead", 6))
        self.assertEqual(probe.expected_for(77), ("LogoLeft", "zone", 87))
        self.assertEqual(probe.expected_for(78), ("LogoCenter", "zone", 93))
        self.assertEqual(probe.expected_for(79), ("LogoRight", "zone", 99))


class InputTests(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(probe.normalize_name("W"), "W")
        self.assertEqual(probe.normalize_name("w"), "W")
        self.assertEqual(probe.normalize_name("printscreen"), "PrtSc")
        self.assertEqual(probe.normalize_name("backspace"), "Bksp")
        self.assertEqual(probe.normalize_name("g1"), "G1")
        self.assertEqual(probe.normalize_name("logo1"), "LogoLeft")
        self.assertEqual(probe.normalize_name("logo-center"), "LogoCenter")
        self.assertEqual(probe.normalize_name("logoright"), "LogoRight")
        self.assertIsNone(probe.normalize_name("   "))

    def test_single_letter_answers_are_key_names(self):
        self.assertEqual(probe.classify_answer("n", "N"), ("record", "N"))
        self.assertEqual(probe.classify_answer("N", "W"), ("record", "N"))
        self.assertEqual(probe.classify_answer("s", "S"), ("record", "S"))
        self.assertEqual(probe.classify_answer("q", "Q"), ("record", "Q"))
        self.assertEqual(probe.classify_answer("-", "W"), ("record", "-"))

    def test_word_commands(self):
        self.assertEqual(probe.classify_answer("dead", "N"), ("record", None))
        self.assertEqual(probe.classify_answer("none", "N"), ("record", None))
        self.assertEqual(probe.classify_answer("blank", "N"), ("record", None))
        self.assertEqual(probe.classify_answer("skip", "S"), ("skip", None))
        self.assertEqual(probe.classify_answer("quit", "Q"), ("quit", None))
        self.assertEqual(probe.classify_answer("help", "W"), ("help", None))
        self.assertEqual(probe.classify_answer("?", "W"), ("help", None))

    def test_enter_accepts_expected(self):
        self.assertEqual(probe.classify_answer("", "W"), ("record", "W"))
        self.assertEqual(probe.classify_answer("   ", "W"), ("record", "W"))
        self.assertEqual(probe.classify_answer("", None), ("record", None))

    def test_parse_slots(self):
        self.assertEqual(probe.parse_slots("0-2,14,44"), [0, 1, 2, 14, 44])
        self.assertEqual(probe.parse_slots("0x7a"), [122])

    def test_parse_slots_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            probe.parse_slots("126")


class ConsolidateTests(unittest.TestCase):
    def synthetic_records(self):
        records = {}
        for slot in range(probe.NUM_SLOTS):
            expected, category, cfg = probe.expected_for(slot)
            if category in ("main", "zone"):
                observed = expected
                status = "ok"
            else:
                observed = None
                status = "dead"
            records[slot] = {
                "slot": slot,
                "cfg_slot": cfg,
                "category": category,
                "expected": expected,
                "observed": observed,
                "status": status,
            }
        return records

    def test_consolidate_transpose_mapping(self):
        document = probe.consolidate(
            self.synthetic_records(), True, "/dev/null", "deadbeef"
        )
        self.assertTrue(document["complete"])
        self.assertEqual(len(document["keys"]), 87)
        self.assertEqual(document["keys"]["W"], 44)
        self.assertEqual(document["keys"]["PrtSc"], 14)
        self.assertEqual(document["keys"]["LCtrl"], 105)
        self.assertEqual(document["keys"]["F5"], 6)
        self.assertEqual(document["mismatches"], [])
        self.assertEqual(len(document["dead_slots"]), 36)
        self.assertEqual(
            document["zones"],
            {"LogoLeft": 77, "LogoCenter": 78, "LogoRight": 79},
        )

    def test_consolidate_infers_swapped_unlit_key(self):
        records = self.synthetic_records()
        records[85] = {
            "slot": 85,
            "cfg_slot": 10,
            "category": "main",
            "expected": "Z",
            "observed": None,
            "status": "mismatch",
        }
        records[86] = {
            "slot": 86,
            "cfg_slot": 16,
            "category": "main",
            "expected": "X",
            "observed": "Z",
            "status": "mismatch",
        }
        document = probe.consolidate(records, True, "/dev/null", "deadbeef")
        self.assertEqual(document["keys"]["X"], 85)
        self.assertEqual(document["keys"]["Z"], 86)
        self.assertEqual(document["inferred_keys"], {"X": 85})
        self.assertEqual(document["unlit_keys"], ["X"])
        self.assertEqual(document["missing_keys"], [])
        self.assertEqual(document["mismatches"], [85, 86])

    def test_consolidate_normalizes_zone_text(self):
        records = self.synthetic_records()
        records[77]["observed"] = "left side of the logo"
        records[77]["status"] = "extra"
        document = probe.consolidate(records, True, "/dev/null", "deadbeef")
        self.assertEqual(document["zones"]["LogoLeft"], 77)
        self.assertEqual(document["slots"]["77"]["observed"], "LogoLeft")
        self.assertEqual(document["slots"]["77"]["category"], "zone")
        self.assertEqual(document["slots"]["77"]["status"], "ok")

    def test_consolidate_verified_record_overrides_expected(self):
        records = self.synthetic_records()
        records[85] = {
            "slot": 85,
            "cfg_slot": 10,
            "category": "dead",
            "expected": None,
            "observed": None,
            "status": "dead",
            "verified": True,
            "source": "verify",
        }
        records[86] = {
            "slot": 86,
            "cfg_slot": 10,
            "category": "main",
            "expected": "Z",
            "observed": "Z",
            "status": "ok",
            "verified": True,
            "source": "verify",
        }
        records[87] = {
            "slot": 87,
            "cfg_slot": 16,
            "category": "main",
            "expected": "X",
            "observed": "X",
            "status": "ok",
            "verified": True,
            "source": "verify",
        }
        records[88] = {
            "slot": 88,
            "cfg_slot": 22,
            "category": "main",
            "expected": "C",
            "observed": "C",
            "status": "ok",
            "verified": True,
            "source": "verify",
        }
        document = probe.consolidate(records, True, "/dev/null", "deadbeef")
        self.assertEqual(document["slots"]["87"]["expected"], "X")
        self.assertEqual(document["slots"]["87"]["verified"], True)
        self.assertEqual(document["keys"]["X"], 87)
        self.assertEqual(document["keys"]["C"], 88)

    def test_choose_primary_prefers_official_slot(self):
        self.assertEqual(probe.choose_primary("W", [80, 44]), 44)
        self.assertEqual(probe.choose_primary("G1", [17, 20]), 17)

    def test_render_module_is_valid_python(self):
        document = probe.consolidate(
            self.synthetic_records(), True, "/dev/null", "deadbeef"
        )
        text = probe.render_module(document)
        compile(text, "<keymap_data>", "exec")
        self.assertIn("SLOT_NAMES = {", text)
        self.assertIn("44: 'W'", text)
        self.assertIn("ZONE_NAMES = {", text)
        self.assertIn("77: 'LogoLeft'", text)
        self.assertIn("DEAD_SLOTS = frozenset((", text)
        self.assertIn("UNLIT_KEYS = ()", text)


if __name__ == "__main__":
    unittest.main()
