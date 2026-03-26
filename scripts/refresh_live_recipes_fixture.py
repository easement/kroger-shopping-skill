from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.ad_capture import SaleItem
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
        }
        for doc in docs
    ]


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
        "pork tenderloin",
    )
    return tuple((SaleItem(name=name, price_text="N/A", category="seed"),) for name in names)


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
) -> tuple[list[RecipeDocument], bool]:
    selected = _select_fresh_docs(docs=docs, excluded_urls=excluded_urls, target_count=target_count)
    if selected:
        return selected, False

    # If strict freshness yields nothing, keep the refresh usable by backfilling
    # from current live docs (still deduped, but ignoring last-week exclusion).
    seen: set[str] = set()
    backfilled: list[RecipeDocument] = []
    for doc in docs:
        url = (doc.url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        backfilled.append(doc)
        if len(backfilled) >= target_count:
            break
    return backfilled, bool(backfilled)


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

    excluded_urls = _load_fixture_urls(last_week_path)
    all_docs: list[RecipeDocument] = []
    seen_urls: set[str] = set()
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
