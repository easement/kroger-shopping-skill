# Grocery Weekly Menu Skill

Generate a weekly set of 10 healthy/easy meals from Kroger sale context, with a bonus healthy-recipe section, diversity controls, quality gates, and markdown/JSON output.

## What It Does

- Fetches the live Kroger weekly ad via Playwright and maps sale items to recipe candidates
- Searches for fresh recipes using the **Brave Search API** (falls back to Bing RSS when no key is set)
- Prioritises **Serious Eats** as a highly-weighted editorial source — recipes are ranked by a fixed high score regardless of vote counts, capped at 3 per week
- Produces **10 main meals** balanced across proteins, cuisines, and source domains
- Produces a bonus **Healthy Options section** (up to 5 recipes) sourced from eatingwell.com, skinnytaste.com, minimalistbaker.com, and cookieandkate.com — collected during the same search run, no extra API calls
- Enforces filters: no Asian cuisine, no beans or fennel in ingredients, healthy + easy prep (≤ 45 min)
- Requires rated recipes (`≥ 4.0`) with vote-weighted scoring for all sites except Serious Eats
- Keeps curated quick-recipe coverage for recurring sale proteins (ground beef, shrimp, pork shoulder, ribs, sausage, chicken wings) as a backfill pool
- Produces JSON, plain meal lines, or markdown meal links

## Environment Variables

Copy `.env.example` to `.env` (gitignored) and fill in your values. Every variable can also be passed as a CLI flag — the env var is the fallback.

| Variable | CLI flag | Required | Description |
|---|---|---|---|
| `BRAVE_API_KEY` | `--brave-api-key` | No | [Brave Search API](https://api.search.brave.com) key. Free tier: 2,000 queries/month. Without a key, recipe search falls back to Bing RSS. |
| `KROGER_COOKIE` | `--kroger-cookie` | For live ads | Raw `Cookie` header from browser DevTools while logged into kroger.com. |
| `KROGER_CIRCULAR_ID` | `--kroger-circular-id` | No | Weekly circular UUID; auto-detected when absent. |
| `KROGER_BROWSER_PROFILE_DIR` | `--kroger-browser-profile-dir` | No | Persistent Chromium profile path for session-assisted Kroger capture. |
| `KROGER_BROWSER_CHANNEL` | `--kroger-browser-channel` | No | Playwright browser channel, e.g. `chrome`. |

## Setup

From `grocery-weekly-menu-skill/`:

```bash
./scripts/setup.sh
```

Manual equivalent:

```bash
pip3 install python-dotenv
npm install
npx playwright install chromium
python3 -m unittest discover -s tests -p "test_*.py"
```

## Weekly Workflow (Recommended)

Fetch the live Kroger ad and search for fresh recipes via Brave — produces both the main 10 meals and the Healthy Options section:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode playwright \
  --search-mode web \
  --planner-config config/planner_config.json \
  --output-format meal-markdown \
  --pretty-summary \
  --save-run
```

If web search finds too few recipes, add a fixture fallback:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode playwright \
  --search-mode web \
  --web-fallback-to-fixture \
  --recipe-fixture fixtures/recipes.live.json \
  --planner-config config/planner_config.json \
  --output-format meal-markdown \
  --pretty-summary
```

Refresh the live recipe pool (rotates out last week's picks, backfills with curated coverage):

```bash
python3 -m scripts.refresh_live_recipes_fixture \
  --mode playwright \
  --target-count 100 \
  --allow-shortfall
```

Manual ad-fixture refresh for replay/debugging (export Kroger JSON to `fixtures/live-deals.json` first):

```bash
python3 -m scripts.refresh_live_deals_fixture
```

## Core Commands

Run planner from sample fixtures (no live network calls):

```bash
python3 -m scripts.run_weekly_plan \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json \
  --target-count 10
```

Switch output format:

```bash
--output-format json          # full structured output including healthy_meals array
--output-format meal-lines    # plain text, one recipe per two lines
--output-format meal-markdown # markdown links with Healthy Options section appended
```

Browser-assisted Kroger capture from a persistent profile:

```bash
python3 -m scripts.run_weekly_plan \
  --ad-mode playwright \
  --kroger-browser-profile-dir .kroger-browser-profile \
  --kroger-browser-channel chrome \
  --search-mode web \
  --planner-config config/planner_config.json \
  --output-format meal-markdown \
  --quality-gate
```

Validate fixture inputs only (no planning):

```bash
python3 -m scripts.run_weekly_plan \
  --validate-only \
  --search-mode fixture \
  --recipe-fixture fixtures/recipes.sample.json \
  --ad-fixture fixtures/ad.sample.json
```

## Recipe Search Backends

| Backend | How to activate | Free quota | Notes |
|---|---|---|---|
| Brave Search API | Set `BRAVE_API_KEY` | 2,000 queries/month | Recommended. Correctly honours `site:` filtering. |
| Bing RSS | No key set | Unlimited (degraded) | `site:` operator unreliable; most links rejected. |

The search backend is shown in the progress output: `Recipe search mode: web (max_links=20, backend=brave)`.

## Recipe Scoring & Source Weighting

| Site | Treatment |
|---|---|
| **seriouseats.com** | Fixed base score of `3.0` — bypasses vote-weighted formula and minimum-rating/vote eligibility filters. Capped at 3 recipes per week. |
| eatingwell.com, skinnytaste.com, minimalistbaker.com, cookieandkate.com | Always included in every search run; queries prefixed with `"healthy"`. Results feed the **Healthy Options** section. |
| All other trusted sites | Standard `normalizedRating × log10(votes+1)` scoring with +0.05 trusted-source boost. |

See `references/scoring-and-filters.md` for the full formula.

## Output Format

### Main meals (10)

```
- [Protein - Title(site - rating) - price](url)
```

### Healthy Options (up to 5, appended)

```
### Healthy Options
- [Protein - Title(site - rating) - price](url)
```

### JSON keys (additional vs. previous)

- `healthy_meal_count` — integer
- `healthy_meals` — array of `{title, url, rating, vote_count, score, source_domain, protein, sale_item_matches}`

## Docs

- Detailed implementation + debugging guide: `docs/DEVELOPMENT.md`
- Skill behaviour and prompt contract: `SKILL.md`
- Scoring formula and filter reference: `references/scoring-and-filters.md`
- Prompt QA scenarios: `references/test-prompts.md`

## Configuration Notes

- Default location id is `01100459` (override with `--location-id`)
- Keep `fixtures/kroger_extra_headers.live.json` local only; use `fixtures/kroger_extra_headers.template.json` as the safe starter
- `--search-mode fixture` requires `--recipe-fixture`
- `scripts.recipe_coverage` is intentionally checked in as stable coverage for recurring weekly-ad proteins that web search may under-fill
- `.kroger-browser-profile/` stores local browser session state and is gitignored
- `.env` is gitignored — never commit it. Use `.env.example` as the template.

## Building for Claude Desktop

Create a zip for upload to Claude Desktop (excludes `node_modules/`, `.git/`, `runs/`, and `.DS_Store`):

```bash
zip -r ~/Desktop/grocery-weekly-menu-skill.zip . \
  -x "node_modules/*" -x ".git/*" -x ".DS_Store" \
  -x "scripts/.DS_Store" -x "tests/.DS_Store" -x "runs/*"
```
