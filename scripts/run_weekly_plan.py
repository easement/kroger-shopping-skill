from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import urlparse

from scripts.ad_capture import DEFAULT_LOCATION_ID, AdCaptureResult, StaticAdCaptureAdapter, build_manual_fallback_result
from scripts.http_recording import HttpRecorder
from scripts.kroger_web_capture import KrogerWebAdCaptureAdapter, KrogerWebCaptureConfig
from scripts.menu_planner import check_eligibility
from scripts.pipeline import run_menu_pipeline_with_search
from scripts.recipe_search import JsonFixtureRecipeSearchAdapter, documents_to_candidates
from scripts.web_recipe_search import WebRecipeSearchAdapter, WebSearchConfig, default_fetch_text


def _load_manual_items(path: str) -> list[dict[str, str]]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list):
        raise ValueError("Manual items JSON must be a list")
    return payload


def _pretty_site_name(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    base = netloc.split(".")[0] if netloc else "unknown"
    return base.replace("-", " ").replace("_", " ").strip()


def _format_meal_plain_lines(result: object) -> str:
    lines: list[str] = []
    for item in result.meals:
        site = _pretty_site_name(item.candidate.url)
        lines.append(f"{item.candidate.title}({site} - {item.candidate.rating:.1f})")
        lines.append(item.candidate.url)
    return "\n".join(lines)


def _format_meal_markdown_lines(result: object) -> str:
    lines: list[str] = []
    for item in result.meals:
        site = _pretty_site_name(item.candidate.url)
        label = f"{item.candidate.title}({site} - {item.candidate.rating:.1f})"
        lines.append(f"- [{label}]({item.candidate.url})")
    return "\n".join(lines)


def _build_ad_adapter(
    *,
    location_id: str,
    use_failed_capture: bool,
    ad_fixture_path: str | None,
    ad_mode: str,
    ad_fetch_wrapper: Callable[[str, dict[str, str]], str] | None = None,
) -> object:
    if use_failed_capture:
        return StaticAdCaptureAdapter(
            AdCaptureResult(
                success=False,
                location_id=location_id,
                sale_items=(),
                source="kroger-web",
                message="Simulated capture failure",
            )
        )

    if ad_mode == "web":
        return KrogerWebAdCaptureAdapter(
            config=KrogerWebCaptureConfig(),
            fetch_text=ad_fetch_wrapper,
        )

    if ad_fixture_path:
        manual_like = _load_manual_items(ad_fixture_path)
        ad_result = build_manual_fallback_result(manual_like, location_id=location_id)
        return StaticAdCaptureAdapter(
            AdCaptureResult(
                success=True,
                location_id=location_id,
                sale_items=ad_result.sale_items,
                source="fixture-ad",
            )
        )

    return StaticAdCaptureAdapter(
        AdCaptureResult(
            success=True,
            location_id=location_id,
            sale_items=(),
            source="fixture-ad",
            message="No sale items fixture provided",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run weekly menu plan from fixture inputs")
    parser.add_argument("--location-id", default=DEFAULT_LOCATION_ID)
    parser.add_argument("--recipe-fixture", default=None)
    parser.add_argument("--ad-fixture", default=None)
    parser.add_argument("--manual-fallback-fixture", default=None)
    parser.add_argument("--simulate-ad-failure", action="store_true")
    parser.add_argument("--ad-mode", choices=("fixture", "web"), default="fixture")
    parser.add_argument("--search-mode", choices=("fixture", "web"), default="fixture")
    parser.add_argument("--web-max-links", type=int, default=20)
    parser.add_argument("--web-fallback-to-fixture", action="store_true")
    parser.add_argument("--target-count", type=int, default=10)
    parser.add_argument(
        "--output-format",
        choices=("json", "meal-lines", "meal-markdown"),
        default="json",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--pretty-summary", action="store_true")
    parser.add_argument("--save-run", action="store_true")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--record-http-dir", default=None)
    parser.add_argument("--record-metadata", action="store_true")
    args = parser.parse_args()
    if args.search_mode == "fixture" and not args.recipe_fixture:
        raise ValueError("--recipe-fixture is required when --search-mode fixture")

    def progress(message: str) -> None:
        if args.pretty:
            print(message, file=sys.stderr)

    recipe_fetch_wrapper = None
    ad_fetch_wrapper = None
    if args.record_http_dir:
        base_dir = Path(args.record_http_dir)
        metadata_file = base_dir / "captures.jsonl" if args.record_metadata else None
        recipe_recorder = HttpRecorder(
            output_dir=base_dir / "recipe",
            prefix="recipe-http",
            metadata_file=metadata_file,
            channel="recipe",
        )
        ad_recorder = HttpRecorder(
            output_dir=base_dir / "ad",
            prefix="ad-http",
            metadata_file=metadata_file,
            channel="ad",
        )

        def recipe_fetch(url: str) -> str:
            body = default_fetch_text(url)
            recipe_recorder.record(url, body)
            return body

        def ad_fetch(url: str, headers: dict[str, str]) -> str:
            from scripts.kroger_web_capture import default_fetch_text as kroger_default_fetch_text

            body = kroger_default_fetch_text(url, headers)
            ad_recorder.record(url, body)
            return body

        recipe_fetch_wrapper = recipe_fetch
        ad_fetch_wrapper = ad_fetch
        progress(f"HTTP recording enabled: {base_dir}")
        if args.record_metadata:
            progress(f"Metadata index enabled: {metadata_file}")

    progress("[1/5] Preparing adapters")
    ad_adapter = _build_ad_adapter(
        location_id=args.location_id,
        use_failed_capture=args.simulate_ad_failure,
        ad_fixture_path=args.ad_fixture,
        ad_mode=args.ad_mode,
        ad_fetch_wrapper=ad_fetch_wrapper,
    )
    if args.search_mode == "web":
        recipe_adapter = WebRecipeSearchAdapter(
            config=WebSearchConfig(max_links=args.web_max_links),
            fetch_text=recipe_fetch_wrapper,
        )
        progress(f"Recipe search mode: web (max_links={args.web_max_links})")
    else:
        recipe_adapter = JsonFixtureRecipeSearchAdapter(args.recipe_fixture)
        progress("Recipe search mode: fixture")
    active_recipe_adapter = recipe_adapter
    progress(f"Location: {args.location_id}")
    if args.search_mode == "fixture":
        progress(f"Recipe fixture: {args.recipe_fixture}")
    if args.ad_fixture:
        progress(f"Ad fixture: {args.ad_fixture}")
    progress(f"Ad capture mode: {args.ad_mode}")
    if args.simulate_ad_failure:
        progress("Ad capture mode: simulated failure")

    manual_fallback_items = (
        _load_manual_items(args.manual_fallback_fixture) if args.manual_fallback_fixture else None
    )
    if manual_fallback_items:
        progress(f"Manual fallback entries loaded: {len(manual_fallback_items)}")

    progress("[2/5] Running pipeline")

    result = run_menu_pipeline_with_search(
        ad_adapter=ad_adapter,
        recipe_search_adapter=recipe_adapter,
        location_id=args.location_id,
        manual_fallback_items=manual_fallback_items,
        target_count=args.target_count,
    )
    used_recipe_fallback = False
    if (
        args.search_mode == "web"
        and args.web_fallback_to_fixture
        and len(result.meals) == 0
        and args.recipe_fixture
    ):
        progress("No web results found, falling back to recipe fixture data")
        fallback_adapter = JsonFixtureRecipeSearchAdapter(args.recipe_fixture)
        result = run_menu_pipeline_with_search(
            ad_adapter=ad_adapter,
            recipe_search_adapter=fallback_adapter,
            location_id=args.location_id,
            manual_fallback_items=manual_fallback_items,
            target_count=args.target_count,
        )
        used_recipe_fallback = True
        active_recipe_adapter = fallback_adapter
    progress("[3/5] Pipeline completed")
    progress(f"Ad source: {result.ad_context.source}")
    progress(f"Used manual fallback: {result.used_manual_fallback}")
    progress(f"Selected meals: {len(result.meals)}")

    summary: dict[str, object] | None = None
    if args.pretty_summary:
        docs = active_recipe_adapter.search(result.ad_context.sale_items)
        candidates = documents_to_candidates(docs=docs, sale_items=result.ad_context.sale_items)
        reason_counts: Counter[str] = Counter()
        eligible_count = 0
        for candidate in candidates:
            check = check_eligibility(candidate)
            reason_counts[check.reason] += 1
            if check.eligible:
                eligible_count += 1

        excluded_total = len(candidates) - eligible_count
        progress("[summary] Candidate counts")
        progress(f" - loaded: {len(docs)}")
        progress(f" - mapped: {len(candidates)}")
        progress(f" - eligible: {eligible_count}")
        progress(f" - excluded: {excluded_total}")
        for reason, count in sorted(reason_counts.items()):
            if reason == "eligible":
                continue
            progress(f" - excluded_{reason}: {count}")
        summary = {
            "loaded_docs": len(docs),
            "mapped_candidates": len(candidates),
            "eligible_candidates": eligible_count,
            "excluded_candidates": excluded_total,
            "excluded_by_reason": {
                reason: count for reason, count in sorted(reason_counts.items()) if reason != "eligible"
            },
        }

    output = {
        "location_id": result.ad_context.location_id,
        "ad_source": result.ad_context.source,
        "used_manual_fallback": result.used_manual_fallback,
        "used_recipe_fallback": used_recipe_fallback,
        "meal_count": len(result.meals),
        "summary": summary,
        "meals": [
            {
                "title": item.candidate.title,
                "url": item.candidate.url,
                "rating": item.candidate.rating,
                "vote_count": item.candidate.vote_count,
                "score": round(item.score, 4),
                "cuisine": item.candidate.cuisine,
                "protein": item.candidate.protein,
                "sale_item_matches": list(item.candidate.sale_item_matches),
            }
            for item in result.meals
        ],
    }
    progress("[4/5] Rendering output")
    if args.output_format == "meal-lines":
        print(_format_meal_plain_lines(result))
    elif args.output_format == "meal-markdown":
        print(_format_meal_markdown_lines(result))
    else:
        print(json.dumps(output, indent=2))
    if args.save_run:
        runs_dir = Path(args.runs_dir)
        runs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = runs_dir / f"weekly-plan-{timestamp}.json"
        out_path.write_text(json.dumps(output, indent=2))
        progress(f"Saved run output: {out_path}")
    progress("[5/5] Done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
