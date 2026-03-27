# Grocery Weekly Menu Skill

Generate a weekly set of 10 healthy/easy meals from Kroger sale context with diversity, quality gates, and markdown/JSON output.

## What It Does

- Enforces filters: no Asian cuisine, no beans, no fennel
- Requires rated recipes (`>=4.0`) with vote-weighted scoring
- Balances diversity across proteins, cuisines, and source domains
- Supports fixture, web, and Playwright-backed recipe/ad modes
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

1) Export Kroger `shoppable-weekly-deals` JSON from browser DevTools to `fixtures/live-deals.json`

2) Run weekly refresh + markdown output:

```bash
python3 -m scripts.refresh_live_deals_fixture && \
python3 -m scripts.refresh_live_recipes_fixture --mode playwright --target-count 100 --allow-shortfall && \
python3 -m scripts.run_weekly_plan \
  --ad-mode fixture \
  --ad-fixture fixtures/ad.live.from-deals.json \
  --search-mode fixture \
  --recipe-fixture fixtures/recipes.live.json \
  --target-count 10 \
  --quality-gate \
  --output-format meal-markdown
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

Validate inputs only:

```bash
python3 -m scripts.run_weekly_plan --validate-only --search-mode fixture --recipe-fixture fixtures/recipes.sample.json --ad-fixture fixtures/ad.sample.json
```

## Docs

- Detailed implementation + debugging guide: `docs/DEVELOPMENT.md`
- Skill behavior and prompt contract: `SKILL.md`
- Prompt QA scenarios: `references/test-prompts.md`

## Configuration Notes

- Default location id is `01100459` (override with `--location-id`)
- Keep `fixtures/kroger_extra_headers.live.json` local only; use `fixtures/kroger_extra_headers.template.json` as the safe starter
- `--search-mode fixture` requires `--recipe-fixture`
