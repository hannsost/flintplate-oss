"""Host safety checks using synthetic files and a fake Docker process only."""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flintplate_ops as ops  # noqa: E402


class FakeDocker(ops.Docker):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[list[str]] = []
        self.statements: list[tuple[str, str]] = []
        self.quiet_checks = 0
        self.allow_backup = True

    def require_quiet(self) -> None:
        self.quiet_checks += 1
        if not self.allow_backup:
            raise ops.OpsError("Test: API läuft.")

    def sql(self, database: str, statement: str) -> str:
        self.statements.append((database, statement))
        if "current_database()" in statement:
            return database
        if "version_num" in statement:
            return "076"
        return ""

    def uploads(self, source: Path, destination: Path) -> None:
        ops.archive_uploads(source, destination)

    def run(self, args: list[str], **kwargs: object) -> bytes:
        self.commands.append(args)
        destination = kwargs.get("destination")
        if destination is not None:
            destination.write(b"PGDMPsynthetic-file")  # type: ignore[attr-defined]
        return b""


class OpsSafetyTests(unittest.TestCase):
    def test_backup_destination_cannot_be_inside_repo_or_follow_symlinks(self) -> None:
        with self.assertRaises(ops.OpsError):
            ops.outside_repo(ops.ROOT / ".local/backup")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            linked = root / "linked"
            linked.symlink_to(ops.ROOT, target_is_directory=True)
            with self.assertRaises(ops.OpsError):
                ops.outside_repo(linked / "new")
            public = root / "public"
            public.mkdir(mode=0o755)
            with self.assertRaises(ops.OpsError):
                ops.private_directory(public)
            self.assertEqual(stat.S_IMODE(public.stat().st_mode), 0o755)

    def test_private_upload_roundtrip_and_link_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "uploads"
            source.mkdir(mode=0o700)
            with ops.private_file(source / "übung.txt") as output:
                output.write(b"only synthetic bytes")
            archive = root / "uploads.tar.gz"
            ops.archive_uploads(source, archive)
            ops.restore_synthetic_uploads(archive, root / "restored")
            self.assertEqual(
                ops.hash_file(source / "übung.txt"), ops.hash_file(root / "restored/übung.txt")
            )
            (source / "link").symlink_to(source / "übung.txt")
            with self.assertRaises(ops.OpsError):
                ops.archive_uploads(source, root / "rejected.tar.gz")

    def test_extraction_rejects_traversal_and_symlink_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, name in enumerate(("../escaped", "/absolute", "a//b", "link")):
                archive_path = root / f"bad-{index}.tar.gz"
                with tarfile.open(archive_path, "w:gz") as archive:
                    member = tarfile.TarInfo(name)
                    if name == "link":
                        member.type = tarfile.SYMTYPE
                        member.linkname = "../escaped"
                    else:
                        member.size = 4
                    archive.addfile(member, io.BytesIO(b"test"))
                with self.assertRaises(ops.OpsError):
                    ops.restore_synthetic_uploads(archive_path, root / f"target-{index}")
            self.assertFalse((root / "escaped").exists())

    def test_unreadable_upload_subdirectory_fails_instead_of_silently_omitting_files(self) -> None:
        def inaccessible(*args: object, **kwargs: object) -> list[object]:
            callback = kwargs["onerror"]
            callback(PermissionError("private-upload-name"))  # type: ignore[operator]
            return []

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(os, "walk", side_effect=inaccessible),
                self.assertRaises(ops.OpsError) as raised,
            ):
                ops.write_upload_archive(Path(directory), io.BytesIO())
            self.assertNotIn("private-upload-name", str(raised.exception))

    def test_backup_refuses_active_service_then_verifies_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "checkout"
            (repo / "backend/uploads").mkdir(parents=True)
            (repo / "backend/uploads/synthetic.txt").write_text("synthetic")
            docker = FakeDocker()
            docker.allow_backup = False
            with patch.object(ops, "ROOT", repo), self.assertRaises(ops.OpsError):
                ops.backup(docker, root / "snapshots")
            self.assertEqual(docker.commands, [])
            docker.allow_backup = True
            with patch.object(ops, "ROOT", repo):
                snapshot = ops.backup(docker, root / "snapshots")
            self.assertTrue(ops.verify_snapshot(snapshot)["verified"])
            self.assertEqual(docker.quiet_checks, 3)
            manifest = json.loads((snapshot / "manifest.json").read_text())
            self.assertEqual(set(manifest["files"]), ops.ARTIFACTS)
            self.assertEqual(manifest["revision"], ["076"])
            self.assertNotIn("synthetic.txt", (snapshot / "manifest.json").read_text())
            for name in [*ops.ARTIFACTS, "manifest.json"]:
                self.assertEqual(stat.S_IMODE((snapshot / name).stat().st_mode), 0o600)
            (snapshot / "database.dump").write_bytes(b"PGDMPtampered")
            with self.assertRaises(ops.OpsError):
                ops.verify_snapshot(snapshot)

    def test_restore_commands_are_exclusively_synthetic_test_schema(self) -> None:
        docker = FakeDocker()
        with tempfile.TemporaryDirectory() as directory:
            result = ops.restore_test(docker, Path(directory))
            self.assertEqual(result["restore_test"], "passed")
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertTrue(docker.statements)
        self.assertTrue(all(database == "flintplate_test" for database, _ in docker.statements))
        self.assertTrue(all("--dbname=flintplate_test" in command for command in docker.commands))
        drops = [sql for _, sql in docker.statements if "DROP SCHEMA" in sql]
        self.assertEqual(len(drops), 2)
        self.assertTrue(
            all("restore_probe_" in sql and "Probe marker mismatch" in sql for sql in drops)
        )
        self.assertFalse(
            any(
                "DROP DATABASE" in sql or "DROP SCHEMA public" in sql
                for _, sql in docker.statements
            )
        )
        with self.assertRaises(ops.OpsError):
            ops.drop_probe(docker, "public", "flintplate:public")
        with self.assertRaises(ops.OpsError):
            docker.database_command("hireos", "pg_restore", [])

    def test_remote_docker_and_subprocess_errors_never_expose_secrets(self) -> None:
        docker = ops.Docker()
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://remote.invalid:1234"}):
            with self.assertRaises(ops.OpsError) as raised:
                docker.run(["ps"])
            self.assertNotIn("remote.invalid", str(raised.exception))
        docker.local_checked = True
        result = subprocess.CompletedProcess(
            [], 1, stdout=b"private output", stderr=b"secret-db-password"
        )
        with patch.object(subprocess, "run", return_value=result):
            with self.assertRaises(ops.OpsError) as raised:
                docker.run(["ps"])
            self.assertNotIn("secret-db-password", str(raised.exception))
            self.assertNotIn("private output", str(raised.exception))

    def test_admin_archive_stream_receives_only_the_explicit_read_only_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "private-upload-source"
            source.mkdir(mode=0o700)
            destination = root / "stream.tar.gz"
            with patch.object(ops.Docker, "run", return_value=b"") as run:
                ops.Docker().uploads(source, destination)
            args = run.call_args.args[0]
            self.assertIn(f"{source}:/source/uploads:ro", args)
            self.assertIn("backup_uploads", args)
            self.assertIn("never", args)
            self.assertNotIn(str(destination), args)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
