# Weekly Calibration Pack

## Purpose
Use this pack before each weekly run to catch quality drift and keep output stable as ad pages and recipe metadata change.

## Quick regression checklist
Run these checks in order:
1. Trigger quality still works for obvious and paraphrased requests
2. Ad capture path still works for default location `01100459`
3. Manual fallback still activates when ad capture is blocked
4. Hard exclusions are always enforced
5. Rating and vote evidence is present for every meal
6. Diversity remains balanced in final 10

## Golden prompts
Use these prompts as weekly regression cases.

### Case 1: Standard weekly run
Prompt:
"Plan 10 healthy and easy dinners from this week's Kroger ad. Exclude Asian food, beans, and fennel. Use highly rated recipes only."

Expected outcomes:
- Exactly 10 meals
- Each meal has rating >= 4.0 with vote count
- Output includes source URL and sale-item rationale

### Case 2: Variety stress test
Prompt:
"Use this week's Kroger deals to build 10 dinners with strong variety across chicken, beef, pork, Italian, and Mexican styles. No Asian dishes, no beans, no fennel."

Expected outcomes:
- No dominant single protein/cuisine cluster
- Variety tags are visible and meaningful

### Case 3: High-confidence ranking
Prompt:
"Pick sale-driven meals where reviews are strongest and give more weight to high vote counts than small sample ratings."

Expected outcomes:
- Top entries reflect both rating quality and vote volume
- Low-vote outliers do not dominate top spots

### Case 4: Fallback path validation
Prompt:
"If Kroger ad fetch fails, ask me for sale highlights and then continue."

Expected outcomes:
- Assistant asks for manual highlights when needed
- Continues workflow and still returns 10 compliant meals

## Weekly sign-off rubric
Mark pass only if all are true:
- Trigger behavior is correct (positive and negative prompts)
- Every meal passes hard filters
- Every meal has explicit rating and vote metadata
- Diversity goals are met across the final set
- Fallback path is operational

If any item fails:
1. Update the relevant guidance doc (`SKILL.md`, `scoring-and-filters.md`, or `kroger-ad-capture.md`)
2. Re-run the failed calibration case
3. Record the update in `version-history.md`
