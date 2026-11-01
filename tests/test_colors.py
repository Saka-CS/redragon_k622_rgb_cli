import unittest

from k622rgb.colors import ColorError, format_color, parse_color


class ParseColorTests(unittest.TestCase):
    def test_hex_with_and_without_hash(self):
        self.assertEqual(parse_color("#ff0000"), (255, 0, 0))
        self.assertEqual(parse_color("ff0000"), (255, 0, 0))
        self.assertEqual(parse_color("#00FF7f"), (0, 255, 127))

    def test_three_digit_hex_is_expanded(self):
        self.assertEqual(parse_color("#f00"), (255, 0, 0))
        self.assertEqual(parse_color("0f8"), (0, 255, 136))

    def test_comma_separated_channels(self):
        self.assertEqual(parse_color("1,2,3"), (1, 2, 3))
        self.assertEqual(parse_color(" 255 , 0 , 128 "), (255, 0, 128))

    def test_named_colors_are_case_insensitive(self):
        self.assertEqual(parse_color("red"), (255, 0, 0))
        self.assertEqual(parse_color("RED"), (255, 0, 0))
        self.assertEqual(parse_color("Off"), (0, 0, 0))
        self.assertEqual(parse_color("white"), (255, 255, 255))

    def test_invalid_colors_are_rejected(self):
        for text in ("", "   ", "#", "#f", "#ff", "#ffff", "#fffff",
                     "#gggggg", "1,2", "1,2,3,4", "256,0,0", "-1,0,0",
                     "1.5,0,0", "notacolor"):
            with self.subTest(text=text):
                with self.assertRaises(ColorError):
                    parse_color(text)

    def test_non_string_is_rejected(self):
        for value in (None, 1, (255, 0, 0)):
            with self.subTest(value=value):
                with self.assertRaises(ColorError):
                    parse_color(value)  # type: ignore[arg-type]


class FormatColorTests(unittest.TestCase):
    def test_formats_lower_case_hex(self):
        self.assertEqual(format_color((255, 0, 0)), "#ff0000")
        self.assertEqual(format_color((0, 255, 127)), "#00ff7f")
        self.assertEqual(format_color((0, 0, 0)), "#000000")

    def test_round_trip(self):
        for color in ((0, 0, 0), (255, 255, 255), (1, 2, 3), (16, 32, 48)):
            with self.subTest(color=color):
                self.assertEqual(parse_color(format_color(color)), color)


if __name__ == "__main__":
    unittest.main()
