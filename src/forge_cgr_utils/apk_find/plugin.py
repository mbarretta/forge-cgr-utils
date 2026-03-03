"""FORGE plugin entry point for apk-find."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich import box

from forge_core.auth import get_chainctl_token
from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus, ToolParam, ToolPlugin, ToolResult

from forge_cgr_utils.apk_find.repos import REPOS, ARCHITECTURES
from forge_cgr_utils.apk_find.searcher import MatchType, SearchConfig, SearchResult, search

_REPO_CHOICES = list(REPOS.keys()) + ["all"]
_ARCH_CHOICES = ARCHITECTURES + ["all"]

_MATCH_STYLE: dict[MatchType, str] = {
    MatchType.EXACT: "bold green",
    MatchType.PARTIAL: "yellow",
    MatchType.NEAR: "dim",
}


def _print_results(query: str, results: list[SearchResult]) -> None:
    console = Console()

    if not results:
        console.print(f"[yellow]No packages found matching '{query}'[/yellow]")
        return

    table = Table(
        title=f"APK search results for '{query}'",
        box=box.ROUNDED,
        show_lines=False,
    )
    table.add_column("Match", style="bold", width=8)
    table.add_column("Package", style="cyan")
    table.add_column("Version", style="white")
    table.add_column("Arch", style="dim")
    table.add_column("Repo", style="magenta")
    table.add_column("Description", style="white", max_width=50, no_wrap=False)

    for result in results:
        pkg = result.package
        match_label = result.match_type.value
        style = _MATCH_STYLE[result.match_type]
        table.add_row(
            f"[{style}]{match_label}[/{style}]",
            f"[{style}]{pkg.name}[/{style}]",
            pkg.version,
            pkg.arch,
            pkg.repo,
            pkg.description,
        )

    console.print(table)
    exact = sum(1 for r in results if r.match_type == MatchType.EXACT)
    partial = sum(1 for r in results if r.match_type == MatchType.PARTIAL)
    near = sum(1 for r in results if r.match_type == MatchType.NEAR)
    console.print(
        f"[dim]Found {len(results)} result(s): "
        f"{exact} exact, {partial} partial, {near} near-match[/dim]"
    )


class ApkFindPlugin:
    name = "apk-find"
    description = "Search Chainguard APK repositories for packages by name"
    version = "0.1.0"
    # Auth is optional: public repos (wolfi, extras) work without chainctl.
    # We self-fetch the token so that the chainguard repo is searched when
    # available but the plugin still runs when chainctl is absent.
    requires_auth = False

    def get_params(self) -> list[ToolParam]:
        return [
            ToolParam(
                name="package",
                description="Package name to search for",
                required=True,
            ),
            ToolParam(
                name="repos",
                description=(
                    "Comma-separated list of repos to search: "
                    + ", ".join(REPOS.keys())
                    + ", or 'all' (default: all)"
                ),
                default="all",
            ),
            ToolParam(
                name="arch",
                description=f"Architecture to search ({', '.join(ARCHITECTURES)}, or 'all')",
                choices=_ARCH_CHOICES,
                default="all",
            ),
            ToolParam(
                name="exact-only",
                description="Only show exact name matches",
                type="bool",
                default=False,
            ),
            ToolParam(
                name="refresh",
                description="Force refresh of cached APKINDEX files",
                type="bool",
                default=False,
            ),
        ]

    def run(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        query: str = args["package"].strip()
        repos_arg: str = args.get("repos", "all")
        arch_arg: str = args.get("arch", "all")
        exact_only: bool = args.get("exact-only", False)
        force_refresh: bool = args.get("refresh", False)

        # Resolve repo list
        if repos_arg == "all":
            repo_names = list(REPOS.keys())
        else:
            repo_names = [r.strip() for r in repos_arg.split(",")]
            invalid = [r for r in repo_names if r not in REPOS]
            if invalid:
                return ToolResult(
                    status=ResultStatus.FAILURE,
                    summary=f"Unknown repo(s): {', '.join(invalid)}. "
                            f"Valid choices: {', '.join(REPOS.keys())}",
                )

        arch = None if arch_arg == "all" else arch_arg

        ctx.progress(0.0, f"Searching for '{query}'…")

        # Self-fetch auth token if forge didn't provide one (requires_auth=False)
        # and any of the requested repos need authentication.
        auth_token = ctx.auth_token
        if not auth_token and any(REPOS[r].requires_auth for r in repo_names):
            try:
                auth_token = get_chainctl_token()
            except RuntimeError:
                ctx.progress(0.05, "chainctl not available — skipping authenticated repos")

        config = SearchConfig(
            query=query,
            repos=repo_names,
            arch=arch,
            auth_token=auth_token,
            force_refresh=force_refresh,
            on_progress=ctx.progress,
        )

        try:
            results = search(config)
        except Exception as e:
            return ToolResult(status=ResultStatus.FAILURE, summary=f"Search failed: {e}")

        if exact_only:
            results = [r for r in results if r.match_type == MatchType.EXACT]

        _print_results(query, results)
        ctx.progress(1.0, "Done")

        return ToolResult(
            status=ResultStatus.SUCCESS,
            summary=f"Found {len(results)} result(s) for '{query}'",
            data={
                "query": query,
                "total": len(results),
                "results": [
                    {
                        "name": r.package.name,
                        "version": r.package.version,
                        "arch": r.package.arch,
                        "repo": r.package.repo,
                        "description": r.package.description,
                        "match": r.match_type.value,
                    }
                    for r in results
                ],
            },
        )


def create_plugin() -> ToolPlugin:
    return ApkFindPlugin()
