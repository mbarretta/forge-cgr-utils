"""APK repository definitions and APKINDEX fetching."""

from __future__ import annotations

import io
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    pass

CACHE_DIR = Path.home() / ".cache" / "apk-find"
CACHE_TTL_SECONDS = 3600  # 1 hour

ARCHITECTURES = ["x86_64", "aarch64"]


@dataclass(frozen=True)
class Repo:
    name: str
    description: str
    base_url: str
    requires_auth: bool = False


# Known Chainguard APK repositories.
# - wolfi and extras are publicly accessible.
# - chainguard requires a chainctl Bearer token (apk.cgr.dev uses registry auth).
REPOS: dict[str, Repo] = {
    "wolfi": Repo(
        name="wolfi",
        description="Wolfi OS packages",
        base_url="https://packages.wolfi.dev/os",
        requires_auth=False,
    ),
    "extras": Repo(
        name="extras",
        description="Chainguard extras packages",
        base_url="https://packages.cgr.dev/extras",
        requires_auth=False,
    ),
    "chainguard": Repo(
        name="chainguard",
        description="Chainguard hardened packages (requires auth)",
        base_url="https://apk.cgr.dev/chainguard",
        requires_auth=True,
    ),
}


@dataclass
class PackageEntry:
    name: str
    version: str
    arch: str
    description: str
    repo: str
    origin: str = ""
    url: str = ""
    license: str = ""


def _cache_path(repo_name: str, arch: str) -> Path:
    return CACHE_DIR / f"{repo_name}-{arch}.apkindex"


def _is_cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS


def _fetch_apkindex(repo: Repo, arch: str, auth_token: str = "") -> bytes:
    url = f"{repo.base_url}/{arch}/APKINDEX.tar.gz"
    headers = {}
    if repo.requires_auth and auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 401:
        raise PermissionError(
            f"Authentication required for {repo.name}. "
            "Run 'chainctl auth login' and ensure FORGE has auth configured."
        )
    resp.raise_for_status()
    return resp.content


def _extract_apkindex(data: bytes) -> str:
    """Extract the APKINDEX text from a .tar.gz blob."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        member = tf.getmember("APKINDEX")
        f = tf.extractfile(member)
        if f is None:
            raise ValueError("APKINDEX not found in archive")
        return f.read().decode("utf-8")


def load_apkindex(
    repo: Repo,
    arch: str,
    auth_token: str = "",
    force_refresh: bool = False,
) -> str:
    """Return the raw APKINDEX text for a repo/arch, using a disk cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(repo.name, arch)

    if not force_refresh and _is_cache_fresh(cache):
        return cache.read_text(encoding="utf-8")

    raw = _fetch_apkindex(repo, arch, auth_token)
    text = _extract_apkindex(raw)
    cache.write_text(text, encoding="utf-8")
    return text


def parse_apkindex(text: str, repo_name: str, arch: str) -> list[PackageEntry]:
    """Parse APKINDEX text into a list of PackageEntry objects."""
    entries: list[PackageEntry] = []
    current: dict[str, str] = {}

    for line in text.splitlines():
        if line == "":
            if "P" in current:
                entries.append(
                    PackageEntry(
                        name=current.get("P", ""),
                        version=current.get("V", ""),
                        arch=current.get("A", arch),
                        description=current.get("T", ""),
                        repo=repo_name,
                        origin=current.get("o", ""),
                        url=current.get("U", ""),
                        license=current.get("L", ""),
                    )
                )
            current = {}
        elif ":" in line:
            key, _, value = line.partition(":")
            if len(key) == 1:  # single-letter APKINDEX fields only
                current[key] = value

    # flush last entry if file doesn't end with blank line
    if "P" in current:
        entries.append(
            PackageEntry(
                name=current.get("P", ""),
                version=current.get("V", ""),
                arch=current.get("A", arch),
                description=current.get("T", ""),
                repo=repo_name,
                origin=current.get("o", ""),
                url=current.get("U", ""),
                license=current.get("L", ""),
            )
        )

    return entries
