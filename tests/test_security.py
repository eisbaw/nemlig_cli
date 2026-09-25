"""Offline regression checks for password handling and Windows compatibility."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import warnings

import nemlig_cli as cli


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.addCleanup(self.output.close)

    def call_main(self, *args):
        with patch.object(sys, "argv", ["nemlig", *args]), \
                contextlib.redirect_stdout(self.output), \
                contextlib.redirect_stderr(self.output):
            return cli.main()

    def test_password_flags_rejected_without_echo_or_login(self):
        for args in (("-p", "synthetic-secret"), ("-psynthetic-secret",),
                     ("--password", "synthetic-secret"),
                     ("--password=synthetic-secret",),
                     ("--pass", "synthetic-secret"), ("--pass=synthetic-secret",)):
            with self.subTest(args=args), patch.object(cli, "login") as login:
                self.assertEqual(self.call_main(*args), 1)
                login.assert_not_called()
                self.assertNotIn("synthetic-secret", self.output.getvalue())

    def test_reject_password_file_without_printing_secret(self):
        with patch.object(cli, "CONFIG_FILE") as config:
            config.exists.return_value = True
            with patch("builtins.open", return_value=io.StringIO(json.dumps(
                    {"username": "user@example.com", "password": "synthetic-secret"}))):
                self.assertEqual(self.call_main("search", "milk"), 1)
        self.assertNotIn("synthetic-secret", self.output.getvalue())
        self.assertIn("Remove the password field", self.output.getvalue())

    def test_piped_password_is_never_read(self):
        with patch.object(sys.stdin, "isatty", return_value=False), \
                patch.object(cli.getpass, "getpass") as prompt:
            with self.assertRaisesRegex(ValueError, "interactive terminal"):
                cli.read_password()
            prompt.assert_not_called()

    def test_getpass_visible_fallback_is_blocked(self):
        def unsafe_fallback(*args):
            warnings.warn("cannot disable echo", cli.getpass.GetPassWarning)
            self.fail("must stop before visible fallback reads a password")

        with patch.object(sys.stdin, "isatty", return_value=True), \
                patch.object(cli.getpass, "getpass", side_effect=unsafe_fallback):
            with self.assertRaisesRegex(ValueError, "Hidden password entry"):
                cli.read_password()

    def test_hidden_password_and_empty_input(self):
        with patch.object(sys.stdin, "isatty", return_value=True), \
                patch.object(cli.getpass, "getpass", return_value="synthetic-secret"):
            self.assertEqual(cli.read_password(), "synthetic-secret")
        with patch.object(sys.stdin, "isatty", return_value=True), \
                patch.object(cli.getpass, "getpass", return_value=""):
            with self.assertRaisesRegex(ValueError, "empty"):
                cli.read_password()

    def test_search_uses_prompt_not_legacy_environment(self):
        with patch.dict(os.environ, {"NEMLIG_USER": "user@example.com",
                                    "NEMLIG_PASS": "unused-secret"}), \
                patch.object(cli, "load_config_credentials", return_value={}), \
                patch.object(cli, "read_password", return_value="synthetic-secret"), \
                patch.object(cli, "login", return_value=object()) as login, \
                patch.object(cli, "cmd_search", return_value=0) as search:
            self.assertEqual(self.call_main("search", "milk"), 0)
            login.assert_called_once_with("user@example.com", "synthetic-secret")
            search.assert_called_once()
        self.assertNotIn("synthetic-secret", self.output.getvalue())
        self.assertNotIn("unused-secret", self.output.getvalue())

    def test_http_error_does_not_print_body_or_url(self):
        response = cli.requests.Response()
        response.status_code = 401
        response._content = b'synthetic-private-body'
        error = cli.requests.HTTPError("synthetic-private-url", response=response)
        with patch.object(cli, "load_config_credentials", return_value={}), \
                patch.object(cli, "read_password", return_value="synthetic-secret"), \
                patch.object(cli, "login", side_effect=error):
            self.assertEqual(self.call_main("-u", "user@example.com", "search", "milk"), 1)
        self.assertIn("HTTP Error: 401", self.output.getvalue())
        self.assertNotIn("synthetic-private", self.output.getvalue())

    def test_cancel_does_not_login(self):
        with patch.object(cli, "load_config_credentials", return_value={}), \
                patch.object(cli, "read_password", side_effect=KeyboardInterrupt), \
                patch.object(cli, "login") as login:
            self.assertEqual(self.call_main("-u", "user@example.com", "search", "milk"), 1)
            login.assert_not_called()

    def test_interactive_mode_without_readline(self):
        with patch.object(cli, "readline", None), \
                patch("builtins.input", return_value="quit"), \
                contextlib.redirect_stdout(self.output):
            self.assertEqual(cli.interactive_mode(object(), "user@example.com"), 0)

    def test_local_list_does_not_prompt_or_authenticate(self):
        with patch.object(cli, "load_grocery_list", return_value={"budget": 500, "items": []}), \
                patch.object(cli, "read_password") as prompt, \
                patch.object(cli, "login") as login:
            self.assertEqual(self.call_main("list"), 0)
            prompt.assert_not_called()
            login.assert_not_called()

    def test_list_sync_preserves_ids_and_quantities(self):
        data = {"items": [{"product_id": "12345678", "name": "Test item", "quantity": 2}]}
        auth = object()
        with patch.object(cli, "load_grocery_list", return_value=data), \
                patch.object(cli, "add_to_basket") as add, \
                contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.output):
            self.assertEqual(cli.cmd_list_sync(auth, None), 0)
            add.assert_called_once_with(auth, "12345678", 2)

    def test_help_with_legacy_windows_output_encoding(self):
        result = subprocess.run(
            [sys.executable, str(Path(cli.__file__)), "--help"],
            env={**os.environ, "PYTHONIOENCODING": "cp1252:strict"},
            capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"search", result.stdout)

    def test_installed_module_uses_package_version(self):
        with patch.object(Path, "open", side_effect=FileNotFoundError), \
                patch.object(cli.metadata, "version", return_value="0.2.0.dev1"), \
                patch.object(cli.subprocess, "check_output") as git:
            self.assertEqual(cli.development_version(), "0.2.0.dev1+unknown")
            git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
