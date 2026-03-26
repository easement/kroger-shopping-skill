# Grocery Weekly Menu Skill

## Quick Start

Run these from `grocery-weekly-menu-skill/`:

1. Run tests
```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

2. Run standard JSON output
```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10
```

3. Run email/doc-friendly meal list
```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10 \
  --output-format meal-lines
```

4. Run markdown clickable links
```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10 \
  --output-format meal-markdown
```

5. Run preflight validation only
```bash
python3 -m scripts.run_weekly_plan \
  --validate-only \
  --search-mode fixture \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json
```

6. Run with quality gate checks
```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10 \
  --quality-gate
```

7. Replay parser checks from recorded captures
```bash
python3 -m scripts.run_weekly_plan \
  --replay-captures-dir runs/http-captures
```

8. Refresh ad fixture from a browser-exported `live-deals.json`
```bash
python3 -m scripts.refresh_live_deals_fixture
```

8b. Prepare local Kroger extra headers from template (optional for web ad mode)
```bash
cp fixtures/kroger_extra_headers.template.json fixtures/kroger_extra_headers.live.json
# edit fixtures/kroger_extra_headers.live.json with current browser-captured values
```

9. Refresh 100 live recipes and exclude last week's URLs
```bash
python3 -m scripts.refresh_live_recipes_fixture --mode playwright --target-count 100
```

If weekly site conditions return fewer than 100, allow a shortfall instead of failing:

```bash
python3 -m scripts.refresh_live_recipes_fixture --mode playwright --target-count 100 --allow-shortfall
```

`refresh_live_recipes_fixture` output now includes:
- `written`: number of recipes saved
- `excluded_from_last_week`: count of URLs excluded
- `used_backfill_from_excluded`: `true` when strict exclusion produced zero and script backfilled from current live docs
- `adapter_stats_by_batch`: per-seed diagnostics for troubleshooting

This project builds a Claude/Cursor-compatible skill workflow that generates a weekly set of 10 meal recommendations from grocery sale context.

The current implementation includes:
- rule-based filtering (healthy + easy recipes)
- exclusions (no Asian cuisine, no beans, no fennel)
- weighted ranking (higher review volume carries more confidence)
- diversity balancing across proteins/styles
- Kroger weekly ad capture support with fallback paths
- multiple output formats for JSON, plain text, and markdown links

## Current Progress Snapshot

- Live Kroger HTTP capture can be network-sensitive; reliable weekly flow is to export `shoppable-weekly-deals` JSON from browser DevTools.
- Use `scripts.refresh_live_deals_fixture.py` to convert exported live deals into `fixtures/ad.live.from-deals.json`.
- `fixtures/kroger_extra_headers.template.json` is a sanitized starting point for local header capture; keep populated `*.live.json` files local only.
- Live recipe refresh supports Playwright browser fetches and multi-seed discovery (including pork/beef/turkey/ham/pasta/seafood).
- Recipe refresh writes `fixtures/recipes.live.json`, excludes last-week URLs from `fixtures/recipes.last-week.json`, and can backfill when novelty is exhausted.
- Each recipe search run randomly samples 7 trusted domains (non-persistent); selected domains are reported in `adapter_stats.recipe_web.selected_domains`.
- Planner can then run against current weekly deals/recipes using fixture mode for stable weekly execution.
- Web/Playwright recipe search reports detailed diagnostics (`adapter_stats.recipe_web`) including page fetch failures and parse outcomes.
- Trusted recipe domains now include additional sources such as Pinch of Yum, Cookie and Kate, Love and Lemons, Serious Eats, Budget Bytes, Smitten Kitchen, Minimalist Baker, Half Baked Harvest, Sally's Baking Addiction, Damn Delicious, The Pioneer Woman, Skinnytaste, Simply Recipes, Gimme Some Oven, Natasha's Kitchen, Jo Cooks, and Food52.

## Project Structure

- `todo.md` - working checklist and implementation progress
- `grocery-weekly-menu-skill/SKILL.md` - skill instructions/frontmatter
- `grocery-weekly-menu-skill/references/` - policy docs, calibration, and tests
- `grocery-weekly-menu-skill/scripts/` - runnable pipeline and adapters
- `grocery-weekly-menu-skill/tests/` - unit/integration tests
- `grocery-weekly-menu-skill/fixtures/` - sample ad/recipe fixture data

## Prerequisites

- Python 3.10+ (the project currently runs with `python3`)
- Cursor installed
- Node.js + npm (required for Playwright/browser-backed modes)

## Setup

From `grocery-weekly-menu-skill/`, run:

```bash
./scripts/setup.sh
```

This setup script:
- validates Python/Node/npm availability
- installs npm dependencies
- installs Playwright Chromium browser binaries
- verifies Playwright import
- runs the Python test suite

Manual equivalent:

```bash
npm install
npx playwright install chromium
python3 -m unittest discover -s tests -p "test_*.py"
```

## Install and Run in Cursor

1. Open the project folder in Cursor:
   - `$HOME/Projects/grocerySkill`
2. Open Cursor terminal at:
   - `$HOME/Projects/grocerySkill/grocery-weekly-menu-skill`
3. Run tests:
   - `python3 -m unittest discover -s tests -p "test_*.py"`
4. Run the planner with fixture data:
   - `python3 -m scripts.run_weekly_plan --recipe-fixture fixtures/recipes.sample.json --ad-fixture fixtures/ad.sample.json --target-count 10`

## Usage

### 1) Standard JSON output

```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10
```

### 2) Progress logs + summary diagnostics

```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10 \
  --pretty \
  --pretty-summary
