"""Private local snapshots and a strictly synthetic PostgreSQL restore drill.

No credentials are read by this process or printed. Docker Compose reads its
existing configuration; PostgreSQL tools use the isolated db container's local
socket. Real restoration is deliberately not exposed as a command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUPS = ROOT.parent / "coordination/flintplate-implementation-2026-09-12/backups"
ARTIFACTS = frozenset({"database.dump", "uploads.tar.gz"})


class OpsError(RuntimeError):
    """Only fixed, non-sensitive descriptions belong in this exception."""


def outside_repo(path: Path, repo: Path = ROOT) -> Path:
    absolute = path.absolute()
    if any(part.is_symlink() for part in [absolute, *absolute.parents]):
        raise OpsError("Symlinks sind für Sicherungsziele nicht erlaubt.")
    resolved = absolute.resolve()
    if resolved == repo.resolve() or repo.resolve() in resolved.parents:
        raise OpsError("Sicherungen müssen außerhalb des Repositories liegen.")
    return resolved


def private_directory(path: Path, *, create: bool = True) -> Path:
    path = outside_repo(path)
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OpsError("Sicherungsziel gehört nicht dem ausführenden Benutzer.")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise OpsError("Bestehendes Sicherungsziel muss Dateimodus 0700 haben.")
    return path


def private_file(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return os.fdopen(descriptor, "wb")


def hash_file(path: Path) -> dict[str, str | int]:
    if path.is_symlink():
        raise OpsError("Sicherungsdatei darf kein Symlink sein.")
    info = path.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise OpsError("Sicherungsdatei muss privat und regulär sein (0600).")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "bytes": info.st_size}


class Docker:
    def __init__(self, compose: str = "compose.yaml") -> None:
        if compose not in {"compose.yaml", "compose.runtime.yaml"}:
            raise OpsError("Nur die isolierte FlintPlate-Compose-Datei ist erlaubt.")
        self.prefix = [
            "docker",
            "compose",
            "--project-name",
            "flintplate",
            "--env-file",
            str(ROOT / ".env.flintplate"),
            "-f",
            str(ROOT / compose),
        ]
        self.local_checked = False

    def require_local(self) -> None:
        if self.local_checked:
            return
        # A globally selected remote Docker context must never turn this local
        # tool into a remote backup or restore command.
        override = os.environ.get("DOCKER_HOST", "")
        if override and not override.startswith("unix://"):
            raise OpsError("Dieses Werkzeug unterstützt nur einen lokalen Docker-Socket.")
        try:
            result = subprocess.run(
                ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise OpsError("Lokaler Docker-Kontext konnte nicht geprüft werden.") from None
        if result.returncode or not result.stdout.decode().strip().startswith("unix://"):
            raise OpsError("Dieses Werkzeug unterstützt nur einen lokalen Docker-Socket.")
        self.local_checked = True

    def run(
        self,
        args: list[str],
        *,
        data: bytes | None = None,
        source: BinaryIO | None = None,
        destination: BinaryIO | None = None,
        timeout: int = 60,
    ) -> bytes:
        self.require_local()
        try:
            result = subprocess.run(
                [*self.prefix, *args],
                input=data,
                stdin=source,
                stdout=destination or subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=ROOT,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise OpsError("Lokaler Verwaltungsbefehl nicht erreichbar oder abgelaufen.") from None
        if result.returncode:
            # stderr can contain paths, SQL data or provider credentials. Keep
            # it private; do not interpolate the exception or subprocess args.
            raise OpsError("Lokaler Verwaltungsbefehl fehlgeschlagen; Details nicht ausgegeben.")
        return result.stdout or b""

    def database_command(self, database: str, command: str, options: list[str]) -> list[str]:
        if database not in {"flintplate", "flintplate_test"}:
            raise OpsError("Zugriff außerhalb der isolierten FlintPlate-Datenbanken abgelehnt.")
        if command not in {"psql", "pg_dump", "pg_restore"}:
            raise OpsError("Nicht freigegebenes Datenbankwerkzeug.")
        return [
            "exec",
            "-T",
            "db",
            "env",
            "-u",
            "PGPASSWORD",
            "-u",
            "PGOPTIONS",
            "-u",
            "PGSERVICE",
            command,
            "--no-password",
            "--host=/var/run/postgresql",
            "--username=flintplate",
            f"--dbname={database}",
            *options,
        ]

    def sql(self, database: str, statement: str) -> str:
        return (
            self.run(
                self.database_command(database, "psql", ["-X", "-qAt", "-v", "ON_ERROR_STOP=1"]),
                data=statement.encode(),
            )
            .decode()
            .strip()
        )

    def require_quiet(self) -> None:
        services = (
            self.run(["ps", "--all", "--status", "running", "--services"]).decode().splitlines()
        )
        if "api" in services or "migrate" in services or "db" not in services:
            raise OpsError("Sicherung benötigt laufende DB und gestoppte API/Migrationsjobs.")
        count = self.sql(
            "flintplate",
            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
            "AND backend_type='client backend' AND pid<>pg_backend_pid();",
        )
        if count != "0":
            raise OpsError("Weitere DB-Verbindungen verhindern das exklusive Sicherungsfenster.")

    def uploads(self, source: Path, destination: Path) -> None:
        # The administrative process gets this one read-only directory, never
        # API/owner credentials or the host backup destination. Streaming also
        # works when UID10001 owns private 0600/0700 uploads after the switch.
        if (
            not source.is_absolute()
            or ":" in str(source)
            or any(part.is_symlink() for part in [source, *source.parents])
        ):
            raise OpsError("Uploadquelle muss ein eindeutiges lokales Verzeichnis sein.")
        if not source.is_dir():
            raise OpsError("Uploadquelle ist kein Verzeichnis.")
        with private_file(destination) as output:
            Docker("compose.runtime.yaml").run(
                [
                    "--profile",
                    "tools",
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "--pull",
                    "never",
                    "--volume",
                    f"{source}:/source/uploads:ro",
                    "backup_uploads",
                ],
                destination=output,
                timeout=600,
            )
            output.flush()
            os.fsync(output.fileno())


def archive_uploads(source: Path, destination: Path) -> None:
    with private_file(destination) as output:
        write_upload_archive(source, output)
        output.flush()
        os.fsync(output.fileno())


def write_upload_archive(source: Path, output: BinaryIO) -> None:
    if source.is_symlink() or not source.is_dir():
        raise OpsError("Uploadverzeichnis fehlt oder ist ein Symlink.")

    def unreadable_directory(_error: OSError) -> None:
        # pathlib.rglob may silently skip permission errors. A backup must
        # fail instead of producing a valid-looking but incomplete archive.
        raise OpsError("Ein Uploadverzeichnis konnte nicht vollständig gelesen werden.") from None

    paths = [
        Path(directory) / name
        for directory, directories, files in os.walk(
            source, followlinks=False, onerror=unreadable_directory
        )
        for name in directories + files
    ]
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path in sorted(paths):
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
                raise OpsError("Uploads enthalten einen Symlink oder eine Spezialdatei.")
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise OpsError("Uploads enthalten einen nicht unterstützten Hardlink.")
            member = tarfile.TarInfo(path.relative_to(source).as_posix())
            member.mtime = int(info.st_mtime)
            member.mode = 0o700 if path.is_dir() else 0o600
            if stat.S_ISDIR(info.st_mode):
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
                continue
            member.size = info.st_size
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as content:
                before = os.fstat(content.fileno())
                if (before.st_ino, before.st_size) != (info.st_ino, info.st_size):
                    raise OpsError("Uploads wurden während der Sicherung verändert.")
                archive.addfile(member, content)
                after = os.fstat(content.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise OpsError("Uploads wurden während der Sicherung verändert.")


def archive_stdout() -> int:
    try:
        write_upload_archive(Path("/source/uploads"), sys.stdout.buffer)
    except (OpsError, OSError, ValueError, tarfile.TarError):
        print("Privater Upload-Archivstream fehlgeschlagen.", file=sys.stderr)
        return 1
    return 0


def validated_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    names: set[str] = set()
    for member in members:
        path = PurePosixPath(member.name)
        if (
            not member.name
            or path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.as_posix() != member.name.rstrip("/")
            or "\\" in member.name
            or member.name in names
            or not (member.isfile() or member.isdir())
        ):
            raise OpsError("Uploadarchiv enthält einen unsicheren Eintrag.")
        names.add(member.name)
    return members


def restore_synthetic_uploads(archive_path: Path, destination: Path) -> None:
    # Used only for the synthetic drill. Existing directories are never replaced.
    destination.mkdir(mode=0o700)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in validated_members(archive):
            target = destination / member.name
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                content = archive.extractfile(member)
                if content is None:
                    raise OpsError("Uploadarchiv ist unvollständig.")
                with content, private_file(target) as output:
                    shutil.copyfileobj(content, output)


def verify_snapshot(path: Path) -> dict[str, object]:
    path = private_directory(path, create=False)
    manifest_path = path / "manifest.json"
    hash_file(manifest_path)
    if manifest_path.stat().st_size > 65536:
        raise OpsError("Sicherungsmanifest ist ungültig.")
    manifest = json.loads(manifest_path.read_text())
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != 1
        or manifest.get("database") != "flintplate"
        or not isinstance(manifest.get("files"), dict)
        or set(manifest["files"]) != ARTIFACTS
        or not isinstance(manifest.get("revision"), list)
        or not manifest["revision"]
        or any(
            not isinstance(item, str) or not re.fullmatch(r"[a-zA-Z0-9_]{1,32}", item)
            for item in manifest["revision"]
        )
    ):
        raise OpsError("Sicherungsmanifest ist ungültig.")
    for name in ARTIFACTS:
        if hash_file(path / name) != manifest["files"][name]:
            raise OpsError("Hash oder Dateigröße der Sicherung stimmt nicht überein.")
    with (path / "database.dump").open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise OpsError("Datenbanksicherung hat kein PostgreSQL-Custom-Format.")
    with tarfile.open(path / "uploads.tar.gz", "r:gz") as archive:
        validated_members(archive)
    return {"verified": True, "revision": manifest.get("revision")}


def backup(docker: Docker, destination: Path) -> Path:
    destination = private_directory(destination)
    docker.require_quiet()
    revision = docker.sql(
        "flintplate", "SELECT version_num FROM alembic_version ORDER BY version_num;"
    )
    revisions = revision.splitlines()
    if not revisions or any(not re.fullmatch(r"[a-zA-Z0-9_]{1,32}", item) for item in revisions):
        raise OpsError("Migrationsstand konnte nicht sicher bestimmt werden.")
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    pending = destination / (name + ".partial")
    pending.mkdir(mode=0o700)
    try:
        with private_file(pending / "database.dump") as output:
            docker.run(
                docker.database_command(
                    "flintplate", "pg_dump", ["--format=custom", "--no-owner", "--no-privileges"]
                ),
                destination=output,
                timeout=600,
            )
            output.flush()
            os.fsync(output.fileno())
        docker.uploads(ROOT / "backend/uploads", pending / "uploads.tar.gz")
        docker.require_quiet()
        if (
            docker.sql(
                "flintplate", "SELECT version_num FROM alembic_version ORDER BY version_num;"
            )
            != revision
        ):
            raise OpsError("Migrationsstand hat sich während der Sicherung verändert.")
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database": "flintplate",
            "revision": revisions,
            "consistency": {
                "api_and_migration_jobs_stopped": True,
                "no_other_database_clients_before_and_after": True,
                "exclusive_maintenance_window_required": True,
            },
            "files": {name: hash_file(pending / name) for name in sorted(ARTIFACTS)},
        }
        with private_file(pending / "manifest.json") as output:
            output.write((json.dumps(manifest, indent=2) + "\n").encode())
            output.flush()
            os.fsync(output.fileno())
        verify_snapshot(pending)
        final = destination / name
        pending.rename(final)
        descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return final
    finally:
        if pending.exists():
            shutil.rmtree(pending)


def drop_probe(docker: Docker, schema: str, marker: str) -> None:
    if not re.fullmatch(r"restore_probe_[a-f0-9]{32}", schema) or marker != "flintplate:" + schema:
        raise OpsError("Nur das eigene synthetische Testschema darf entfernt werden.")
    docker.sql(
        "flintplate_test",
        f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='{schema}') THEN "
        f"IF (SELECT obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname='{schema}') "
        f"IS DISTINCT FROM '{marker}' THEN RAISE EXCEPTION 'Probe marker mismatch'; END IF; "
        f'DROP SCHEMA "{schema}" CASCADE; END IF; END $$;',
    )


def restore_test(docker: Docker, destination: Path) -> dict[str, object]:
    destination = private_directory(destination)
    schema = "restore_probe_" + uuid.uuid4().hex
    marker = "flintplate:" + schema
    # Database name is not a CLI option. No existing application schema or real
    # snapshot is ever passed to pg_restore by this command.
    if docker.sql("flintplate_test", "SELECT current_database();") != "flintplate_test":
        raise OpsError("Restoretest ausschließlich in flintplate_test erlaubt.")
    created = False
    with tempfile.TemporaryDirectory(prefix=".restore-probe-", dir=destination) as directory:
        local = Path(directory)
        try:
            docker.sql(
                "flintplate_test",
                f'BEGIN; CREATE SCHEMA "{schema}"; '
                f"COMMENT ON SCHEMA \"{schema}\" IS '{marker}'; "
                f'CREATE TABLE "{schema}".orders(id integer PRIMARY KEY, cents integer CHECK(cents>0), note text); '
                f'CREATE TABLE "{schema}".entries(id integer PRIMARY KEY, order_id integer REFERENCES "{schema}".orders(id)); '
                f"INSERT INTO \"{schema}\".orders VALUES(1,1005,'synthetisch ä'),(2,995,'nur Test'); "
                f'INSERT INTO "{schema}".entries VALUES(1,1),(2,2); '
                f'CREATE FUNCTION "{schema}".immutable() RETURNS trigger LANGUAGE plpgsql AS $$ '
                "BEGIN RAISE EXCEPTION 'immutable synthetic evidence' USING ERRCODE='PFP01'; END $$; "
                f'CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON "{schema}".entries '
                f'FOR EACH ROW EXECUTE FUNCTION "{schema}".immutable(); COMMIT;',
            )
            created = True
            dump = local / "synthetic.dump"
            with private_file(dump) as output:
                docker.run(
                    docker.database_command(
                        "flintplate_test",
                        "pg_dump",
                        ["--format=custom", "--no-owner", "--no-privileges", f"--schema={schema}"],
                    ),
                    destination=output,
                )
            drop_probe(docker, schema, marker)
            with dump.open("rb") as source:
                docker.run(
                    docker.database_command(
                        "flintplate_test",
                        "pg_restore",
                        [
                            "--no-owner",
                            "--no-privileges",
                            "--exit-on-error",
                            "--single-transaction",
                        ],
                    ),
                    source=source,
                )
            docker.sql(
                "flintplate_test",
                "DO $$ BEGIN "
                f'IF (SELECT count(*) FROM "{schema}".orders)<>2 '
                f'OR (SELECT sum(cents) FROM "{schema}".orders)<>2000 '
                f"OR (SELECT note FROM \"{schema}\".orders WHERE id=1)<>'synthetisch ä' "
                "THEN RAISE EXCEPTION 'Synthetic data mismatch'; END IF; "
                f'BEGIN UPDATE "{schema}".entries SET order_id=2 WHERE id=1; '
                "RAISE EXCEPTION 'Missing immutable trigger'; EXCEPTION WHEN SQLSTATE 'PFP01' THEN NULL; END; "
                f"BEGIN INSERT INTO \"{schema}\".orders VALUES(1,1,'duplicate'); "
                "RAISE EXCEPTION 'Missing unique constraint'; EXCEPTION WHEN unique_violation THEN NULL; END; "
                f'BEGIN INSERT INTO "{schema}".entries VALUES(3,999); '
                "RAISE EXCEPTION 'Missing foreign key'; EXCEPTION WHEN foreign_key_violation THEN NULL; END; END $$;",
            )
            uploads = local / "synthetic-uploads"
            uploads.mkdir(mode=0o700)
            with private_file(uploads / "probe.txt") as output:
                output.write(b"FlintPlate synthetic upload\n")
            archive = local / "uploads.tar.gz"
            docker.uploads(uploads, archive)
            restored = local / "restored-uploads"
            restore_synthetic_uploads(archive, restored)
            if hash_file(uploads / "probe.txt") != hash_file(restored / "probe.txt"):
                raise OpsError("Synthetische Upload-Wiederherstellung stimmt nicht überein.")
            return {
                "restore_test": "passed",
                "checks": [
                    "rows",
                    "cents",
                    "unicode",
                    "immutable_trigger",
                    "unique_constraint",
                    "foreign_key",
                    "upload_hash",
                ],
            }
        finally:
            if created:
                drop_probe(docker, schema, marker)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def probe() -> dict[str, bool]:
    result: dict[str, bool] = {}
    opener = build_opener(ProxyHandler({}), NoRedirect)
    for endpoint, expected in (("health", "ok"), ("ready", "ready")):
        try:
            request = Request(
                f"http://127.0.0.1:8012/{endpoint}", headers={"Cache-Control": "no-cache"}
            )
            with opener.open(request, timeout=4) as response:
                payload = json.loads(response.read(4096))
                result[endpoint] = response.status == 200 and payload.get("status") == expected
        except (OSError, HTTPError, URLError, ValueError, AttributeError):
            result[endpoint] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose", choices=["compose.yaml", "compose.runtime.yaml"], default="compose.yaml"
    )
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUPS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="DB+Uploads im exklusiven Wartungsfenster privat sichern")
    commands.add_parser(
        "restore-test", help="Nur ein synthetisches Schema in flintplate_test wiederherstellen"
    )
    commands.add_parser(
        "probe", help="Nur lokale Liveness/Readiness abfragen; keine Nachrichten senden"
    )
    verify = commands.add_parser("verify", help="Private Sicherung anhand ihres Manifests prüfen")
    verify.add_argument("path", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "probe":
            result = probe()
            print(json.dumps(result))
            return 0 if all(result.values()) else 1
        if args.command == "verify":
            print(json.dumps(verify_snapshot(args.path)))
        elif args.command == "backup":
            print(json.dumps({"backup": str(backup(Docker(args.compose), args.backup_root))}))
        else:
            print(json.dumps(restore_test(Docker(args.compose), args.backup_root)))
    except OpsError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, tarfile.TarError):
        print("Betriebsprüfung fehlgeschlagen; keine privaten Details ausgegeben.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
