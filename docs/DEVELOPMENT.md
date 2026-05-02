# Development Guide

This doc contains implementation details that are intentionally kept out of the main `README.md`.

## End-to-End Code Flow

```mermaid
flowchart TD
    A[run_weekly_plan.py --ad-mode playwright] --> B[DACS-first Kroger capture]
    B --> C[Structured weekly ad offers]
    D[recipe_coverage.py] --> E[fixtures/recipes.live.json]
    F[refresh_live_recipes_fixture.py] --> E
    C --> G[Candidate build + sale matching]
    E --> G
    G --> H[Eligibility filters]
    H --> I[Score + diversity]
    I --> J[json / meal-lines / meal-markdown]
```

## Script Responsibilities

- `scripts.refresh_live_deals_fixture.py`
  - converts browser-exported Kroger deals JSON into normalized ad fixture data
  - writes `fixtures/ad.live.from-deals.json`
  - rejects expired live-deals payloads so stale ads do not silently feed planning

- `scripts.refresh_live_recipes_fixture.py`
  - fetches recipe pages (`web` or `playwright` mode)
  - parses JSON-LD recipe payloads
  - prepends stable coverage docs from `scripts.recipe_coverage`
  - excludes URLs from `fixtures/recipes.last-week.json`
  - does not exclude curated coverage URLs during weekly rotation
  - writes `fixtures/recipes.live.json`

- `scripts.recipe_coverage.py`
  - contains curated quick recipes for recurring sale anchors that live search often under-fills
  - currently covers ground beef, shrimp, pork butt/shoulder, ribs, sausage, and chicken wings
  - keeps coverage within planner constraints (`rating >= 4.0`, positive votes, `prep_minutes <= 45`)

- `scripts.run_weekly_plan.py`
  - loads fixture or live adapters for ad + recipe inputs
  - maps recipe docs to candidates (`documents_to_candidates`)
  - applies eligibility, scoring, and diversity
  - emits `json`, `meal-lines`, or `meal-markdown`

- `scripts.kroger_web_capture.py`
  - uses Playwright's browser session for Kroger capture
  - fetches `digitalads/v1/circulars` with `filter.div` before relying on page rendering
  - prefers the weekly print DACS circular, then parses page-level offer payloads
  - falls back through intercepted API responses, shoppable deals, HTML parsing, and heuristics

## Data Shapes

- Ad fixture item:
  - `{ "name": "...", "price_text": "...", "category": "..." }`

- Recipe fixture item:
  - `{ "title","url","cuisine","protein","ingredients","rating","vote_count","prep_minutes","healthy" }`

- Planner output item:
  - `{ "title","url","rating","vote_count","score","cuisine","protein","sale_item_matches" }`

## Troubleshooting

- live headless ad capture returns promo cards only:
  - check that `--ad-mode playwright` is being used with `--kroger-browser-profile-dir .kroger-browser-profile`
  - DACS-first capture should report `parsed_from_api_items` in ad debug stats
  - if `parsed_from_api_items=0`, verify Kroger is returning `digitalads/v1/circulars` for the division implied by `--location-id`

- `quality_gate_failed:selected_meals(...)<required(10)` after ad capture succeeds:
  - inspect `[summary] Candidate counts`; if `eligible` is high but `selected` is low, diversity caps are probably working as intended
  - add coverage in `scripts.recipe_coverage.py` for recurring sale anchors rather than relaxing planner constraints
  - run `python3 -m unittest tests.test_recipe_coverage` after changing coverage docs

- `written=0` on recipe refresh:
  - no recipe docs were accepted for this run
  - check Playwright install:
  - `npm install playwright && npx playwright install chromium`
  - rerun with:
  - `python3 -m scripts.refresh_live_recipes_fixture --mode playwright --target-count 100 --allow-shortfall`

- `used_backfill_from_excluded=true`:
  - strict novelty filter (exclude last week) removed all candidates
  - script backfilled from available docs to avoid empty fixture

- low recipe count:
  - keep `--allow-shortfall` enabled so planner can continue
  - retry later or on a different network when domains are unstable

Compact healthy refresh example:

```json
{
  "status": "ok",
  "mode": "playwright",
  "target_count": 100,
  "written": 72,
  "excluded_from_last_week": 24,
  "used_backfill_from_excluded": false,
  "allow_shortfall": true
}
```

Compact healthy live-capture stats example:

```json
{
  "ad_source": "kroger-playwright",
  "meal_count": 10,
  "adapter_stats": {
    "ad": {
      "api_endpoints_attempted": 16,
      "parsed_from_api_items": 185
    }
  }
}
```

## Useful Dev Commands

Run full tests:

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

Record HTTP captures for diagnostics:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode web \
  --search-mode web \
  --web-fallback-to-fixture \
  --recipe-fixture fixtures/recipes.sample.json \
  --manual-fallback-fixture fixtures/ad.sample.json \
  --record-http-dir runs/http-captures \
  --record-metadata \
  --target-count 10
```

Run live DACS-backed weekly plan:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode playwright \
  --kroger-browser-profile-dir .kroger-browser-profile \
  --kroger-browser-channel chrome \
  --search-mode fixture \
  --recipe-fixture fixtures/recipes.live.json \
  --target-count 10 \
  --quality-gate \
  --pretty \
  --pretty-summary \
  --output-format meal-markdown
```