```

### 3) Copy/paste meal list for email/docs

Plain text lines:

```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10 \
  --output-format meal-lines
```

Markdown clickable links:

```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10 \
  --output-format meal-markdown
```

### 4) Web mode with fixture fallback

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode web \
  --search-mode web \
  --web-fallback-to-fixture \
  --recipe-fixture fixtures/recipes.sample.json \
  --manual-fallback-fixture fixtures/ad.sample.json \
  --target-count 10 \
  --pretty \
  --pretty-summary
```

Optional header file in web ad mode (local only):

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode web \
  --search-mode web \
  --kroger-extra-headers-file fixtures/kroger_extra_headers.live.json \
  --web-fallback-to-fixture \
  --recipe-fixture fixtures/recipes.sample.json \
  --manual-fallback-fixture fixtures/ad.sample.json \
  --target-count 10
```

### 4b) Playwright recipe mode (browser-backed recipe fetch)

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode fixture \
  --ad-fixture fixtures/ad.live.from-deals.json \
  --search-mode playwright \
  --web-fallback-to-fixture \
  --recipe-fixture fixtures/recipes.sample.json \
  --target-count 10 \
  --web-max-links 15 \
  --pretty \
  --pretty-summary
```

If needed, install Playwright once:

```bash
npm install playwright
npx playwright install chromium
```

### 5) Record HTTP payloads and metadata for debugging

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

### 6) Start-up script (manual ad refresh + planner run)

Use this as a weekly kickoff command from repo root:

```bash
python3 -m scripts.refresh_live_deals_fixture && \
python3 -m scripts.refresh_live_recipes_fixture --mode playwright --target-count 100 --allow-shortfall && \
python3 -m scripts.run_weekly_plan \
  --ad-mode fixture \
  --ad-fixture fixtures/ad.live.from-deals.json \
  --search-mode fixture \
  --recipe-fixture fixtures/recipes.live.json \
  --target-count 10 \
  --web-max-links 15 \
  --pretty-summary \
  --quality-gate \
  --output-format json
```

This keeps ad input up to date from your browser-exported weekly deals and refreshes a 100-item live recipe fixture with last-week exclusion and safe backfill when needed.

### Troubleshooting (Recipe Refresh)

- `written=0`
  - Meaning: no recipes were saved to `fixtures/recipes.live.json`.
  - Typical cause: live fetch returned no usable recipe docs for current network/site conditions.
  - Fixes:
    - rerun with Playwright mode: `python3 -m scripts.refresh_live_recipes_fixture --mode playwright --target-count 100 --allow-shortfall`
    - verify Playwright install: `npm install playwright && npx playwright install chromium`
    - retry later or on a different network if sites are returning 403/timeouts

- `used_backfill_from_excluded=true`
  - Meaning: strict "exclude last week URLs" produced zero candidates, so script reused currently fetched URLs to avoid an empty fixture.
  - Typical cause: small or repetitive live result pool this week.
  - Fixes:
    - keep this behavior for continuity (safe default)
    - increase discovery breadth: raise `--max-links`
    - rotate/expand seed terms in `scripts/refresh_live_recipes_fixture.py`

- Common quick checks
  - Inspect refresh output: `written`, `excluded_from_last_week`, `used_backfill_from_excluded`, and `adapter_stats_by_batch`.
  - If `written` is low, run with `--allow-shortfall` so planner can still proceed.
  - If repeated 403 behavior appears in stats, prefer Playwright mode over web mode.
- Do not commit populated `fixtures/kroger_extra_headers.live.json`; use the template file and keep live values local.

Expected healthy output example (compact):

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

## Changing the Default Location Value

There are two ways to set location:

1. Per run (recommended)
   - Use `--location-id` in the CLI:
   - `python3 -m scripts.run_weekly_plan --location-id 01100459 ...`

2. Global default in code
   - Edit `DEFAULT_LOCATION_ID` in:
   - `grocery-weekly-menu-skill/scripts/ad_capture.py`
   - Current value is `01100459`

If you update the global default, all runs that do not pass `--location-id` will use the new value.

## Notes

- `--search-mode fixture` requires `--recipe-fixture`
- In web mode, live results can vary; use `--web-fallback-to-fixture` for reliability
- For ad failures, provide `--manual-fallback-fixture` (or manual fallback input in future UX flows)
