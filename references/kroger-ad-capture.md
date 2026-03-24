# Kroger Weekly Ad Capture

## Objective
Collect weekly sale context from Kroger to anchor meal recommendations to discounted items.

## Default location behavior
- Default location ID: `01100459`
- Allow user override when they provide another location.

## Cookie context
Kroger ad behavior may depend on `x-active-modality`.
Example value pattern:
`{"type":"PICKUP","locationId":"01100459","source":"FALLBACK_ACTIVE_MODALITY_COOKIE","createdDate":1774358019738}`

Treat this as location-context guidance for capture attempts.

## Capture workflow
1. Attempt browser/web retrieval of weekly ad data.
2. Extract sale anchors:
   - product names
   - promo prices
   - relevant protein/produce staples
3. Normalize item names for recipe search anchors.

## Fallback workflow (required)
If ad capture is blocked or incomplete:
1. Ask user for manual highlights from the current weekly ad.
2. Request at minimum:
   - major proteins on sale
   - produce on sale
   - notable pantry specials
3. Continue recipe discovery using provided sale anchors.

## Reliability notes
- Weekly ad structures can change and break extraction.
- Session/cookie context may limit content access.
- Fallback path should always keep the workflow unblocked.
