import json
import unittest
from pathlib import Path

from k622rgb import keymap_data


ROOT = Path(__file__).resolve().parents[1]
OBSERVED = ROOT / "docs" / "keymap-observed.json"


class KeymapDataTests(unittest.TestCase):
    def setUp(self):
        with OBSERVED.open("r", encoding="utf-8") as handle:
            self.mapping = json.load(handle)

    def test_slot_names_match_observed_json(self):
        expected = {
            int(slot): name for name, slot in self.mapping["keys"].items()
        }
        self.assertEqual(keymap_data.SLOT_NAMES, expected)

    def test_zone_names_match_observed_json(self):
        expected = {
            int(slot): name for name, slot in self.mapping["zones"].items()
        }
        self.assertEqual(keymap_data.ZONE_NAMES, expected)

    def test_alias_and_dead_slots_match_observed_json(self):
        slot_names = set(keymap_data.SLOT_NAMES)
        zone_names = set(keymap_data.ZONE_NAMES)
        expected_aliases = {}
        expected_dead = set()
        for slot_text, record in self.mapping["slots"].items():
            slot = int(slot_text)
            observed = record.get("observed")
            if observed is None:
                if slot not in slot_names and slot not in zone_names:
                    expected_dead.add(slot)
            elif slot not in slot_names and slot not in zone_names:
                expected_aliases[slot] = observed
        self.assertEqual(keymap_data.ALIAS_SLOTS, expected_aliases)
        self.assertEqual(keymap_data.DEAD_SLOTS, frozenset(expected_dead))

    def test_unlit_keys_match_observed_json(self):
        self.assertEqual(
            keymap_data.UNLIT_KEYS,
            tuple(self.mapping.get("unlit_keys", [])),
        )

    def test_every_packet_slot_is_accounted_for(self):
        groups = [
            set(keymap_data.SLOT_NAMES),
            set(keymap_data.ZONE_NAMES),
            set(keymap_data.ALIAS_SLOTS),
            set(keymap_data.DEAD_SLOTS),
        ]
        self.assertEqual(set().union(*groups), set(range(126)))
        for index, left in enumerate(groups):
            for right in groups[index + 1 :]:
                self.assertFalse(left & right)


if __name__ == "__main__":
    unittest.main()
