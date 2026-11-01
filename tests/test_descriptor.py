import unittest
from pathlib import Path

from k622rgb import controller

FIXTURE = Path(__file__).parent / "data" / "k622-if1-descriptor.bin"


def fixture_bytes():
    return FIXTURE.read_bytes()


def build_feature_descriptor(report_id, count, size=8):
    """Minimal vendor report descriptor with one feature report."""
    return bytes(
        (
            0x06, 0x00, 0xFF,  # Usage Page (vendor)
            0x09, 0x01,        # Usage
            0xA1, 0x01,        # Collection (application)
            0x85, report_id,   # Report ID
            0x95, count,       # Report Count
            0x75, size,        # Report Size
            0xB1, 0x02,        # Feature (data, variable, absolute)
            0xC0,              # End Collection
        )
    )


class DescriptorFixtureTests(unittest.TestCase):
    def test_fixture_is_the_captured_k622_descriptor(self):
        data = fixture_bytes()
        self.assertEqual(len(data), 227)
        self.assertEqual(controller.K622_DESCRIPTOR_SIZE, 227)
        self.assertEqual(controller.descriptor_sha256(data),
                         controller.K622_DESCRIPTOR_SHA256)
        self.assertTrue(controller.is_known_descriptor(data))

    def test_unknown_descriptor_is_not_accepted(self):
        self.assertFalse(controller.is_known_descriptor(bytes(227)))
        self.assertFalse(controller.is_known_descriptor(b""))


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.reports = controller.parse_report_descriptor(fixture_bytes())

    def test_declares_exactly_the_k622_reports(self):
        self.assertEqual(
            self.reports,
            [
                controller.ReportInfo(1, "input", 1),
                controller.ReportInfo(2, "input", 2),
                controller.ReportInfo(3, "input", 3),
                controller.ReportInfo(4, "input", 15),
                controller.ReportInfo(5, "feature", 5),
                controller.ReportInfo(6, "feature", 1031),
                controller.ReportInfo(7, "input", 7),
            ],
        )

    def test_no_output_reports(self):
        self.assertFalse([r for r in self.reports if r.kind == "output"])

    def test_no_report_eight(self):
        self.assertFalse([r for r in self.reports if r.report_id == 0x08])

    def test_report_six_is_not_1796_bytes(self):
        report = controller.find_feature_report(self.reports, 0x06)
        self.assertEqual(report.size, 1031)

    def test_only_two_feature_reports(self):
        features = [r.report_id for r in self.reports if r.kind == "feature"]
        self.assertEqual(features, [0x05, 0x06])

    def test_accepts_bytearray_and_memoryview(self):
        data = fixture_bytes()
        self.assertEqual(
            controller.parse_report_descriptor(bytearray(data)), self.reports
        )
        self.assertEqual(
            controller.parse_report_descriptor(memoryview(data)), self.reports
        )

    def test_rejects_non_bytes(self):
        with self.assertRaises(TypeError):
            controller.parse_report_descriptor("06 01 00")

    def test_truncated_descriptor_raises(self):
        with self.assertRaises(ValueError):
            controller.parse_report_descriptor(b"\x06\x01")

    def test_accumulates_multiple_main_items_for_one_report(self):
        # Report 1 in the real descriptor is 3 bits + 5 bits = 1 byte.
        data = bytes(
            (
                0x85, 0x01,
                0x75, 0x03,
                0x95, 0x01,
                0x81, 0x02,
                0x75, 0x05,
                0x95, 0x01,
                0x81, 0x01,
            )
        )
        self.assertEqual(
            controller.parse_report_descriptor(data),
            [controller.ReportInfo(1, "input", 1)],
        )

    def test_skips_long_items(self):
        data = bytes((0xFE, 0x02, 0x01, 0xAA, 0xBB)) + build_feature_descriptor(
            0x05, 5
        )
        self.assertEqual(
            controller.parse_report_descriptor(data),
            [controller.ReportInfo(5, "feature", 5)],
        )

    def test_truncated_long_item_raises(self):
        with self.assertRaises(ValueError):
            controller.parse_report_descriptor(bytes((0xFE, 0x05, 0x01, 0x00)))


class FeatureReportTests(unittest.TestCase):
    def setUp(self):
        self.reports = controller.parse_report_descriptor(fixture_bytes())

    def test_allowlist_sizes(self):
        self.assertEqual(controller.ALLOWED_FEATURE_REPORTS, {0x05: 5, 0x06: 1031})

    def test_feature_report_size_for_declared_reports(self):
        self.assertEqual(controller.feature_report_size(self.reports, 0x05), 5)
        self.assertEqual(controller.feature_report_size(self.reports, 0x06), 1031)

    def test_refuses_report_not_in_allowlist(self):
        with self.assertRaises(controller.ProtocolError) as ctx:
            controller.feature_report_size(self.reports, 0x08)
        self.assertIn("allowlist", str(ctx.exception))
        self.assertIn("0x08", str(ctx.exception))

    def test_refuses_input_report(self):
        with self.assertRaises(controller.ProtocolError) as ctx:
            controller.feature_report_size(self.reports, 0x01)
        self.assertIn("allowlist", str(ctx.exception))

    def test_refuses_declared_size_mismatch(self):
        reports = controller.parse_report_descriptor(
            build_feature_descriptor(0x06, 5)
        )
        with self.assertRaises(controller.ProtocolError) as ctx:
            controller.feature_report_size(reports, 0x06)
        self.assertIn("5 bytes", str(ctx.exception))
        self.assertIn("1031", str(ctx.exception))

    def test_find_feature_report_errors_for_missing_report(self):
        with self.assertRaises(controller.ProtocolError):
            controller.find_feature_report(self.reports, 0x08)


if __name__ == "__main__":
    unittest.main()
