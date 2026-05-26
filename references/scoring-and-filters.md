# Scoring and Filters

## Hard eligibility filters
Apply these before scoring:
1. Rating must be at least 4.0 out of 5.
2. Recipe must show explicit vote/review count.
3. Exclude Asian cuisine.
4. Exclude recipes containing beans.
5. Exclude recipes containing fennel.
6. Recipe should be healthy and easy to prepare.

If any required field is missing, discard the candidate.

## Healthy and easy heuristics
Use practical heuristics:
- Healthy signal examples: lean proteins, vegetables, balanced plate composition, moderate saturated fat methods.
- Easy signal examples: limited ingredient complexity, straightforward steps, practical weeknight prep time.
- Prefer recipes with clear timing and method sections.

If uncertain, prefer simpler and more balanced options.

## Source prioritization
1. Start with trusted recipe publishers.
2. If coverage is insufficient, add additional sources with explicit rating and vote count.
3. Never include entries without rating evidence.

## Serious Eats special treatment
Serious Eats (`seriouseats.com`) is treated as a highly preferred editorial source:
- **Eligibility**: Skip the minimum rating and vote-count filters entirely. A Serious Eats recipe is eligible regardless of its rating or vote count (other filters such as cuisine exclusions, ingredient exclusions, and prep time still apply).
- **Scoring**: Use a fixed base score of `3.0` (approximately the score of a very highly rated, high-volume recipe) instead of the standard `normalizedRating × voteWeight` formula. Sale, ease, trusted-source, and confidence boosts are still applied on top.
- **Cap**: No more than 3 Serious Eats recipes may appear per weekly menu (enforced by the standard per-domain cap).

## Weighted ranking model
Use a vote-aware score so high-volume ratings carry more confidence.

Suggested formula:
- `normalizedRating = clamp((rating - 4.0) / 1.0, 0, 1)`
- `voteWeight = log10(voteCount + 1)`
- `confidenceScore = normalizedRating * voteWeight`

Then apply tie-breakers:
1. Better sale-item alignment
2. Easier prep profile
3. Higher trusted-source priority

## Diversity requirements across 10 meals
Enforce distribution across proteins/styles:
- Include a mix such as chicken, beef, pork, and at least two cuisine-style families.
- Avoid repeating near-identical meal profiles.
- Do not allow one cuisine or one protein to dominate the set.

If diversity is weak, swap lower-ranked duplicates for the next eligible diverse candidate.
