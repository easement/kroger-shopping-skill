# Grocery Weekly Menu Skill

Generate a weekly set of 10 healthy/easy meals from Kroger sale context with diversity, quality gates, and markdown/JSON output.

## What It Does

- Enforces filters: no Asian cuisine, no beans, no fennel
- Requires rated recipes (`>=4.0`) with vote-weighted scoring
- Balances diversity across proteins, cuisines, and source domains
- Supports fixture, web, and Playwright-backed recipe/ad modes
- Fetches Kroger weekly ads through a DACS-first Playwright path that avoids relying on visible page rendering
- Keeps curated quick-recipe coverage for recurring sale proteins like ground beef, shrimp, pork shoulder, ribs, sausage, and chicken wings
- Produces JSON, plain meal lines, or markdown meal links

## Setup

From `grocery-weekly-menu-skill/`:

```bash
./scripts/setup.sh
```

Manual equivalent:

```bash
npm install
npx playwright install chromium
python3 -m unittest discover -s tests -p "test_*.py"
```

## Weekly Workflow (Recommended)

Run live Kroger ad capture with the persistent browser profile and the current live recipe fixture:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode playwright \
  --kroger-browser-profile-dir .kroger-browser-profile \
  --kroger-browser-channel chrome \
  --search-mode fixture \
  --recipe-fixture fixtures/recipes.live.json \
  --target-count 10 \
  --quality-gate \
  --output-format meal-markdown
```

Refresh recipe coverage when you want to rotate or expand the live recipe fixture:

```bash
python3 -m scripts.refresh_live_recipes_fixture \
  --mode playwright \
  --target-count 100 \
  --allow-shortfall
```

Manual ad-fixture refresh is still available for replay/debugging if you export Kroger JSON to `fixtures/live-deals.json`:

```bash
python3 -m scripts.refresh_live_deals_fixture
```

## Core Commands

Run planner from sample fixtures:

```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10
```

Switch output format:

```bash
--output-format json
--output-format meal-lines
--output-format meal-markdown
```

Web mode with fixture fallback:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode web \
  --search-mode web \
  --web-fallback-to-fixture \
  --recipe-fixture fixtures/recipes.sample.json \
  --manual-fallback-fixture fixtures/ad.sample.json \
  --target-count 10
```

Browser-assisted Kroger capture from a persistent profile:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode playwright \
  --kroger-browser-profile-dir .kroger-browser-profile \
  --kroger-browser-channel chrome \
  --search-mode fixture \
  --recipe-fixture fixtures/recipes.live.json \
  --target-count 10 \
  --quality-gate \
  --output-format meal-markdown
```

Validate inputs only:

```bash
python3 -m scripts.run_weekly_plan --validate-only --search-mode fixture --recipe-fixture fixtures/recipes.sample.json --ad-fixture fixtures/ad.sample.json
```

## Building for Claude Desktop

Create a zip for upload to Claude Desktop (excludes `node_modules/`, `.git/`, `runs/`, and `.DS_Store`):

```bash
zip -r ~/Desktop/grocery-weekly-menu-skill.zip . -x "node_modules/*" -x ".git/*" -x ".DS_Store" -x "scripts/.DS_Store" -x "tests/.DS_Store" -x "runs/*"
```

## Docs

- Detailed implementation + debugging guide: `docs/DEVELOPMENT.md`
- Skill behavior and prompt contract: `SKILL.md`
- Prompt QA scenarios: `references/test-prompts.md`

## Configuration Notes

- Default location id is `01100459` (override with `--location-id`)
- Keep `fixtures/kroger_extra_headers.live.json` local only; use `fixtures/kroger_extra_headers.template.json` as the safe starter
- `--search-mode fixture` requires `--recipe-fixture`
- `scripts.recipe_coverage` is intentionally checked in as stable coverage for recurring weekly-ad proteins that web search may under-fill
- `.kroger-browser-profile/` stores local browser session state and is ignored by git
