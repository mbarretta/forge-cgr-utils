"""APK package search logic."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from forge_cgr_utils.apk_find.repos import (
    ARCHITECTURES,
    REPOS,
    Repo,
    PackageEntry,
    load_apkindex,
    parse_apkindex,
)


class MatchType(str, Enum):
    EXACT = "exact"
    PARTIAL = "partial"  # name contains query or query contains name
    NEAR = "near"        # fuzzy / close match on name


@dataclass
class SearchResult:
    package: PackageEntry
    match_type: MatchType

    @property
    def sort_key(self) -> tuple:
        order = {MatchType.EXACT: 0, MatchType.PARTIAL: 1, MatchType.NEAR: 2}
        return (order[self.match_type], self.package.repo, self.package.name)


@dataclass
class SearchConfig:
    query: str
    repos: list[str]
    arch: str | None  # None = all arches
    auth_token: str = ""
    force_refresh: bool = False
    near_match_cutoff: float = 0.6
    on_progress: Callable[[float, str], None] = lambda f, m: None


def search(config: SearchConfig) -> list[SearchResult]:
    """Search APK repos and return ranked results (exact → partial → near)."""
    query = config.query.lower()
    results: list[SearchResult] = []
    seen: set[tuple[str, str, str]] = set()  # (repo, name, arch)

    archs = [config.arch] if config.arch else ARCHITECTURES
    repo_names = config.repos
    total_steps = len(repo_names) * len(archs)
    step = 0

    for repo_name in repo_names:
        repo = REPOS[repo_name]
        for arch in archs:
            step += 1
            config.on_progress(step / total_steps, f"Searching {repo_name}/{arch}…")

            try:
                text = load_apkindex(
                    repo, arch, config.auth_token, config.force_refresh
                )
            except PermissionError as e:
                config.on_progress(
                    step / total_steps,
                    f"Skipping {repo_name}/{arch}: {e}",
                )
                continue
            except Exception as e:
                config.on_progress(
                    step / total_steps,
                    f"Error fetching {repo_name}/{arch}: {e}",
                )
                continue

            entries = parse_apkindex(text, repo_name, arch)
            all_names = [e.name.lower() for e in entries]

            # Build a near-match set from difflib for this arch's full name list.
            near_names = set(
                difflib.get_close_matches(
                    query, all_names, n=20, cutoff=config.near_match_cutoff
                )
            )

            for entry in entries:
                key = (repo_name, entry.name, arch)
                if key in seen:
                    continue

                name_lower = entry.name.lower()
                if name_lower == query:
                    match_type = MatchType.EXACT
                elif query in name_lower or name_lower in query:
                    match_type = MatchType.PARTIAL
                elif name_lower in near_names:
                    match_type = MatchType.NEAR
                else:
                    continue

                seen.add(key)
                results.append(SearchResult(package=entry, match_type=match_type))

    results.sort(key=lambda r: r.sort_key)
    return results
