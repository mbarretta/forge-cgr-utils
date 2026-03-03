# forge-cgr-utils

Chainguard field utilities for [FORGE](https://github.com/mbarretta/forge) — a single installable package that registers multiple FORGE plugins.

## Plugins

### `apk-find`

Search Chainguard APK repositories for packages by name.

**Repos searched:**

| Repo | URL | Auth |
|------|-----|------|
| `wolfi` | https://packages.wolfi.dev/os | None |
| `extras` | https://packages.cgr.dev/extras | None |
| `chainguard` | https://apk.cgr.dev/chainguard | chainctl token (auto-fetched) |

**Parameters:**

| Name | Description | Default |
|------|-------------|---------|
| `package` | Package name to search for | *(required)* |
| `repos` | Comma-separated repos to search, or `all` | `all` |
| `arch` | Architecture (`x86_64`, `aarch64`, or `all`) | `all` |
| `exact-only` | Only show exact name matches | `false` |
| `refresh` | Force refresh of cached APKINDEX files | `false` |

**Match types** (ranked in output order):
- **exact** — package name matches query exactly
- **partial** — package name contains query, or query contains package name
- **near** — fuzzy match via `difflib` (cutoff 0.6)

APKINDEX files are cached to `~/.cache/apk-find/` with a 1-hour TTL.

## Installation

```bash
forge plugin install forge-cgr-utils
```

## Development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mbarretta/forge-cgr-utils.git
cd forge-cgr-utils
uv sync
uv run pytest tests/ -v
```
