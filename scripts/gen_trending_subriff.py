#!/usr/bin/env python3
"""Generate configurable subreddit lists from Subriff's public rankings."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://subriff.com/Home/GetSubreddits"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "subriff-sources.json"
DEFAULT_SOURCE = "blended"
USER_AGENT = "Dfango-subreddits/1.0 (+https://github.com/Dfango/subreddits)"

DEFAULT_SCORING = {
    "rrf_k": 60.0,
    "rank_weight": 0.70,
    "coverage_weight": 0.30,
    "period_weights": {
        "daily": 0.80,
        "weekly": 1.15,
        "monthly": 1.25,
        "yearly": 1.00,
    },
    "size_weights": {
        "medium-small": 0.75,
        "medium": 1.00,
        "large": 1.10,
        "xlarge": 0.95,
    },
    "tie_seed": "subriff-v2",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _canonical_name(name: str) -> str:
    name = name.strip()
    return name[2:] if name.lower().startswith("r/") else name


NSFW_FIELDS = (
    "isNsfw",
    "internal_IsNsfw",
    "suggested_Internal_IsNsfw",
)


def _is_nsfw(subreddit: dict[str, Any]) -> bool:
    return any(_as_bool(subreddit.get(field, False)) for field in NSFW_FIELDS)


def _is_allowed(
    subreddit: dict[str, Any],
    include_nsfw: bool,
    require_nsfw: bool = False,
) -> bool:
    is_nsfw = _is_nsfw(subreddit)
    if require_nsfw and not is_nsfw:
        return False
    if include_nsfw:
        return True
    return not is_nsfw


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)

    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        raise ValueError("config must contain a sources list")

    source_names: set[str] = set()
    output_names: set[str] = set()
    report_names: set[str] = set()
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
        selection_mode = source.get("selection_mode", "ranked")
        if selection_mode not in {"ranked", "shuffle"}:
            raise ValueError("unknown selection mode: %s" % selection_mode)
        source_names.add(name)
        output_names.add(output)

        report = source.get("report")
        if report is not None:
            if (
                not isinstance(report, str)
                or Path(report).name != report
                or not report.endswith(".json")
            ):
                raise ValueError("source report must be a plain .json filename: %s" % report)
            if report in report_names:
                raise ValueError("duplicate source report: %s" % report)
            report_names.add(report)

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


def fetch_subreddit_observations(
    session: requests.Session,
    query: dict[str, Any],
    max_pages: int,
) -> list[dict[str, Any]]:
    """Fetch ranked, deduplicated observations for one Subriff query."""
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    include_nsfw = _as_bool(query.get("include_nsfw", False))
    require_nsfw = _as_bool(query.get("require_nsfw", False))
    rows_seen = 0

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
            rows_seen += 1
            if not isinstance(subreddit, dict) or not _is_allowed(
                subreddit,
                include_nsfw,
                require_nsfw,
            ):
                continue
            display_name = subreddit.get("displayName")
            if not isinstance(display_name, str) or not display_name.strip():
                continue
            name = _canonical_name(display_name)
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                observations.append({"name": name, "key": key, "rank": rows_seen})

    return observations


def fetch_subreddits(
    session: requests.Session,
    query: dict[str, Any],
    max_pages: int,
) -> list[str]:
    """Backward-compatible name-only wrapper for one Subriff query."""
    return [
        observation["name"]
        for observation in fetch_subreddit_observations(session, query, max_pages)
    ]


def _query_identifier(query: dict[str, Any]) -> str:
    return "%s:%s" % (query.get("size_filter", ""), query.get("sort_by", ""))


def _merge_scoring(defaults: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    scoring = dict(DEFAULT_SCORING)
    scoring.update(defaults.get("scoring", {}))
    scoring.update(source.get("scoring", {}))
    for field in ("period_weights", "size_weights"):
        merged = dict(DEFAULT_SCORING[field])
        merged.update(defaults.get("scoring", {}).get(field, {}))
        merged.update(source.get("scoring", {}).get(field, {}))
        scoring[field] = merged
    return scoring


def _query_weight(query: dict[str, Any], scoring: dict[str, Any]) -> float:
    period_weight = float(scoring["period_weights"].get(query.get("sort_by"), 1.0))
    size_weight = float(scoring["size_weights"].get(query.get("size_filter"), 1.0))
    return max(0.0, period_weight * size_weight)


def _stable_tie_key(name: str, seed: str) -> str:
    value = "%s:%s" % (seed, name.casefold())
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _query_cache_key(query: dict[str, Any], max_pages: int) -> tuple[Any, ...]:
    fields = (
        "size_filter",
        "search_term",
        "sort_by",
        "growth_type",
        "sort_column",
        "sort_direction",
        "date_filter",
        "allows_promotion",
        "nsfw",
        "include_nsfw",
        "require_nsfw",
    )
    return tuple((field, str(query.get(field, ""))) for field in fields) + (("max_pages", max_pages),)


def rank_source(
    source: dict[str, Any],
    defaults: dict[str, Any],
    session: requests.Session,
    query_cache: dict[tuple[Any, ...], list[dict[str, Any]]] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Rank candidates using weighted reciprocal rank fusion."""
    queries = _queries_for(source, defaults)
    scoring = _merge_scoring(defaults, source)
    rrf_k = max(1.0, float(scoring["rrf_k"]))
    rank_weight = max(0.0, float(scoring["rank_weight"]))
    coverage_weight = max(0.0, float(scoring["coverage_weight"]))
    weight_total = rank_weight + coverage_weight
    if weight_total == 0:
        raise ValueError("source scoring weights must add up to more than zero")
    rank_weight /= weight_total
    coverage_weight /= weight_total

    query_weights = [_query_weight(query, scoring) for query in queries]
    query_ids = [_query_identifier(query) for query in queries]
    max_rank_score = sum(
        weight / (rrf_k + 1.0)
        for weight in query_weights
        if weight > 0
    )
    total_query_weight = sum(
        weight for weight in query_weights if weight > 0
    ) or 1.0

    candidates: dict[str, dict[str, Any]] = {}
    max_pages = int(source.get("max_pages", defaults.get("max_pages", 1)))
    if query_cache is None:
        query_cache = {}
    for query, query_id, query_weight in zip(queries, query_ids, query_weights):
        if query_weight == 0:
            continue
        cache_key = _query_cache_key(query, max_pages)
        if cache_key not in query_cache:
            query_cache[cache_key] = fetch_subreddit_observations(session, query, max_pages)
        for observation in query_cache[cache_key]:
            key = observation["key"]
            candidate = candidates.setdefault(
                key,
                {
                    "name": observation["name"],
                    "rank_score": 0.0,
                    "query_ids": set(),
                    "periods": set(),
                    "size_filters": set(),
                    "best_rank": observation["rank"],
                    "appearances": 0,
                },
            )
            candidate["rank_score"] += query_weight / (rrf_k + observation["rank"])
            candidate["query_ids"].add(query_id)
            candidate["periods"].add(query.get("sort_by", ""))
            candidate["size_filters"].add(query.get("size_filter", ""))
            candidate["best_rank"] = min(candidate["best_rank"], observation["rank"])
            candidate["appearances"] += 1

    for candidate in candidates.values():
        rank_score = (
            candidate["rank_score"] / max_rank_score
            if max_rank_score
            else 0.0
        )
        coverage_score = sum(
            query_weights[index]
            for index, query_id in enumerate(query_ids)
            if query_id in candidate["query_ids"]
        ) / total_query_weight
        candidate["rank_score_normalized"] = rank_score
        candidate["coverage_score"] = coverage_score
        candidate["score"] = rank_weight * rank_score + coverage_weight * coverage_score

    tie_seed = str(scoring.get("tie_seed", DEFAULT_SCORING["tie_seed"]))
    ranked = sorted(
        candidates.values(),
        key=lambda candidate: (
            -round(candidate["score"], 12),
            candidate["best_rank"],
            -candidate["appearances"],
            _stable_tie_key(candidate["name"], tie_seed),
        ),
    )
    limit = int(source.get("limit", defaults.get("limit", 35)))
    selection_mode = source.get("selection_mode", "ranked")
    if selection_mode == "shuffle":
        shuffle_seed = str(source.get("shuffle_seed", source["name"]))
        if shuffle_seed == "daily":
            shuffle_seed = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        shuffle_seed = "%s:%s" % (shuffle_seed, source["name"])
        selection_order = sorted(
            ranked,
            key=lambda candidate: _stable_tie_key(candidate["name"], shuffle_seed),
        )
    else:
        selection_order = ranked
    selected = selection_order[:limit]
    selected_keys = {candidate["name"].casefold() for candidate in selected}
    report = [
        {
            "name": candidate["name"],
            "score": round(candidate["score"], 12),
            "rank_score": round(candidate["rank_score_normalized"], 12),
            "coverage_score": round(candidate["coverage_score"], 12),
            "best_rank": candidate["best_rank"],
            "appearances": candidate["appearances"],
            "periods": sorted(candidate["periods"]),
            "size_filters": sorted(candidate["size_filters"]),
            "selected": candidate["name"].casefold() in selected_keys,
        }
        for candidate in ranked
    ]
    return [candidate["name"] for candidate in selected], report


