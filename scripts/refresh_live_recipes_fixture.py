from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.ad_capture import SaleItem
from scripts.recipe_coverage import coverage_recipe_docs
from scripts.recipe_search import RecipeDocument
from scripts.web_recipe_search import PlaywrightRecipeSearchAdapter, WebRecipeSearchAdapter, WebSearchConfig


def _load_fixture_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        return set()
    urls: set[str] = set()
    for item in payload:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if url:
                urls.add(url)
    return urls


def _docs_to_fixture(docs: list[RecipeDocument]) -> list[dict[str, object]]:
    return [
        {
            "title": doc.title,
            "url": doc.url,
            "cuisine": doc.cuisine,
            "protein": doc.protein,
            "ingredients": list(doc.ingredients),
            "rating": doc.rating,
            "vote_count": doc.vote_count,
            "prep_minutes": doc.prep_minutes,
            "healthy": doc.healthy,
            "extraction_method": doc.extraction_method,
            "extraction_confidence": doc.extraction_confidence,
        }
        for doc in docs
    ]


def _load_fixture_docs(path: Path) -> list[RecipeDocument]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        return []
    docs: list[RecipeDocument] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            docs.append(
                RecipeDocument(
                    title=str(item.get("title") or "Unknown Recipe"),
                    url=str(item.get("url") or "").strip(),
                    cuisine=str(item.get("cuisine") or "Unknown"),
                    protein=str(item.get("protein") or "unknown"),
                    ingredients=tuple(item.get("ingredients", [])),
                    rating=float(item.get("rating", 0.0)),
                    vote_count=int(item.get("vote_count", 0)),
                    prep_minutes=int(item.get("prep_minutes", 45)),
                    healthy=bool(item.get("healthy", True)),
                    extraction_method=str(item.get("extraction_method") or "fixture"),
                    extraction_confidence=float(item.get("extraction_confidence", 1.0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return docs


def _seed_sale_items() -> tuple[SaleItem, ...]:
    return (SaleItem(name="chicken", price_text="N/A", category="seed"),)


def _seed_sale_item_batches() -> tuple[tuple[SaleItem, ...], ...]:
    # Multiple seed batches increase query variety and improve live recipe yield.
    names = (
        "chicken",
        "beef",
        "pork",
        "turkey",
        "ham",
        "pasta",
        "seafood",
        "lamb",
        "salmon",
        "shrimp",
        "cod",
        "tuna",
        "ground beef",
        "chicken breast",
        "chicken wings",
        "pork shoulder",
        "pork butt",
        "pork tenderloin",
        "ribs",
        "sausage",
    )
    return tuple((SaleItem(name=name, price_text="N/A", category="seed"),) for name in names)


def _exclude_rotating_urls_only(
    excluded_urls: set[str],
    coverage_docs: list[RecipeDocument],
) -> set[str]:
    coverage_urls = {doc.url for doc in coverage_docs if doc.url}
    return {url for url in excluded_urls if url not in coverage_urls}


def _select_fresh_docs(
    docs: list[RecipeDocument],
    excluded_urls: set[str],
    target_count: int,
) -> list[RecipeDocument]:
    selected: list[RecipeDocument] = []
    seen: set[str] = set()
    for doc in docs:
        url = (doc.url or "").strip()
        if not url or url in seen or url in excluded_urls:
            continue
        seen.add(url)
        selected.append(doc)
        if len(selected) >= target_count:
            break
    return selected


def _select_with_backfill(
    docs: list[RecipeDocument],
    excluded_urls: set[str],
    target_count: int,
    previous_docs: list[RecipeDocument] | None = None,
) -> tuple[list[RecipeDocument], bool]:
    selected = _select_fresh_docs(docs=docs, excluded_urls=excluded_urls, target_count=target_count)
    if len(selected) >= target_count:
        return selected, False

    used_backfill = False
    selected_urls = {doc.url for doc in selected if doc.url}

    def append_from(pool: list[RecipeDocument], *, prefer_non_foodnetwork: bool) -> None:
        nonlocal used_backfill
        ordered = pool
        if prefer_non_foodnetwork:
            ordered = sorted(
                pool,
                key=lambda doc: 1 if "foodnetwork.com" in (doc.url or "").lower() else 0,
            )
        for doc in ordered:
            if len(selected) >= target_count:
                break
            url = (doc.url or "").strip()
            if not url or url in selected_urls:
                continue
            selected.append(doc)
            selected_urls.add(url)
            used_backfill = True

    # First backfill from currently fetched docs that were excluded by freshness.
    excluded_pool = [doc for doc in docs if (doc.url or "").strip() in excluded_urls]
    append_from(excluded_pool, prefer_non_foodnetwork=True)

    # If still short, use previous fixture docs as carryover continuity.
    append_from(previous_docs or [], prefer_non_foodnetwork=True)
    return selected, used_backfill


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh live recipes fixture and exclude last week's recipe URLs"
    )
    parser.add_argument("--mode", choices=("web", "playwright"), default="playwright")
    parser.add_argument("--output", default="fixtures/recipes.live.json")
    parser.add_argument("--last-week", default="fixtures/recipes.last-week.json")
    parser.add_argument("--target-count", type=int, default=100)
    parser.add_argument("--max-links", type=int, default=300)
    parser.add_argument("--allow-shortfall", action="store_true")
    args = parser.parse_args()

    output_path = Path(args.output)
    last_week_path = Path(args.last_week)
    previous_output_docs = _load_fixture_docs(output_path)

    coverage_docs = coverage_recipe_docs()
    excluded_urls = _exclude_rotating_urls_only(_load_fixture_urls(last_week_path), coverage_docs)
    all_docs: list[RecipeDocument] = []
    seen_urls: set[str] = set()
    for doc in coverage_docs:
        url = (doc.url or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        all_docs.append(doc)
    stats_by_batch: list[dict[str, object] | None] = []
    for seed_batch in _seed_sale_item_batches():
        config = WebSearchConfig(max_links=args.max_links)
        adapter = (
            PlaywrightRecipeSearchAdapter(config=config)
            if args.mode == "playwright"
            else WebRecipeSearchAdapter(config=config)
        )
        docs = adapter.search(seed_batch)
        stats = getattr(adapter, "last_stats", None)
        if isinstance(stats, dict):
            stats_by_batch.append(stats)
        for doc in docs:
            url = (doc.url or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            all_docs.append(doc)

    selected, used_backfill = _select_with_backfill(
        docs=all_docs,
        excluded_urls=excluded_urls,
        target_count=args.target_count,
        previous_docs=previous_output_docs,
    )
    if len(selected) < args.target_count and not args.allow_shortfall:
        raise ValueError(
            "Unable to collect enough fresh recipes. "
            f"needed={args.target_count} got={len(selected)} total_fetched={len(all_docs)} "
            f"excluded_from_last_week={len(excluded_urls)}"
        )

    # Snapshot current output after a successful refresh decision.
    if output_path.exists():
        last_week_path.write_text(output_path.read_text())

    fixture = _docs_to_fixture(selected)
    output_path.write_text(json.dumps(fixture, indent=2))
    print(
        json.dumps(
            {
                "status": "ok",
                "mode": args.mode,
                "output": str(output_path),
                "last_week": str(last_week_path),
                "target_count": args.target_count,
                "written": len(fixture),
                "excluded_from_last_week": len(excluded_urls),
                "used_backfill_from_excluded": bool(used_backfill),
                "adapter_stats_by_batch": stats_by_batch,
                "allow_shortfall": bool(args.allow_shortfall),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
