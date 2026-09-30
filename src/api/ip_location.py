"""Approximate location from the request's IP address, using the free DB-IP Lite database.

The data file (IP_LOCATION_DB_PATH, default data/dbip-city-lite.mmdb) is downloaded by
scripts/download_ip_location_db.py at build time; lookups are local, so no outside service sees
users' IPs. Country is reliable, state usually right, city often the network's hub city, so the
result is always stored as approximate. Any failure returns None: signup never depends on it.
IP geolocation by DB-IP (https://db-ip.com), CC BY 4.0.
"""

from __future__ import annotations

import ipaddress
import re
import logging
import os
from functools import cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "dbip-city-lite.mmdb"


def client_ip(forwarded_for: str | None, peer_host: str | None) -> str | None:
    """The user's public IP: the first X-Forwarded-For entry (Cloud Run), else the peer."""
    for candidate in [*(forwarded_for or "").split(","), peer_host or ""]:
        text = candidate.strip()
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if address.is_global:
            return text
    return None


def locate_ip(ip: str | None) -> dict[str, str] | None:
    """{country, country_code, region, city} for a public IP, or None when unknown."""
    if not ip:
        return None
    reader = _reader()
    if reader is None:
        return None
    try:
        record: Any = reader.get(ip)
    except Exception as error:  # a bad address or a damaged file
        logger.warning("ip_location.lookup_failed error=%s", type(error).__name__)
        return None
    if not isinstance(record, dict):
        return None
    country = record.get("country") or {}
    subdivisions = record.get("subdivisions") or [{}]
    place = {
        "country": _name(country),
        "country_code": str(country.get("iso_code") or ""),
        "region": _name(subdivisions[0] if subdivisions else {}),
        # DB-IP adds a neighbourhood ("Navi Mumbai (Ghansoli)"); the city alone is plenty.
        "city": re.sub(r"\s*\(.*\)\s*$", "", _name(record.get("city") or {})),
    }
    return {key: value for key, value in place.items() if value} or None


@cache
def _reader() -> Any:
    path = Path(os.getenv("IP_LOCATION_DB_PATH", "").strip() or DEFAULT_DB_PATH)
    if not path.is_file():
        logger.info("ip_location.unavailable path=%s", path)
        return None
    try:
        import maxminddb

        return maxminddb.open_database(str(path))
    except Exception as error:
        logger.warning("ip_location.open_failed error=%s", type(error).__name__)
        return None


def _name(entry: Any) -> str:
    names = entry.get("names") if isinstance(entry, dict) else None
    return str((names or {}).get("en") or "").strip()


__all__ = ["client_ip", "locate_ip"]
