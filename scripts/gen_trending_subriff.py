#!/usr/bin/env python3
"""Generate configurable subreddit lists from Subriff's public rankings."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://subriff.com/Home/GetSubreddits"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "subriff-sources.json"
DEFAULT_SOURCE = "blended"
USER_AGENT = "Dfango-subreddits/1.0 (+https://github.com/Dfango/subreddits)"


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _canonical_name(name: str) -> str:
    name = name.strip()
    return name[2:] if name.lower().startswith("r/") else name


def _is_allowed(subreddit: dict[str, Any], include_nsfw: bool) -> bool:
    if include_nsfw:
        return True
    return not any(
        subreddit.get(field)
        for field in (
            "isNsfw",
            "internal_IsNsfw",
            "suggested_Internal_IsNsfw",
        )
    )


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)

    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        raise ValueError("config must contain a sources list")

    source_names: set[str] = set()
    output_names: set[str] = set()
    for source in config["sources"]:
        if not isinstance(source, dict):
            raise ValueError("each source must be an object")
        name = source.get("name")
        output = source.get("output")
        if not isinstance(name, str) or not name:
            raise ValueError("every source needs a non-empty name")
        if name in source_names:
            raise ValueError("duplicate source name: %s" % name)
        if (
            not isinstance(output, str)
            or Path(output).name != output
            or not output.endswith(".txt")
        ):
            raise ValueError("source output must be a plain .txt filename: %s" % output)
        if output in output_names:
            raise ValueError("duplicate source output: %s" % output)
        source_names.add(name)
        output_names.add(output)

    return config


def _queries_for(source: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(source.get("queries"), list):
        queries = source["queries"]
    else:
        size_filters = source.get("size_filters", defaults.get("size_filters", []))
        periods = source.get("periods", defaults.get("periods", []))
        queries = [
            {"size_filter": size_filter, "sort_by": period}
            for size_filter in size_filters
            for period in periods
        ]

    if not queries:
        raise ValueError("source has no queries: %s" % source["name"])
    return [dict(defaults, **query, **source) for query in queries]


def fetch_subreddits(
    session: requests.Session,
    query: dict[str, Any],
    max_pages: int,
) -> list[str]:
    """Fetch and deduplicate subreddit names for one Subriff query."""
    names: list[str] = []
    seen: set[str] = set()
    include_nsfw = _as_bool(query.get("include_nsfw", False))

    for page in range(1, max_pages + 1):
        params = {
            "page": page,
            "sizeFilter": query["size_filter"],
            "searchTerm": query.get("search_term", ""),
            "sortBy": query["sort_by"],
            "growthType": query.get("growth_type", "percent"),
            "sortColumn": query.get("sort_column", ""),
            "sortDirection": query.get("sort_direction", ""),
            "dateFilter": query.get("date_filter", "all"),
            "allowsPromotion": str(_as_bool(query.get("allows_promotion", False))).lower(),
            "nsfw": str(_as_bool(query.get("nsfw", include_nsfw))).lower(),
        }
        response = session.get(BASE_URL, params=params, timeout=(10, 30))
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("subreddits") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Subriff response is missing a subreddits list")
        if not rows:
            break

        for subreddit in rows:
            if not isinstance(subreddit, dict) or not _is_allowed(subreddit, include_nsfw):
                continue
            display_name = subreddit.get("displayName")
            if not isinstance(display_name, str) or not display_name.strip():
                continue
            name = _canonical_name(display_name)
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                names.append(name)

    return names


def generate_source(
    source: dict[str, Any],
    defaults: dict[str, Any],
    session: requests.Session,
) -> list[str]:
    """Rank names by how consistently they appear across configured queries."""
    appearances: Counter[str] = Counter()
    display_names: dict[str, str] = {}
    max_pages = int(source.get("max_pages", defaults.get("max_pages", 1)))

    for query in _queries_for(source, defaults):
        for raw_name in fetch_subreddits(session, query, max_pages):
            name = _canonical_name(raw_name)
            key = name.casefold()
            appearances[key] += 1
            display_names.setdefault(key, name)

    limit = int(source.get("limit", defaults.get("limit", 35)))
    ranked_keys = sorted(appearances, key=lambda key: (-appearances[key], key))
    return [display_names[key] for key in ranked_keys[:limit]]


def _write_atomic(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".%s." % path.name,
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(names))
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--all", action="store_true", dest="all_sources")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--list-outputs", action="store_true")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        sources = {source["name"]: source for source in config["sources"]}

        if args.list_outputs:
            for source in config["sources"]:
                print(source["output"])
            return 0

        if args.all_sources and args.write:
            parser.error("--all and --write cannot be combined")
        if args.all_sources:
            selected = config["sources"]
        else:
            if args.source not in sources:
                raise ValueError("unknown source: %s" % args.source)
            selected = [sources[args.source]]

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        generated = {
            source["output"]: generate_source(source, config.get("defaults", {}), session)
            for source in selected
        }
        if any(not names for names in generated.values()):
            raise RuntimeError("one or more sources returned no subreddits")

        if args.all_sources or args.write:
            for output, names in generated.items():
                _write_atomic(args.output_dir / output, names)
        else:
            sys.stdout.write("\n".join(generated[selected[0]["output"]]) + "\n")
        return 0
    except (OSError, ValueError, requests.RequestException, RuntimeError) as error:
        print("Aborting: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
