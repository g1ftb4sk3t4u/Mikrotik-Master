"""What to look for on the MikroTik CDN: architectures, channels, and file templates.

MikroTik does not expose a browsable directory index on download.mikrotik.com /
cdn.mikrotik.com (both 403 on a bare directory GET), and per-device firmware is
shipped bundled inside the RouterOS install packages rather than as separate
per-model downloads. So "everything in the CDN" for a given version boils down
to: the combined package bundle, the core npk per architecture, CHR cloud
images, netinstall tooling, the ISO installer, and the changelog/readme.
"""

BASE_CDN_URL = "https://download.mikrotik.com/routeros"

# Major-branch "latest known" pointer files MikroTik publishes for the
# router-side auto-upgrade mechanism.
# https://upgrade.mikrotik.com/routeros/LATEST.<branch>  ->  "<version> <unix_ts>"
# These aren't guaranteed to track true "current stable" for every branch in
# real time (LATEST.7 has been observed lagging well behind the version the
# RSS feed and changelog page advertise as current) - treat them as one more
# free, exact, real version to add to the manifest, not as the authoritative
# "what's current" signal. The RSS feed (below) is more current for that.
CHANNELS = {
    "7": "7",
    "6": "6",
}

LATEST_POINTER_URL = "https://upgrade.mikrotik.com/routeros/LATEST.{channel_code}"
RSS_URL = "https://cdn.mikrotik.com/routeros/latest-stable-and-long-term.rss"
RSS_URL_FALLBACK = "https://mikrotik.com/download.rss"

ARCHITECTURES = [
    "arm",
    "arm64",
    "mipsbe",
    "mmips",
    "ppc",
    "smips",
    "tile",
    "x86",
]

# category -> filename template, arch requirement, and the major-version
# range it applies to. Every template here was verified live against the CDN
# (HEAD request, checked for 200) rather than assumed - MikroTik is not
# consistent about this: the core package's filename order flips between
# major branches (v6: "routeros-{arch}-{version}.npk", v7:
# "routeros-{version}-{arch}.npk" - arch and version swap places), CHR's
# .ova has no .zip suffix while its other formats do, and there's no
# separate README file at all (only CHANGELOG). Categories that were pure
# guesses and turned out not to exist (a "netinstall-6.*" per-version
# variant, a bare "chr-*.raw.zip", "README") were dropped rather than left
# in to 404 forever.
FILE_CATEGORIES = {
    "npk_legacy": {
        "template": "routeros-{arch}-{version}.npk",
        "needs_arch": True,
        "min_major": 0,
        "max_major": 6,
    },
    "npk": {
        "template": "routeros-{version}-{arch}.npk",
        "needs_arch": True,
        "min_major": 7,
        "max_major": None,
    },
    "all_packages": {
        "template": "all_packages-{arch}-{version}.zip",
        "needs_arch": True,
        "min_major": 0,
        "max_major": None,
    },
    "iso": {
        "template": "mikrotik-{version}.iso",
        "needs_arch": False,
        "min_major": 0,
        "max_major": None,
    },
    "netinstall": {
        "template": "netinstall-{version}.zip",
        "needs_arch": False,
        "min_major": 0,
        "max_major": None,
    },
    "chr_img": {
        "template": "chr-{version}.img.zip",
        "needs_arch": False,
        "min_major": 6,
        "max_major": None,
    },
    "chr_ova": {
        "template": "chr-{version}.ova",
        "needs_arch": False,
        "min_major": 6,
        "max_major": None,
    },
    "chr_vdi": {
        "template": "chr-{version}.vdi.zip",
        "needs_arch": False,
        "min_major": 6,
        "max_major": None,
    },
    "chr_vmdk": {
        "template": "chr-{version}.vmdk.zip",
        "needs_arch": False,
        "min_major": 6,
        "max_major": None,
    },
    "chr_vhdx": {
        "template": "chr-{version}.vhdx.zip",
        "needs_arch": False,
        "min_major": 6,
        "max_major": None,
    },
    "changelog": {
        "template": "CHANGELOG",
        "needs_arch": False,
        "min_major": 0,
        "max_major": None,
    },
}

DEFAULT_CATEGORIES = list(FILE_CATEGORIES.keys())

# Probe used to decide whether a version directory exists at all. CHANGELOG is
# present for every real release and small, so it's cheap and unambiguous
# (200 = exists, 404 = does not) - unlike HEAD on the bare version directory,
# which the CDN answers with 403 whether or not the version is real.
EXISTENCE_PROBE_FILENAME = "CHANGELOG"


def build_file_list(version: str, architectures=None, categories=None):
    """Return list of (category, arch_or_None, filename, url) for a version."""
    architectures = architectures or ARCHITECTURES
    categories = categories or DEFAULT_CATEGORIES
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        major = 0

    out = []
    for cat in categories:
        spec = FILE_CATEGORIES.get(cat)
        if not spec or major < spec["min_major"]:
            continue
        if spec["max_major"] is not None and major > spec["max_major"]:
            continue
        if spec["needs_arch"]:
            for arch in architectures:
                if cat == "npk" and arch == "x86":
                    # v7's version-first npk naming drops the arch suffix
                    # entirely for x86 specifically (routeros-7.16.npk, not
                    # routeros-7.16-x86.npk) - every other v7 architecture
                    # keeps it. Verified live; not a guess.
                    filename = f"routeros-{version}.npk"
                else:
                    filename = spec["template"].format(arch=arch, version=version)
                url = f"{BASE_CDN_URL}/{version}/{filename}"
                out.append((cat, arch, filename, url))
        else:
            filename = spec["template"].format(version=version)
            url = f"{BASE_CDN_URL}/{version}/{filename}"
            out.append((cat, None, filename, url))
    return out
