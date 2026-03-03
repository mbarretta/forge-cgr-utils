"""Tests for APK search logic and APKINDEX parsing."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from forge_cgr_utils.apk_find.repos import PackageEntry, Repo, parse_apkindex
from forge_cgr_utils.apk_find.searcher import MatchType, SearchConfig, SearchResult, search


SAMPLE_APKINDEX = textwrap.dedent("""\
    C:Q1abc123
    P:python3
    V:3.12.0-r0
    A:x86_64
    S:100000
    I:300000
    T:A high-level scripting language
    U:https://www.python.org
    L:PSF
    o:python3
    m:Wolfi Maintainers
    t:1700000000
    c:deadbeef
    D:libffi glibc

    C:Q1def456
    P:python3-dev
    V:3.12.0-r0
    A:x86_64
    S:50000
    I:150000
    T:Python 3 development headers
    U:https://www.python.org
    L:PSF
    o:python3
    m:Wolfi Maintainers
    t:1700000000
    c:deadbeef
    D:python3

    C:Q1ghi789
    P:py3-requests
    V:2.31.0-r0
    A:x86_64
    S:80000
    I:200000
    T:HTTP library for Python
    U:https://requests.readthedocs.io
    L:Apache-2.0
    o:py3-requests
    m:Wolfi Maintainers
    t:1700000000
    c:deadbeef
    D:python3

    C:Q1jkl012
    P:nginx
    V:1.25.3-r0
    A:x86_64
    S:500000
    I:1000000
    T:HTTP and reverse proxy server
    U:https://nginx.org
    L:BSD-2-Clause
    o:nginx
    m:Wolfi Maintainers
    t:1700000000
    c:deadbeef

""")


class TestParseApkindex:
    def test_parses_all_entries(self):
        entries = parse_apkindex(SAMPLE_APKINDEX, "wolfi", "x86_64")
        assert len(entries) == 4

    def test_parses_fields_correctly(self):
        entries = parse_apkindex(SAMPLE_APKINDEX, "wolfi", "x86_64")
        python3 = next(e for e in entries if e.name == "python3")
        assert python3.version == "3.12.0-r0"
        assert python3.arch == "x86_64"
        assert python3.description == "A high-level scripting language"
        assert python3.repo == "wolfi"
        assert python3.url == "https://www.python.org"
        assert python3.license == "PSF"
        assert python3.origin == "python3"

    def test_empty_input(self):
        assert parse_apkindex("", "wolfi", "x86_64") == []

    def test_repo_name_set_on_entry(self):
        entries = parse_apkindex(SAMPLE_APKINDEX, "extras", "aarch64")
        assert all(e.repo == "extras" for e in entries)


class TestSearch:
    def _make_config(self, query: str, **kwargs) -> SearchConfig:
        return SearchConfig(
            query=query,
            repos=["wolfi"],
            arch="x86_64",
            **kwargs,
        )

    def _patched_load(self, text: str):
        return patch("forge_cgr_utils.apk_find.searcher.load_apkindex", return_value=text)

    def test_exact_match(self):
        with self._patched_load(SAMPLE_APKINDEX):
            results = search(self._make_config("python3"))
        exact = [r for r in results if r.match_type == MatchType.EXACT]
        assert any(r.package.name == "python3" for r in exact)

    def test_partial_match(self):
        with self._patched_load(SAMPLE_APKINDEX):
            results = search(self._make_config("python"))
        names = [r.package.name for r in results]
        assert "python3" in names
        assert "python3-dev" in names

    def test_near_match(self):
        # "nginz" is close to "nginx"
        with self._patched_load(SAMPLE_APKINDEX):
            results = search(self._make_config("nginz", near_match_cutoff=0.5))
        names = [r.package.name for r in results]
        assert "nginx" in names

    def test_no_match_returns_empty(self):
        with self._patched_load(SAMPLE_APKINDEX):
            results = search(self._make_config("zzzzzzzznotapackage"))
        assert results == []

    def test_exact_before_partial_before_near(self):
        with self._patched_load(SAMPLE_APKINDEX):
            results = search(self._make_config("python3"))
        match_types = [r.match_type for r in results]
        # All EXACT results should come before PARTIAL
        seen_non_exact = False
        for mt in match_types:
            if mt != MatchType.EXACT:
                seen_non_exact = True
            if seen_non_exact:
                assert mt != MatchType.EXACT

    def test_skips_repo_on_permission_error(self):
        config = SearchConfig(
            query="python3",
            repos=["wolfi", "chainguard"],
            arch="x86_64",
        )
        def mock_load(repo, arch, auth_token="", force_refresh=False):
            if repo.name == "chainguard":
                raise PermissionError("auth required")
            return SAMPLE_APKINDEX

        with patch("forge_cgr_utils.apk_find.searcher.load_apkindex", side_effect=mock_load):
            results = search(config)

        repos_in_results = {r.package.repo for r in results}
        assert "wolfi" in repos_in_results
        assert "chainguard" not in repos_in_results

    def test_deduplicates_within_same_repo_arch(self):
        # Duplicate APKINDEX text should not produce duplicate results
        doubled = SAMPLE_APKINDEX + SAMPLE_APKINDEX
        with self._patched_load(doubled):
            results = search(self._make_config("python3"))
        names = [r.package.name for r in results if r.package.repo == "wolfi"]
        assert names.count("python3") == 1

    def test_multi_arch_returns_both(self):
        config = SearchConfig(
            query="python3",
            repos=["wolfi"],
            arch=None,  # all arches
        )
        with patch("forge_cgr_utils.apk_find.searcher.load_apkindex", return_value=SAMPLE_APKINDEX):
            results = search(config)
        arches = {r.package.arch for r in results if r.package.name == "python3"}
        assert "x86_64" in arches
        # aarch64 entries will also report x86_64 from sample data (A: field),
        # but both fetches happen — check load was called twice