def generate_source(
    source: dict[str, Any],
    defaults: dict[str, Any],
    session: requests.Session,
    query_cache: dict[tuple[Any, ...], list[dict[str, Any]]] | None = None,
) -> list[str]:
    """Return Apollo-compatible names from the weighted ranking."""
    names, _report = rank_source(source, defaults, session, query_cache)
    return names


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


def _write_report_atomic(path: Path, report: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".%s." % path.name,
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
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
        generated: dict[str, list[str]] = {}
        reports: dict[str, list[dict[str, Any]]] = {}
        query_cache: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for source in selected:
            names, report = rank_source(
                source,
                config.get("defaults", {}),
                session,
                query_cache,
            )
            generated[source["output"]] = names
            if source.get("report"):
                reports[source["report"]] = report
        if any(not names for names in generated.values()):
            raise RuntimeError("one or more sources returned no subreddits")

        if args.all_sources or args.write:
            for output, names in generated.items():
                _write_atomic(args.output_dir / output, names)
            for report, entries in reports.items():
                _write_report_atomic(args.output_dir / report, entries)
        else:
            sys.stdout.write("\n".join(generated[selected[0]["output"]]) + "\n")
        return 0
    except (OSError, ValueError, requests.RequestException, RuntimeError) as error:
        print("Aborting: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
