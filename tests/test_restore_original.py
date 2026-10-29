"""Prove di sicurezza del cambio al servizio originale, senza Docker reale."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "restore", Path(__file__).resolve().parents[1] / "restore_original.py"
)
restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore)


class RestoreTests(unittest.TestCase):
    def test_modified_source_is_rejected(self):
        with patch.object(
            restore.subprocess,
            "check_output",
            side_effect=[restore.REVISION + "\n", " M src/main.js\n"],
        ):
            with self.assertRaises(RuntimeError):
                restore.check_source()

    def test_build_failure_keeps_previous_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app-original"
            source.mkdir()
            old = root / "compose.yaml"
            old.write_text("name: nomad-geointel\nservices: {}\n")
            config = root / "compose.original.json"
            with (
                patch.object(restore, "ROOT", root),
                patch.object(restore, "SOURCE", source),
                patch.object(restore, "CONFIG", config),
                patch.object(restore, "check_source"),
                patch.object(restore, "run"),
                patch.object(restore, "compose") as compose,
            ):
                compose.side_effect = [
                    None,
                    subprocess.CalledProcessError(1, "build"),
                ]
                with self.assertRaises(subprocess.CalledProcessError):
                    restore.deploy()
            self.assertFalse(config.exists())
            self.assertTrue(old.exists())
            self.assertFalse(
                any(call.args[0] == "up" for call in compose.call_args_list)
            )

    def test_cleanup_refuses_other_container_source(self):
        with (
            patch.object(restore, "check_source"),
            patch.object(restore, "healthy"),
            patch.object(
                restore.subprocess, "check_output", return_value="[]"
            ),
            patch.object(restore.shutil, "rmtree") as remove,
        ):
            with self.assertRaises(RuntimeError):
                restore.cleanup()
            remove.assert_not_called()

    def test_cleanup_preserves_original_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app-original"
            source.mkdir()
            (root / "app").mkdir()
            keep = root / "unrelated.txt"
            keep.write_text("keep")
            mounts = json.dumps(
                [{"Source": str(source), "Destination": "/app"}]
            )
            with (
                patch.object(restore, "ROOT", root),
                patch.object(restore, "SOURCE", source),
                patch.object(restore, "check_source"),
                patch.object(restore, "healthy"),
                patch.object(restore, "redirect_old_links"),
                patch.object(restore, "remove_legacy_voice"),
                patch.object(
                    restore.subprocess, "check_output", return_value=mounts
                ),
            ):
                restore.cleanup()
            self.assertFalse((root / "app").exists())
            self.assertTrue(source.is_dir())
            self.assertEqual(keep.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
