from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine.url import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

from storage import database_url


def backup_database(output_dir: str | Path | None = None) -> Path:
    url = database_url()
    parsed = make_url(url)
    destination_dir = Path(output_dir or PROJECT_ROOT / "backups")
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if parsed.drivername.startswith("sqlite"):
        source = Path(parsed.database or "")
        if not source.is_absolute():
            source = PROJECT_ROOT / source
        if not source.exists():
            raise FileNotFoundError(f"SQLite database does not exist: {source}")
        destination = destination_dir / f"{source.stem}-{stamp}{source.suffix or '.db'}"
        shutil.copy2(source, destination)
        return destination

    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError(f"Unsupported DATABASE_URL for backup: {parsed.render_as_string(hide_password=True)}")

    pg_url = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    destination = destination_dir / f"{parsed.database or 'postgres'}-{stamp}.dump"
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(destination), pg_url],
        check=True,
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a timestamped Omiryn database backup.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Backup directory. Defaults to ./backups.",
    )
    args = parser.parse_args()

    destination = backup_database(args.output_dir)
    print(f"Database backup written: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
