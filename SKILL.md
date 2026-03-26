---
name: grocery-weekly-menu-skill
description: Builds a weekly grocery-sale-driven meal recommendation set with strict diet and quality constraints. Use when user asks to plan meals from a weekly grocery ad, wants healthy and easy recipes, or asks for top-rated meal ideas tied to sale items. Supports Kroger weekly ad context with default location 01100459, optional location override, and manual fallback when ad capture is blocked or incomplete.
compatibility: Requires web access for ad and recipe lookup. If weekly ad capture fails, requires user-provided sale highlights.
metadata:
  author: grocerySkill
  version: 1.1.0
  category: meal-planning
  tags:
    - grocery-ad
    - meal-planning
    - recipe-ranking
---

# Grocery Weekly Menu Skill

## Purpose
Generate exactly 10 healthy, easy-to-prepare meal recommendations based on current grocery ad sale context, while enforcing strict exclusions and ranking quality.

## Important rules
1. Return exactly 10 meals, not more and not fewer.
2. Exclude any meal that is Asian cuisine.
3. Exclude any meal containing beans or fennel.
4. Only include meals with explicit rating >= 4.0 out of 5 and visible review/vote count.
5. Use weighted ranking that gives more influence to entries with larger vote counts.
6. Enforce diversity across proteins and styles in the final 10.

See `references/scoring-and-filters.md` for filtering and ranking details.
See `references/kroger-ad-capture.md` for weekly ad capture and fallback flow.
See `references/test-prompts.md` for trigger tests and validation checklist.
See `references/calibration-pack.md` for weekly regression and quality checks.
See `references/version-history.md` for release notes and tuning traceability.

## Workflow

### Step 1: Capture ad context
1. Use Kroger weekly ad context first.
2. Default to location `01100459` unless user provides an override.
3. Attempt browser/web capture of sale items and notable price promotions.
4. If blocked or incomplete, request manual sale highlights from the user and continue.

### Step 2: Build candidate recipe pool
1. Use sale items as ingredient anchors.
2. Search trusted recipe sources first.
3. Expand to broader sources only if needed to reach strong candidate coverage.
4. Keep only recipes with explicit rating and vote count metadata.

### Step 3: Apply hard constraints
1. Enforce healthy and easy preparation heuristics.
2. Remove any recipe matching excluded cuisine or ingredients.
3. Remove any recipe below rating threshold or missing vote count evidence.

### Step 4: Score and rank
1. Compute weighted confidence score based on rating and vote count.
2. Prefer candidates with strong rating and larger evidence volume.
3. Resolve ties by prep simplicity and sale-item relevance.

### Step 5: Enforce diversity and finalize
1. Ensure variety across proteins and styles.
2. Avoid over-concentration in one cuisine/protein cluster.
3. Return the top 10 that satisfy all constraints.

## Output format
For each of the 10 meals, include:
- Meal title
- Source URL
- Rating and vote count
- Prep difficulty/time signal
- Sale-item match explanation
- Cuisine/protein tag
- Compliance note: non-Asian and no beans/fennel

## Failure handling
- If ad context cannot be fetched: ask for manual sale highlights and continue.
- If candidates are too sparse after constraints: broaden source search while keeping hard exclusions.
- If rating metadata is missing: discard the entry.

## Weekly Refresh + Markdown Output
When user asks to refresh this week’s plan, run:
`python3 -m scripts.refresh_live_deals_fixture && python3 -m scripts.refresh_live_recipes_fixture --mode playwright --target-count 100 --allow-shortfall && python3 -m scripts.run_weekly_plan --ad-mode fixture --ad-fixture fixtures/ad.live.from-deals.json --search-mode fixture --recipe-fixture fixtures/recipes.live.json --target-count 10 --quality-gate --output-format meal-markdown`
Then return the markdown meal list output.
