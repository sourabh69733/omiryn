"""Approximate location from the request's IP address, using the free DB-IP Lite database.

The data file (IP_LOCATION_DB_PATH, default data/dbip-city-lite.mmdb) is downloaded by
scripts/download_ip_location_db.py at build time; lookups are local, so no outside service sees
users' IPs. Country is reliable, state usually right, city often the network's hub city, so the
result is always stored as approximate. Any failure returns None: signup never depends on it.
IP geolocation by DB-IP (https://db-ip.com), CC BY 4.0.
"""

from __future__ import annotations

import hashlib
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
    """The user's public IP: the first X-Forwarded-For entry (Cloud Run), else the peer.

    Local development has no public IP; IP_LOCATION_DEV_IP stands in for it there.
    """
    for candidate in [*(forwarded_for or "").split(","), peer_host or ""]:
        text = candidate.strip()
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if address.is_global:
            return text
    return os.getenv("IP_LOCATION_DEV_IP", "").strip() or None


def matches_timezone(place: dict[str, str] | None, timezone_name: str | None) -> bool:
    """False when the IP's country differs from the browser timezone's country.

    That mismatch almost always means a VPN or relay (Cloudflare WARP, a corporate VPN), whose
    exit address says nothing about where the user is. Unknown data never counts as a mismatch.
    """
    if not place or not place.get("country_code"):
        return True
    timezone_country = country_for_timezone(timezone_name)
    return timezone_country is None or timezone_country == place["country_code"]


def country_for_timezone(timezone_name: str | None) -> str | None:
    """ISO country code of an IANA timezone, from the system tz database's zone.tab.

    Old names browsers still report ("Asia/Calcutta") are not in zone.tab; they are matched by
    their timezone file, which is the same file as the current name's.
    """
    name = (timezone_name or "").strip()
    if not name:
        return None
    by_name, by_content = _zone_countries()
    if name in by_name:
        return by_name[name]
    content = _zone_file_hash(name)
    return by_content.get(content) if content else None


@cache
def _zone_countries() -> tuple[dict[str, str], dict[str, str]]:
    by_name: dict[str, str] = {}
    for root in _tz_roots():
        table = root / "zone.tab"
        if not table.is_file():
            continue
        for line in table.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and not line.startswith("#"):
                by_name[parts[2]] = parts[0]
        break
    by_content = {}
    for zone, country in by_name.items():
        content = _zone_file_hash(zone)
        if content:
            by_content.setdefault(content, country)
    return by_name, by_content


def _zone_file_hash(name: str) -> str | None:
    if ".." in name or name.startswith("/"):
        return None
    for root in _tz_roots():
        path = root / name
        if path.is_file():
            return hashlib.sha1(path.read_bytes()).hexdigest()
    return None


def _tz_roots() -> list[Path]:
    import zoneinfo

    return [Path(root) for root in zoneinfo.TZPATH if Path(root).is_dir()]


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


__all__ = ["client_ip", "country_for_timezone", "locate_ip", "matches_timezone"]
