#!/usr/bin/env python3
"""Download the free DB-IP Lite city database used to estimate a user's location from their IP.

No account or key: DB-IP publishes one file a month. Tries this month, then last month (early in
a month the new file may not be out yet). Writes data/dbip-city-lite.mmdb (about 60 MB compressed).
Run at build time; the app works without it and simply skips the estimate.
IP geolocation by DB-IP (https://db-ip.com), CC BY 4.0.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = PROJECT_ROOT / "data" / "dbip-city-lite.mmdb"
URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"


def _months(today: date) -> list[str]:
    last_month = today.replace(day=1) - timedelta(days=1)
    return [today.strftime("%Y-%m"), last_month.strftime("%Y-%m")]


def download(target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    for month in _months(date.today()):
        try:
            with urllib.request.urlopen(URL.format(month=month), timeout=120) as response:
                with gzip.GzipFile(fileobj=response) as unzipped, partial.open("wb") as out:
                    shutil.copyfileobj(unzipped, out)
        except Exception as error:
            print(f"{month}: not available ({type(error).__name__}); trying an older month")
            continue
        partial.replace(target)
        return month
    partial.unlink(missing_ok=True)
    raise SystemExit("Could not download DB-IP Lite; location estimates stay off.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    month = download(args.target)
    print(f"Saved DB-IP Lite {month} to {args.target} ({args.target.stat().st_size // 1_000_000} MB).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
