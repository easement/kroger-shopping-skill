from __future__ import annotations

import argparse
import os
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import urlparse

from scripts.ad_capture import DEFAULT_LOCATION_ID, AdCaptureResult, StaticAdCaptureAdapter, build_manual_fallback_result
from scripts.config_loader import load_planner_config
from scripts.http_recording import HttpRecorder
from scripts.kroger_web_capture import (
    KrogerPlaywrightAdCaptureAdapter,
    KrogerWebAdCaptureAdapter,
    KrogerWebCaptureConfig,
)
from scripts.menu_planner import check_eligibility
from scripts.pipeline import run_menu_pipeline_with_search
from scripts.recipe_search import JsonFixtureRecipeSearchAdapter, documents_to_candidates
from scripts.replay_parsers import replay_ad_capture_dir, replay_recipe_capture_dir
from scripts.web_recipe_search import (
    PlaywrightRecipeSearchAdapter,
    WebRecipeSearchAdapter,
    WebSearchConfig,
    default_fetch_text,
)


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


def _build_sale_price_lookup(result: object) -> dict[str, str]:
    sale_items = getattr(getattr(result, "ad_context", None), "sale_items", ()) or ()
    lookup: dict[str, str] = {}
    for item in sale_items:
        name = str(getattr(item, "name", "")).strip()
        price = str(getattr(item, "price_text", "")).strip()
        if not name or not price:
            continue
        lookup[name.lower()] = price
    return lookup


def _meal_prefix_and_price(result: object, item: object, sale_price_lookup: dict[str, str]) -> tuple[str, str]:
    matches = list(getattr(item.candidate, "sale_item_matches", ()) or ())
    protein = str(getattr(item.candidate, "protein", "")).strip()
    protein_lower = protein.lower()

    if matches and protein_lower:
        for match in matches:
            match_text = str(match).strip()
            if not match_text:
                continue
            match_lower = match_text.lower()
            if protein_lower in match_lower or match_lower in protein_lower:
                price = sale_price_lookup.get(match_lower, "N/A")
                return protein.title(), price

    if protein:
        # If no direct protein match exists, keep the protein as the main label
        # and use the best available matched sale price.
        for sale_name, sale_price in sale_price_lookup.items():
            if protein_lower and protein_lower in sale_name:
                return protein.title(), sale_price
        if matches:
            fallback_match = str(matches[0]).strip().lower()
            return protein.title(), sale_price_lookup.get(fallback_match, "N/A")
        return protein.title(), "N/A"

    if matches:
        main = str(matches[0]).strip()
        if main:
            price = sale_price_lookup.get(main.lower(), "N/A")
            return main.title(), price

    return "Unknown", "N/A"


def _format_meal_plain_lines(result: object) -> str:
    sale_price_lookup = _build_sale_price_lookup(result)
    lines: list[str] = []
    for item in _group_meals_by_protein(result):
        site = _pretty_site_name(item.candidate.url)
        main, price = _meal_prefix_and_price(result, item, sale_price_lookup)
        lines.append(f"{main} - {item.candidate.title}({site} - {item.candidate.rating:.1f}) - {price}")
        lines.append(item.candidate.url)
    return "\n".join(lines)


def _format_meal_markdown_lines(result: object) -> str:
    sale_price_lookup = _build_sale_price_lookup(result)
    lines: list[str] = []
    for item in _group_meals_by_protein(result):
        site = _pretty_site_name(item.candidate.url)
        main, price = _meal_prefix_and_price(result, item, sale_price_lookup)
        label = f"{main} - {item.candidate.title}({site} - {item.candidate.rating:.1f}) - {price}"
        lines.append(f"- [{label}]({item.candidate.url})")
    return "\n".join(lines)


