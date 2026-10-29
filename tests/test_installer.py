"""Prove di regressione: niente apt, build o avvio di container reali."""

import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

INSTALLER_PATH = Path(__file__).resolve().parents[1] / "install.py"
if not INSTALLER_PATH.exists():
    INSTALLER_PATH = Path(__file__).with_name("install.py")
SPEC = importlib.util.spec_from_file_location("installer", INSTALLER_PATH)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_resume_requires_apply(self):
        with self.assertRaises(SystemExit):
            self.options("--resume")

    def test_resume_rejects_foreign_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "install-state.json"
            state.write_text(json.dumps({"nomad_revision": "foreign"}))
            state.chmod(0o600)
            with self.assertRaises(RuntimeError):
                installer.read_install_state(root)

    def test_wsl_override_preserves_foreign_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose.yml").write_text("services: {}")
            override = root / "nomad-wsl.override.json"
            override.write_text('{"custom": true}')
            with (
                patch.object(installer, "is_wsl", return_value=True),
                patch.object(installer, "run_command") as command,
            ):
                with self.assertRaises(RuntimeError):
                    installer.start_existing_nomad(root, root)
                command.assert_not_called()
            self.assertEqual(override.read_text(), '{"custom": true}')

    def test_wsl_override_uses_readonly_slave_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose.yml").write_text("services: {}")
            with (
                patch.object(installer, "is_wsl", return_value=True),
                patch.object(installer, "run_command"),
            ):
                installer.start_existing_nomad(root, root)
            config = json.loads((root / "nomad-wsl.override.json").read_text())
            volume = config["services"]["disk-collector"]["volumes"][0]
            self.assertTrue(volume["read_only"])
            self.assertEqual(volume["bind"]["propagation"], "rslave")

    def options(self, *arguments):
        with patch.object(sys, "argv", ["install.py", *arguments]):
            with contextlib.redirect_stderr(io.StringIO()):
                return installer.read_options()

    def test_invalid_arguments_are_cli_errors(self):
        for arguments in [
            ["--bind-ip", "not-an-ip"],
            ["--bind-ip", "0.0.0.0"],
            ["--bind-ip", "8.8.8.8"],
            ["--bind-ip", "224.0.0.1"],
            ["--port", "8080"],
            ["--port", "80"],
            ["--uid", "0"],
            ["--geointel-root", "relative/path"],
            ["--geointel-root", "/srv/nomad/../other"],
        ]:
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as error:
                    self.options(*arguments)
                self.assertEqual(error.exception.code, 2)

    def test_symlink_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "linked"
            path.symlink_to(Path(directory), target_is_directory=True)
            with self.assertRaises(SystemExit):
                self.options("--geointel-root", str(path))

    def test_plan_does_not_install_or_create_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "geointel"
            with (
                patch.object(
                    sys, "argv", ["install.py", "--geointel-root", str(target)]
                ),
                patch.object(installer, "prepare_docker") as docker,
            ):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(installer.main(), 0)
            self.assertEqual(
                json.loads(output.getvalue())["mode"], "PLAN ONLY"
            )
            self.assertFalse(target.exists())
            docker.assert_not_called()

    def test_root_check_prevents_commands(self):
        parser, options, root, ip = self.options("--apply")
        with patch.object(installer.os, "geteuid", return_value=1000):
            with patch.object(installer, "run_command") as command:
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        installer.check_system(parser, options, root, ip)
                command.assert_not_called()

    def test_failed_nomad_install_never_starts_geointel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "new-install"
            arguments = [
                "install.py",
                "--apply",
                "--accept-nomad-terms",
                "--geointel-root",
                str(root),
            ]
            with patch.object(sys, "argv", arguments):
                with patch.object(
                    installer,
                    "check_system",
                    return_value=Path(directory) / "nomad",
                ):
                    with patch.object(installer, "prepare_docker"):
                        with patch.object(
                            installer,
                            "install_nomad",
                            side_effect=RuntimeError("test"),
                        ):
                            with patch.object(
                                installer, "install_geointel"
                            ) as geo:
                                with contextlib.redirect_stdout(io.StringIO()):
                                    with self.assertRaises(RuntimeError):
                                        installer.main()
                                geo.assert_not_called()
            self.assertTrue(root.exists())
            self.assertTrue((root / "install-state.json").exists())

    def test_build_failure_never_runs_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, options, _, ip = self.options("--skip-nomad")
            calls = []

            def command(arguments, **kwargs):
                calls.append(arguments)
                if arguments[-1] == "build":
                    raise subprocess.CalledProcessError(1, arguments)

            with patch.object(installer, "run_command", side_effect=command):
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install_geointel(
                        options, root, ip, lambda _: None
                    )
            self.assertFalse(any(call[-2:] == ["up", "-d"] for call in calls))
            self.assertTrue((root / "compose.json").exists())

    def test_nomad_receives_only_two_consented_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nomad = root / "nomad"
            nomad.mkdir()
            (nomad / "compose.yml").write_text("services: {}")
            script = b"#!/bin/bash\nexit 0\n"

            def download(url, target):
                target.write_bytes(script)
                return hashlib.sha256(script).hexdigest()

            with patch.object(
                installer, "download_file", side_effect=download
            ):
                with patch.object(installer, "run_command") as command:
                    installer.install_nomad(root, nomad, {}, lambda _: None)
            self.assertEqual(command.call_args.kwargs["input"], "y\ny\n")
            self.assertEqual(
                command.call_args.kwargs["stdout"], subprocess.DEVNULL
            )

    def test_downloads_and_health_use_real_local_http(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/large":
                    body = b"x" * (16 * 1024 * 1024 + 1)
                else:
                    body = b"fixture"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "download"
                url = f"http://127.0.0.1:{server.server_port}"
                digest = installer.download_file(url, target)
                self.assertEqual(
                    digest, hashlib.sha256(b"fixture").hexdigest()
                )
                with self.assertRaises(RuntimeError):
                    installer.download_file(url + "/large", target)
                self.assertEqual(target.read_bytes(), b"fixture")
                _, options, _, ip = self.options(
                    "--skip-nomad", "--port", str(server.server_port)
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        installer.verify_services(
                            options, Path(directory), ip
                        ),
                        0,
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
