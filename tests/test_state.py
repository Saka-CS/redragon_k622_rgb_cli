import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from k622rgb import state


DUMP_FILES = {
    "config-response.bin": bytes((0x06,)) + bytes(261),
    "colors-response.bin": bytes((0x06,)) + bytes(1031),
    "custom1-response.bin": bytes((0x06,)) + bytes(1031),
    "custom2-response.bin": bytes((0x06,)) + bytes(1031),
    "profile-response.bin": bytes((0x06,)) + bytes(1031),
}


class BackupStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make_backup(self, files, meta, name="backup"):
        path = self.root / name
        path.mkdir()
        for filename, data in files.items():
            (path / filename).write_bytes(data)
        (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return path

    def test_files_manifest_has_hashes_for_all_dump_files(self):
        manifest = state.files_manifest(DUMP_FILES)
        self.assertEqual(list(manifest), sorted(DUMP_FILES))
        for name, data in DUMP_FILES.items():
            self.assertEqual(manifest[name]["size"], len(data))
            self.assertEqual(
                manifest[name]["sha256"], hashlib.sha256(data).hexdigest()
            )

    def test_manifest_round_trips_through_save_backup(self):
        with mock.patch.dict(
            os.environ, {state.STATE_DIR_ENV: str(self.root)}
        ):
            path = state.save_backup(
                DUMP_FILES,
                {
                    "kind": "config dump",
                    "descriptor_sha256": "abc123",
                },
            )
        meta, files = state.verify_backup_dir(
            path,
            required=tuple(DUMP_FILES),
            descriptor_sha256="abc123",
        )
        self.assertEqual(meta["version"], 2)
        self.assertEqual(meta["files"], state.files_manifest(DUMP_FILES))
        self.assertEqual(files, DUMP_FILES)

    def test_verify_rejects_size_mismatch(self):
        manifest = state.files_manifest({"config-response.bin": b"four"})
        path = self.make_backup(
            {"config-response.bin": b"four"},
            {"version": 2, "files": manifest},
        )
        (path / "config-response.bin").write_bytes(b"longer")

        with self.assertRaises(state.BackupError) as ctx:
            state.verify_backup_dir(path)
        self.assertIn("size mismatch", str(ctx.exception))
        self.assertIn("config-response.bin", str(ctx.exception))
        self.assertIn("4", str(ctx.exception))
        self.assertIn("6", str(ctx.exception))

    def test_verify_rejects_hash_mismatch(self):
        manifest = state.files_manifest({"config-response.bin": b"four"})
        path = self.make_backup(
            {"config-response.bin": b"four"},
            {"version": 2, "files": manifest},
        )
        (path / "config-response.bin").write_bytes(b"fouf")

        with self.assertRaises(state.BackupError) as ctx:
            state.verify_backup_dir(path)
        self.assertIn("sha256 mismatch", str(ctx.exception))
        self.assertIn("config-response.bin", str(ctx.exception))
        self.assertIn(manifest["config-response.bin"]["sha256"], str(ctx.exception))

    def test_verify_rejects_missing_required_file(self):
        files = {"config-response.bin": b"config"}
        path = self.make_backup(
            files,
            {"version": 2, "files": state.files_manifest(files)},
        )

        with self.assertRaises(state.BackupError) as ctx:
            state.verify_backup_dir(
                path,
                required=("config-response.bin", "colors-response.bin"),
            )
        self.assertIn("colors-response.bin", str(ctx.exception))
        self.assertIn("required", str(ctx.exception))

    def test_verify_rejects_listed_file_missing(self):
        manifest = state.files_manifest(
            {"config-response.bin": b"config", "colors-response.bin": b"colors"}
        )
        path = self.make_backup(
            {"config-response.bin": b"config"},
            {"version": 2, "files": manifest},
        )

        with self.assertRaises(state.BackupError) as ctx:
            state.verify_backup_dir(path)
        self.assertIn("colors-response.bin", str(ctx.exception))
        self.assertIn("missing", str(ctx.exception))

    def test_verify_rejects_descriptor_mismatch(self):
        files = {"config-response.bin": b"config"}
        path = self.make_backup(
            files,
            {
                "version": 2,
                "descriptor_sha256": "aaaa",
                "files": state.files_manifest(files),
            },
        )

        with self.assertRaises(state.BackupError) as ctx:
            state.verify_backup_dir(path, descriptor_sha256="bbbb")
        self.assertIn("descriptor", str(ctx.exception))
        self.assertIn("bbbb", str(ctx.exception))
        self.assertIn("aaaa", str(ctx.exception))

    def test_verify_marks_legacy_backup_unverified(self):
        files = {"config-response.bin": b"config"}
        path = self.make_backup(files, {"version": 1, "kind": "config dump"})

        meta, loaded = state.read_backup_dir(str(path))
        self.assertNotIn("files", meta)
        self.assertEqual(loaded, files)

        with self.assertRaises(state.UnverifiedBackup) as ctx:
            state.verify_backup_dir(path)
        self.assertEqual(str(ctx.exception), "unverified backup")
        self.assertIsInstance(ctx.exception, state.BackupError)


if __name__ == "__main__":
    unittest.main()