def _group_meals_by_protein(result: object) -> list[object]:
    meals = list(getattr(result, "meals", ()) or ())
    if len(meals) <= 1:
        return meals

    grouped: dict[str, list[object]] = {}
    protein_order: list[str] = []
    for meal in meals:
        protein = str(getattr(meal.candidate, "protein", "")).strip().lower() or "unknown"
        if protein not in grouped:
            grouped[protein] = []
            protein_order.append(protein)
        grouped[protein].append(meal)

    ordered: list[object] = []
    for protein in protein_order:
        ordered.extend(grouped[protein])
    return ordered


def _validate_output_schema(payload: dict[str, object]) -> None:
    required_fields = [
        "location_id",
        "ad_source",
        "used_manual_fallback",
        "used_recipe_fallback",
        "meal_count",
        "meals",
    ]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        raise ValueError(f"Output schema missing fields: {missing}")
    meals = payload.get("meals")
    if not isinstance(meals, list):
        raise ValueError("Output schema field 'meals' must be a list")


def _run_preflight_validation(args: argparse.Namespace, planner_config: object) -> dict[str, object]:
    _ = planner_config
    checks: dict[str, object] = {
        "planner_config": "ok",
        "ad_input": "ok",
        "recipe_input": "ok",
    }

    if args.ad_fixture:
        _load_manual_items(args.ad_fixture)

    if args.manual_fallback_fixture:
        _load_manual_items(args.manual_fallback_fixture)

    if args.search_mode == "fixture":
        adapter = JsonFixtureRecipeSearchAdapter(args.recipe_fixture)
        docs = adapter.search(())
        checks["recipe_count"] = len(docs)

    return {
        "status": "ok",
        "validate_only": True,
        "checks": checks,
    }


def _adapter_stats(adapter: object) -> dict[str, object] | None:
    stats = getattr(adapter, "last_stats", None)
    if isinstance(stats, dict):
        return stats
    return None


