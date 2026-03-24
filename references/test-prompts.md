# Test Prompts and Validation Rubric

## Trigger tests

### Should trigger
1. "Plan 10 healthy weeknight meals from this week's Kroger ad."
2. "Use Kroger sales to suggest easy dinner recipes rated 4+ stars."
3. "Build a weekly sale-based menu with chicken, beef, and pork variety."

### Should not trigger
1. "What is the weather this week?"
2. "Help me write a resume."
3. "Create a generic shopping list with no recipe recommendations."

## Functional tests
For each run, verify:
1. Exactly 10 meals returned.
2. Every meal has rating >= 4.0 and explicit vote count.
3. No meal is Asian cuisine.
4. No meal contains beans or fennel.
5. Meals are healthy and easy by stated heuristics.
6. Diversity is present across proteins/styles.
7. Each meal includes sale-match explanation.

## Fallback tests
1. Simulate failed ad capture and verify user is asked for manual ad highlights.
2. Provide manual highlights and verify workflow continues to 10 valid meals.
3. Verify output quality remains compliant in fallback mode.

## Pass/fail rubric
Pass only if all checks are true:
- Trigger behavior is correct on both positive and negative prompts.
- All hard filters are satisfied across all 10 meals.
- Rating and vote metadata is present for every recommendation.
- Diversity rule is visibly enforced.
- Fallback flow works end-to-end without blocking.

Fail on any single violation and revise:
- frontmatter description if trigger quality fails
- filtering instructions if constraints fail
- ranking guidance if quality/variety degrades
