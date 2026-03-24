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

This project builds a Claude/Cursor-compatible skill workflow that generates a weekly set of 10 meal recommendations from grocery sale context.

The current implementation includes:
- rule-based filtering (healthy + easy recipes)
- exclusions (no Asian cuisine, no beans, no fennel)
- weighted ranking (higher review volume carries more confidence)
- diversity balancing across proteins/styles
- Kroger weekly ad capture support with fallback paths
- multiple output formats for JSON, plain text, and markdown links

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