def _build_ad_adapter(
    *,
    location_id: str,
    use_failed_capture: bool,
    ad_fixture_path: str | None,
    ad_mode: str,
    kroger_circular_id: str | None = None,
    kroger_cookie_header: str | None = None,
    kroger_extra_headers: dict[str, str] | None = None,
    ad_fetch_wrapper: Callable[[str, dict[str, str]], str] | None = None,
    ad_fetch_json_wrapper: Callable[[str, dict[str, str]], object] | None = None,
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
            config=KrogerWebCaptureConfig(
                circular_id=kroger_circular_id,
                cookie_header=kroger_cookie_header,
                extra_headers=kroger_extra_headers,
            ),
            fetch_text=ad_fetch_wrapper,
            fetch_json=ad_fetch_json_wrapper,
        )
    if ad_mode == "playwright":
        return KrogerPlaywrightAdCaptureAdapter(
            config=KrogerWebCaptureConfig(
                circular_id=kroger_circular_id,
                cookie_header=kroger_cookie_header,
                extra_headers=kroger_extra_headers,
            )
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
    parser.add_argument(
        "--kroger-cookie",
        default=None,
        help="Raw Cookie header value for Kroger requests (overrides synthesized x-active-modality)",
    )
    parser.add_argument(
        "--kroger-cookie-file",
        default=None,
        help="Path to a file containing the raw Cookie header value for Kroger requests",
    )
    parser.add_argument(
        "--kroger-extra-headers-json",
        default=None,
        help='JSON object of extra headers, e.g. \'{"x-kroger-channel":"WEB"}\'',
    )
    parser.add_argument(
        "--kroger-extra-headers-file",
        default=None,
        help="Path to JSON file containing an object of extra headers",
    )
    parser.add_argument("--recipe-fixture", default=None)
    parser.add_argument("--ad-fixture", default=None)
    parser.add_argument("--manual-fallback-fixture", default=None)
    parser.add_argument("--simulate-ad-failure", action="store_true")
    parser.add_argument("--ad-mode", choices=("fixture", "web", "playwright"), default="fixture")
    parser.add_argument(
        "--kroger-circular-id",
        default=None,
        help="Atlas weekly circular UUID; probes shoppable-weekly-deals/deals first. "
        "Fallback: env KROGER_CIRCULAR_ID or parse from weekly ad HTML when present.",
    )
    parser.add_argument("--search-mode", choices=("fixture", "web", "playwright"), default="fixture")
    parser.add_argument("--web-max-links", type=int, default=20)
    parser.add_argument("--web-fallback-to-fixture", action="store_true")
    parser.add_argument("--target-count", type=int, default=10)
    parser.add_argument("--planner-config", default="config/planner_config.json")
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
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--replay-captures-dir", default=None)
    parser.add_argument("--quality-gate", action="store_true")
    parser.add_argument("--quality-min-meals", type=int, default=None)
    parser.add_argument("--quality-min-trusted-ratio", type=float, default=None)
    args = parser.parse_args()
    kroger_circular_id = args.kroger_circular_id or os.environ.get("KROGER_CIRCULAR_ID") or None
    if kroger_circular_id:
        kroger_circular_id = kroger_circular_id.strip() or None

    kroger_cookie_header = args.kroger_cookie or os.environ.get("KROGER_COOKIE") or None
    kroger_cookie_file = args.kroger_cookie_file or None
    if kroger_cookie_header and kroger_cookie_file:
        raise ValueError("Provide only one of --kroger-cookie or --kroger-cookie-file")
    if kroger_cookie_file:
        cookie_path = Path(kroger_cookie_file)
        if not cookie_path.exists():
            raise ValueError(f"--kroger-cookie-file not found: {kroger_cookie_file}")
        kroger_cookie_header = cookie_path.read_text().strip()
        # Sanitize common pastes from DevTools:
        # - sometimes includes "cookie " prefix
        # - contains newlines which are invalid for HTTP headers
        kroger_cookie_header = kroger_cookie_header.replace("\r", " ").replace("\n", " ").strip()
        lowered = kroger_cookie_header.lower()
        if lowered.startswith("cookie "):
            kroger_cookie_header = kroger_cookie_header[len("cookie ") :].lstrip()
        if lowered.startswith("cookie:"):
            kroger_cookie_header = kroger_cookie_header[len("cookie:") :].lstrip()
        if not kroger_cookie_header:
            kroger_cookie_header = None

    kroger_extra_headers: dict[str, str] | None = None
    extra_headers_json = args.kroger_extra_headers_json or os.environ.get("KROGER_EXTRA_HEADERS_JSON") or None
    extra_headers_file = args.kroger_extra_headers_file or None
    if extra_headers_json and extra_headers_file:
        raise ValueError(
            "Provide only one of --kroger-extra-headers-json or --kroger-extra-headers-file"
        )
    if extra_headers_json:
        parsed = json.loads(extra_headers_json)
        if not isinstance(parsed, dict):
            raise ValueError("--kroger-extra-headers-json must be a JSON object")
        kroger_extra_headers = {}
        for k, v in parsed.items():
            if isinstance(v, str):
                kroger_extra_headers[str(k)] = v
            else:
                kroger_extra_headers[str(k)] = json.dumps(v, separators=(",", ":"))
    if extra_headers_file:
        extra_path = Path(extra_headers_file)
        if not extra_path.exists():
            raise ValueError(f"--kroger-extra-headers-file not found: {extra_headers_file}")
        parsed = json.loads(extra_path.read_text())
        if not isinstance(parsed, dict):
            raise ValueError("--kroger-extra-headers-file must contain a JSON object")
        kroger_extra_headers = {}
        for k, v in parsed.items():
            if isinstance(v, str):
                kroger_extra_headers[str(k)] = v
            else:
                kroger_extra_headers[str(k)] = json.dumps(v, separators=(",", ":"))

    def progress(message: str) -> None:
        if args.pretty:
            print(message, file=sys.stderr)

    if args.replay_captures_dir:
        root = Path(args.replay_captures_dir)
        ad_stats = replay_ad_capture_dir(str(root / "ad"))
        recipe_stats = replay_recipe_capture_dir(str(root / "recipe"))
        payload = {
            "status": "ok",
            "replay_only": True,
            "captures_root": str(root),
            "ad": {
                "files_scanned": ad_stats.files_scanned,
                "files_parsed": ad_stats.files_parsed,
                "items_extracted": ad_stats.items_extracted,
                "files_with_signal": ad_stats.files_with_signal,
                "files_with_non_recipe_jsonld": ad_stats.files_with_non_recipe_jsonld,
            },
            "recipe": {
                "files_scanned": recipe_stats.files_scanned,
                "files_parsed": recipe_stats.files_parsed,
                "items_extracted": recipe_stats.items_extracted,
                "files_with_signal": recipe_stats.files_with_signal,
                "files_with_non_recipe_jsonld": recipe_stats.files_with_non_recipe_jsonld,
            },
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.search_mode == "fixture" and not args.recipe_fixture:
        raise ValueError("--recipe-fixture is required when --search-mode fixture")

    planner_config = load_planner_config(args.planner_config)
    progress(f"Planner config: {args.planner_config}")

    if args.validate_only:
        validation = _run_preflight_validation(args=args, planner_config=planner_config)
        print(json.dumps(validation, indent=2))
        return 0

    recipe_fetch_wrapper = None
    ad_fetch_wrapper = None
    ad_fetch_json_wrapper = None
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

        # Shared cookie jar so Atlas endpoints can reuse cookies set during the initial
        # weekly-ad HTML request (required for some protected endpoints).
        from http.cookiejar import CookieJar
        from urllib.request import HTTPCookieProcessor, build_opener

        kroger_cookiejar = CookieJar()
        kroger_opener = build_opener(HTTPCookieProcessor(kroger_cookiejar))

        def recipe_fetch(url: str) -> str:
            body = default_fetch_text(url)
            recipe_recorder.record(url, body)
            return body

        def ad_fetch(url: str, headers: dict[str, str]) -> str:
            from urllib.request import Request

            request = Request(url, headers=headers)
            with kroger_opener.open(request, timeout=12) as response:
                body = response.read().decode("utf-8", errors="ignore")
            ad_recorder.record(url, body)
            return body

        def ad_fetch_json(url: str, headers: dict[str, str]) -> object:
            from urllib.request import Request

            request = Request(url, headers={**headers, "Accept": "application/json"})
            with kroger_opener.open(request, timeout=12) as response:
                raw = response.read().decode("utf-8", errors="ignore")
            payload = json.loads(raw)
            try:
                body = json.dumps(payload)
            except TypeError:
                body = str(payload)
            ad_recorder.record(url, body)
            return payload

        recipe_fetch_wrapper = recipe_fetch
        ad_fetch_wrapper = ad_fetch
        ad_fetch_json_wrapper = ad_fetch_json
        progress(f"HTTP recording enabled: {base_dir}")
        if args.record_metadata:
            progress(f"Metadata index enabled: {metadata_file}")

    progress("[1/5] Preparing adapters")
    ad_adapter = _build_ad_adapter(
        location_id=args.location_id,
        use_failed_capture=args.simulate_ad_failure,
        ad_fixture_path=args.ad_fixture,
        ad_mode=args.ad_mode,
        kroger_circular_id=kroger_circular_id,
        kroger_cookie_header=kroger_cookie_header,
        kroger_extra_headers=kroger_extra_headers,
        ad_fetch_wrapper=ad_fetch_wrapper,
        ad_fetch_json_wrapper=ad_fetch_json_wrapper,
    )
    if args.search_mode == "web":
        recipe_adapter = WebRecipeSearchAdapter(
            config=WebSearchConfig(max_links=args.web_max_links),
            fetch_text=recipe_fetch_wrapper,
        )
        progress(f"Recipe search mode: web (max_links={args.web_max_links})")
    elif args.search_mode == "playwright":
        recipe_adapter = PlaywrightRecipeSearchAdapter(
            config=WebSearchConfig(max_links=args.web_max_links),
            fetch_text=recipe_fetch_wrapper,
        )
        progress(f"Recipe search mode: playwright (max_links={args.web_max_links})")
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
    if args.ad_mode in ("web", "playwright") and kroger_circular_id:
        progress(f"Kroger Atlas circular id (CLI/env): {kroger_circular_id}")
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
        planner_config=planner_config,
    )
    used_recipe_fallback = False
    web_recipe_stats = _adapter_stats(recipe_adapter) if args.search_mode in ("web", "playwright") else None
    if (
        args.search_mode in ("web", "playwright")
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
            planner_config=planner_config,
        )
        used_recipe_fallback = True
        active_recipe_adapter = fallback_adapter
    progress("[3/5] Pipeline completed")
    progress(f"Ad source: {result.ad_context.source}")
    progress(f"Used manual fallback: {result.used_manual_fallback}")
    progress(f"Selected meals: {len(result.meals)}")
    if result.diagnostics and result.diagnostics.insufficient_reason:
        progress(f"Selection warning: {result.diagnostics.insufficient_reason}")

    summary: dict[str, object] | None = None
    if args.pretty_summary:
        docs = active_recipe_adapter.search(result.ad_context.sale_items)
        candidates = documents_to_candidates(docs=docs, sale_items=result.ad_context.sale_items)
        reason_counts: Counter[str] = Counter()
        eligible_count = 0
        for candidate in candidates:
            check = check_eligibility(candidate, planner_config)
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
        "diagnostics": (
            {
                "total_candidates": result.diagnostics.total_candidates,
                "eligible_candidates": result.diagnostics.eligible_candidates,
                "selected_meals": result.diagnostics.selected_meals,
                "trusted_selected": result.diagnostics.trusted_selected,
                "trusted_ratio": round(result.diagnostics.trusted_ratio, 3),
                "insufficient_reason": result.diagnostics.insufficient_reason,
            }
            if result.diagnostics
            else None
        ),
        "summary": summary,
        "adapter_stats": {
            "ad": _adapter_stats(ad_adapter),
            "recipe": _adapter_stats(active_recipe_adapter),
            "recipe_web": web_recipe_stats,
        },
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
    _validate_output_schema(output)
    if args.quality_gate:
        diagnostics = output.get("diagnostics") or {}
        selected_meals = int(diagnostics.get("selected_meals") or output["meal_count"])
        trusted_ratio = float(diagnostics.get("trusted_ratio") or 0.0)
        min_meals = args.quality_min_meals if args.quality_min_meals is not None else args.target_count
        min_trusted_ratio = (
            args.quality_min_trusted_ratio
            if args.quality_min_trusted_ratio is not None
            else planner_config.min_trusted_ratio
        )

        quality_errors: list[str] = []
        if selected_meals < min_meals:
            quality_errors.append(
                f"quality_gate_failed:selected_meals({selected_meals})<required({min_meals})"
            )
        if trusted_ratio < min_trusted_ratio:
            quality_errors.append(
                f"quality_gate_failed:trusted_ratio({trusted_ratio:.3f})<required({min_trusted_ratio:.3f})"
            )

        if quality_errors:
            raise ValueError("; ".join(quality_errors))

    progress("[4/5] Rendering output")
    if args.pretty:
        ad_stats = output["adapter_stats"]["ad"]
        recipe_stats = output["adapter_stats"]["recipe"]
        if ad_stats:
            progress(f"[debug][ad] {ad_stats}")
        if recipe_stats:
            progress(f"[debug][recipe] {recipe_stats}")
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
