"""Host-only checks. No environment files, Docker daemon or database are opened."""

from __future__ import annotations

import ast
import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class RuntimeConfigurationTests(unittest.TestCase):
    def test_canonical_compose_uses_verified_runtime_configuration(self) -> None:
        self.assertEqual(
            yaml.safe_load((ROOT / "compose.yaml").read_text()),
            yaml.safe_load((ROOT / "compose.runtime.yaml").read_text()),
        )

    def test_api_cannot_receive_owner_identity_or_modify_migration_source(self) -> None:
        compose = yaml.safe_load((ROOT / "compose.runtime.yaml").read_text())
        api = compose["services"]["api"]
        self.assertNotIn("env_file", api)
        self.assertTrue(api["read_only"])
        self.assertEqual(api["user"], "10001:10001")
        self.assertEqual(api["command"][0], "uvicorn")
        self.assertNotIn("alembic", " ".join(api["command"]))
        self.assertIn("flintplate_runtime:", api["environment"]["DATABASE_URL"])
        self.assertNotIn("FLINTPLATE_DB_PASSWORD", str(api))
        self.assertEqual(
            api["volumes"],
            ["./backend/app:/app/app:ro", "./backend/uploads:/app/uploads"],
        )
        self.assertIn("ALL", api["cap_drop"])
        self.assertIn("/ready", api["healthcheck"]["test"][-1])
        self.assertEqual(api["healthcheck"]["timeout"], "5s")
        migration = compose["services"]["migrate"]
        self.assertEqual(migration["profiles"], ["tools"])
        self.assertIn("flintplate:", migration["environment"]["DATABASE_URL"])
        self.assertEqual(migration["command"], ["python", "-m", "tools.migrate"])

    def test_allowlist_covers_every_application_setting(self) -> None:
        compose = yaml.safe_load((ROOT / "compose.runtime.yaml").read_text())
        settings = ast.parse((ROOT / "backend/app/config.py").read_text())
        fields = {
            item.target.id.upper()
            for node in settings.body
            if isinstance(node, ast.ClassDef) and node.name == "Settings"
            for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        }
        self.assertFalse(fields - compose["services"]["api"]["environment"].keys())

    def test_upload_archiver_has_read_access_without_network_or_credentials(self) -> None:
        compose = yaml.safe_load((ROOT / "compose.runtime.yaml").read_text())
        service = compose["services"]["backup_uploads"]
        self.assertEqual(service["profiles"], ["tools"])
        self.assertEqual(service["network_mode"], "none")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["cap_add"], ["DAC_READ_SEARCH"])
        self.assertNotIn("env_file", service)
        self.assertEqual(set(service["environment"]), {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE"})
        self.assertEqual(
            service["volumes"], ["./scripts/flintplate_ops.py:/tool/flintplate_ops.py:ro"]
        )

    def test_build_context_excludes_credentials_and_local_user_data(self) -> None:
        excluded = (ROOT / "backend/.dockerignore").read_text().splitlines()
        for required in (".env", ".env.*", ".local/", "uploads/", ".git/"):
            self.assertIn(required, excluded)

    def test_setup_extends_preserves_and_protects_existing_configuration(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "setup_local", ROOT / "scripts/setup-local.py"
        )
        assert spec is not None and spec.loader is not None
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config"
            original = "# existing local settings\nFLINTPLATE_DB_PASSWORD=existing-test-only\nAPP_ENV=development\n"
            target.write_text(original)
            setup.ensure_config(target)
            first = target.read_text()
            self.assertTrue(first.startswith(original))
            self.assertIn("FLINTPLATE_RUNTIME_DB_PASSWORD=", first)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            setup.ensure_config(target)
            self.assertEqual(target.read_text(), first)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
