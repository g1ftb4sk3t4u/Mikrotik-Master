"""Version discovery: cheap authoritative sources first, bounded brute force to fill gaps."""

import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import requests

from .catalog import (
    BASE_CDN_URL,
    CHANNELS,
    EXISTENCE_PROBE_FILENAME,
    LATEST_POINTER_URL,
    RSS_URL,
    RSS_URL_FALLBACK,
)

VERSION_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)?(?:(?:rc|beta)\d+)?)\b")
# Scoped to an actual "RouterOS <version>" title, not any number-dot-number
# in the document - a bare VERSION_RE run over raw RSS XML also matches the
# feed's own <?xml version="1.0"?> / <rss version="2.0"> metadata, and over
# an item's full text it can pick up incidental version mentions inside
# changelog prose (e.g. "fixed regression introduced in 7.20.8").
TITLE_VERSION_RE = re.compile(r"RouterOS\s+v?(\d+\.\d+(?:\.\d+)?(?:(?:rc|beta)\d+)?)", re.IGNORECASE)


def fetch_channel_pointers(session: requests.Session, timeout=10) -> set:
    """Query the official LATEST.<channel> pointer files. Cheap, exact, no guessing."""
    found = set()
    for _name, code in CHANNELS.items():
        try:
            r = session.get(LATEST_POINTER_URL.format(channel_code=code), timeout=timeout)
            if r.status_code == 200 and r.text.strip():
                version = r.text.strip().split()[0]
                if VERSION_RE.fullmatch(version):
                    found.add(version)
        except requests.RequestException:
            continue
    return found


def fetch_rss_versions(session: requests.Session, timeout=10) -> set:
    """Pull the small set of currently-advertised stable/long-term versions from the RSS feed.

    Parsed as XML and scoped to <title>/<link> per item - NOT a regex sweep
    over the raw feed text, which would also match the feed's own XML/RSS
    version metadata and any version-looking substrings inside changelog
    description text.
    """
    found = set()
    for url in (RSS_URL, RSS_URL_FALLBACK):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code != 200:
                continue
            found.update(_parse_rss_item_versions(r.text))
            if found:
                break
        except (requests.RequestException, ET.ParseError):
            continue
    return found


def _parse_rss_item_versions(xml_text: str) -> set:
    found = set()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return found

    for item in root.iter("item"):
        title_el = item.find("title")
        if title_el is not None and title_el.text:
            m = TITLE_VERSION_RE.search(title_el.text)
            if m:
                found.add(m.group(1))
                continue
        link_el = item.find("link")
        if link_el is not None and link_el.text:
            qs = parse_qs(urlparse(link_el.text).query)
            for v in qs.get("v", []):
                if VERSION_RE.fullmatch(v):
                    found.add(v)
    return found


def probe_version_exists(session: requests.Session, version: str, timeout=8) -> bool:
    """Single unambiguous existence check: CHANGELOG is present on every real release."""
    url = f"{BASE_CDN_URL}/{version}/{EXISTENCE_PROBE_FILENAME}"
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            return True
        if resp.status_code == 405:
            # Some edge nodes reject HEAD; fall back to a ranged GET.
            resp = session.get(url, timeout=timeout, headers={"Range": "bytes=0-0"})
            return resp.status_code in (200, 206)
        return False
    except requests.RequestException:
        return False


def generate_candidates(start_version: str, end_version: str, include_prerelease: bool = False):
    """Bounded major.minor.patch sweep.

    Unlike a naive generator that fans every patch out into 5 rc + 5 beta
    variants (221 candidates per minor version, almost all dead), this only
    adds pre-release suffixes when explicitly requested, and only for the
    single next-patch guess - pre-releases are for hunting the bleeding edge,
    not for the historical archive sweep.
    """
    start_major, start_minor = _split(start_version)
    end_major, end_minor = _split(end_version)

    versions = []
    for major in range(start_major, end_major + 1):
        min_minor = start_minor if major == start_major else 0
        max_minor = end_minor if major == end_major else 60
        for minor in range(min_minor, max_minor + 1):
            base = f"{major}.{minor}"
            versions.append(base)
            for patch in range(1, 26):
                versions.append(f"{base}.{patch}")
                if include_prerelease:
                    versions.append(f"{base}.{patch}rc1")
                    versions.append(f"{base}.{patch}beta1")
    return versions


def _split(version: str):
    parts = version.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return major, minor
