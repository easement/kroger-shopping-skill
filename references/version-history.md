# Version History

## 1.1.0
- Added maintenance guidance for weekly calibration and regression checks
- Added `references/calibration-pack.md` for repeatable quality validation
- Added direct links in `SKILL.md` to versioning and calibration references

## 1.0.0
- Initial release of `grocery-weekly-menu-skill`
- Added core workflow for Kroger ad context, search, filtering, scoring, diversity, and output formatting
- Added hard constraints:
  - non-Asian cuisine only
  - no beans
  - no fennel
  - rating >= 4.0 with explicit vote count
- Added required fallback from ad capture to manual sale-item input
- Added testing references:
  - trigger tests
  - functional checks
  - fallback checks
