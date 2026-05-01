from __future__ import annotations

from dataclasses import dataclass
from math import log10
from typing import Iterable


EXCLUDED_INGREDIENT_TOKENS = {
    "bean",
    "beans",
    "black bean",
    "black beans",
    "kidney bean",
    "kidney beans",
    "pinto bean",
    "pinto beans",
    "fennel",
    "fennel bulb",
    "fennel seed",
}

EXCLUDED_CUISINE_TOKENS = {
    "asian",
    "chinese",
    "japanese",
    "korean",
    "thai",
    "vietnamese",
    "indian",
}

TRUSTED_SOURCES = {
    "allrecipes.com",
    "foodnetwork.com",
    "eatingwell.com",
    "delish.com",
    "epicurious.com",
    "pinchofyum.com",
    "cookieandkate.com",
    "loveandlemons.com",
    "seriouseats.com",
    "budgetbytes.com",
    "smittenkitchen.com",
    "minimalistbaker.com",
    "halfbakedharvest.com",
    "sallysbakingaddiction.com",
    "damndelicious.net",
    "thepioneerwoman.com",
    "skinnytaste.com",
    "simplyrecipes.com",
    "gimmesomeoven.com",
    "natashaskitchen.com",
    "jocooks.com",
    "food52.com",
}


@dataclass(frozen=True)
class RecipeCandidate:
    title: str
    url: str
    source_domain: str
    cuisine: str
    protein: str
    ingredients: tuple[str, ...]
    rating: float
    vote_count: int
    prep_minutes: int
    healthy: bool
    sale_item_matches: tuple[str, ...]
    extraction_confidence: float = 1.0


@dataclass(frozen=True)
class RankedRecipe:
    candidate: RecipeCandidate
    score: float
    trusted_source: bool


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str


@dataclass(frozen=True)
class PlannerConfig:
    min_rating: float = 4.0
    max_prep_minutes: int = 45
    max_per_protein: int = 3
    max_per_cuisine: int = 4
    max_per_source_domain: int = 10
    max_foodnetwork_per_protein: int = 2
    min_non_foodnetwork_count: int = 4
    min_trusted_ratio: float = 0.3
    require_sale_item_match: bool = True


@dataclass(frozen=True)
class PlanningDiagnostics:
    total_candidates: int
    eligible_candidates: int
    selected_meals: int
    trusted_selected: int
    trusted_ratio: float
    insufficient_reason: str | None


def _normalize(text: str) -> str:
    return text.strip().lower()


def _has_excluded_ingredient(ingredients: Iterable[str]) -> bool:
    normalized_ingredients = " | ".join(_normalize(item) for item in ingredients)
    return any(token in normalized_ingredients for token in EXCLUDED_INGREDIENT_TOKENS)


def _is_excluded_cuisine(cuisine: str) -> bool:
    normalized_cuisine = _normalize(cuisine)
    return any(token in normalized_cuisine for token in EXCLUDED_CUISINE_TOKENS)


def _is_easy(prep_minutes: int, config: PlannerConfig) -> bool:
    return prep_minutes <= config.max_prep_minutes


def check_eligibility(candidate: RecipeCandidate, config: PlannerConfig | None = None) -> EligibilityResult:
    active_config = config or PlannerConfig()
    if candidate.rating < active_config.min_rating:
        return EligibilityResult(eligible=False, reason="rating_below_threshold")

    if candidate.vote_count <= 0:
        return EligibilityResult(eligible=False, reason="missing_vote_count")

    if not candidate.healthy:
        return EligibilityResult(eligible=False, reason="not_healthy")

    if not _is_easy(candidate.prep_minutes, active_config):
        return EligibilityResult(eligible=False, reason="not_easy")

    if _is_excluded_cuisine(candidate.cuisine):
        return EligibilityResult(eligible=False, reason="excluded_cuisine")

    if _has_excluded_ingredient(candidate.ingredients):
        return EligibilityResult(eligible=False, reason="excluded_ingredient")

    if active_config.require_sale_item_match and not candidate.sale_item_matches:
        return EligibilityResult(eligible=False, reason="missing_sale_item_match")

    return EligibilityResult(eligible=True, reason="eligible")


def is_eligible(candidate: RecipeCandidate) -> bool:
    return check_eligibility(candidate).eligible


def score_candidate(candidate: RecipeCandidate) -> RankedRecipe:
    normalized_rating = max(0.0, min(1.0, (candidate.rating - 4.0) / 1.0))
    vote_weight = log10(candidate.vote_count + 1)
    sale_boost = min(len(candidate.sale_item_matches), 3) * 0.05
    ease_boost = max(0, 45 - candidate.prep_minutes) / 45 * 0.05
    trusted_source = _normalize(candidate.source_domain) in TRUSTED_SOURCES
    trusted_boost = 0.05 if trusted_source else 0.0
    confidence = max(0.0, min(1.0, float(candidate.extraction_confidence)))
    confidence_boost = confidence * 0.03

    score = normalized_rating * vote_weight + sale_boost + ease_boost + trusted_boost + confidence_boost
    return RankedRecipe(candidate=candidate, score=score, trusted_source=trusted_source)


def _sort_ranked(recipes: list[RankedRecipe]) -> list[RankedRecipe]:
    return sorted(
        recipes,
        key=lambda entry: (
            entry.score,
            entry.candidate.vote_count,
            entry.candidate.rating,
            len(entry.candidate.sale_item_matches),
            -entry.candidate.prep_minutes,
        ),
        reverse=True,
    )


def enforce_diversity(
    sorted_ranked: list[RankedRecipe],
    target_count: int = 10,
    config: PlannerConfig | None = None,
) -> list[RankedRecipe]:
    active_config = config or PlannerConfig()
    if target_count <= 0:
        return []

    selected: list[RankedRecipe] = []
    by_protein: dict[str, int] = {}
    by_cuisine: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    by_domain_protein: dict[tuple[str, str], int] = {}
    max_per_protein = active_config.max_per_protein
    max_per_cuisine = active_config.max_per_cuisine
    max_per_domain = active_config.max_per_source_domain
    max_foodnetwork_per_protein = active_config.max_foodnetwork_per_protein

    def can_select(
        protein_key: str,
        cuisine_key: str,
        domain_key: str,
        *,
        enforce_protein_cap: bool,
        enforce_cuisine_cap: bool,
        enforce_domain_cap: bool,
    ) -> bool:
        if enforce_protein_cap and by_protein.get(protein_key, 0) >= max_per_protein:
            return False
        if enforce_cuisine_cap and by_cuisine.get(cuisine_key, 0) >= max_per_cuisine:
            return False
        if enforce_domain_cap and by_domain.get(domain_key, 0) >= max_per_domain:
            return False
        if domain_key == "foodnetwork.com":
            domain_protein_key = (domain_key, protein_key)
            if by_domain_protein.get(domain_protein_key, 0) >= max_foodnetwork_per_protein:
                return False
        return True

    selected_ids: set[str] = set()

    def add_candidates(
        *,
        enforce_protein_cap: bool,
        enforce_cuisine_cap: bool,
        enforce_domain_cap: bool,
    ) -> None:
        for ranked in sorted_ranked:
            if len(selected) >= target_count:
                break
            recipe_url = ranked.candidate.url
            if recipe_url in selected_ids:
                continue
            protein_key = _normalize(ranked.candidate.protein)
            cuisine_key = _normalize(ranked.candidate.cuisine)
            domain_key = _normalize(ranked.candidate.source_domain)
            if not can_select(
                protein_key,
                cuisine_key,
                domain_key,
                enforce_protein_cap=enforce_protein_cap,
                enforce_cuisine_cap=enforce_cuisine_cap,
                enforce_domain_cap=enforce_domain_cap,
            ):
                continue
            selected.append(ranked)
            selected_ids.add(recipe_url)
            by_protein[protein_key] = by_protein.get(protein_key, 0) + 1
            by_cuisine[cuisine_key] = by_cuisine.get(cuisine_key, 0) + 1
            by_domain[domain_key] = by_domain.get(domain_key, 0) + 1
            domain_protein_key = (domain_key, protein_key)
            by_domain_protein[domain_protein_key] = by_domain_protein.get(domain_protein_key, 0) + 1

    # Prefer strong diversity first, then progressively relax caps to fill target_count.
    add_candidates(enforce_protein_cap=True, enforce_cuisine_cap=True, enforce_domain_cap=True)
    add_candidates(enforce_protein_cap=True, enforce_cuisine_cap=False, enforce_domain_cap=True)
    add_candidates(enforce_protein_cap=True, enforce_cuisine_cap=False, enforce_domain_cap=False)
    add_candidates(enforce_protein_cap=False, enforce_cuisine_cap=False, enforce_domain_cap=False)
    selected = _enforce_min_non_foodnetwork_count(
        selected=selected,
        sorted_ranked=sorted_ranked,
        min_count=active_config.min_non_foodnetwork_count,
    )

    return _interleave_by_protein(selected)


def _enforce_min_non_foodnetwork_count(
    *,
    selected: list[RankedRecipe],
    sorted_ranked: list[RankedRecipe],
    min_count: int,
) -> list[RankedRecipe]:
    if min_count <= 0 or not selected:
        return selected

    def is_non_foodnetwork(item: RankedRecipe) -> bool:
        return _normalize(item.candidate.source_domain) != "foodnetwork.com"

    non_fn_count = len([item for item in selected if is_non_foodnetwork(item)])
    if non_fn_count >= min_count:
        return selected

    selected_urls = {item.candidate.url for item in selected}
    non_fn_pool = [
        item
        for item in sorted_ranked
        if item.candidate.url not in selected_urls and is_non_foodnetwork(item)
    ]
    if not non_fn_pool:
        return selected

    foodnetwork_indices = [
        idx for idx, item in enumerate(selected) if _normalize(item.candidate.source_domain) == "foodnetwork.com"
    ]
    replacement_index = 0
    needed = min_count - non_fn_count

    for idx in reversed(foodnetwork_indices):
        if needed <= 0 or replacement_index >= len(non_fn_pool):
            break
        selected[idx] = non_fn_pool[replacement_index]
        replacement_index += 1
        needed -= 1

    return selected


def _interleave_by_protein(selected: list[RankedRecipe]) -> list[RankedRecipe]:
    if len(selected) <= 2:
        return selected

    buckets: dict[str, list[RankedRecipe]] = {}
    protein_order: list[str] = []
    for ranked in selected:
        key = _normalize(ranked.candidate.protein) or "unknown"
        if key not in buckets:
            buckets[key] = []
            protein_order.append(key)
        buckets[key].append(ranked)

    interleaved: list[RankedRecipe] = []
    while len(interleaved) < len(selected):
        made_progress = False
        for protein in protein_order:
            bucket = buckets.get(protein) or []
            if not bucket:
                continue
            interleaved.append(bucket.pop(0))
            made_progress = True
        if not made_progress:
            break
    return interleaved


def plan_weekly_menu_with_diagnostics(
    candidates: list[RecipeCandidate],
    target_count: int = 10,
    config: PlannerConfig | None = None,
) -> tuple[list[RankedRecipe], PlanningDiagnostics]:
    active_config = config or PlannerConfig()
    eligible = [candidate for candidate in candidates if check_eligibility(candidate, active_config).eligible]
    ranked = [score_candidate(candidate) for candidate in eligible]
    sorted_ranked = _sort_ranked(ranked)
    selected = enforce_diversity(sorted_ranked=sorted_ranked, target_count=target_count, config=active_config)

    trusted_selected = len([entry for entry in selected if entry.trusted_source])
    trusted_ratio = trusted_selected / len(selected) if selected else 0.0
    insufficient_reason = None
    if len(selected) < target_count:
        insufficient_reason = "insufficient_eligible_candidates"
    elif trusted_ratio < active_config.min_trusted_ratio:
        insufficient_reason = "low_trusted_source_ratio"

    diagnostics = PlanningDiagnostics(
        total_candidates=len(candidates),
        eligible_candidates=len(eligible),
        selected_meals=len(selected),
        trusted_selected=trusted_selected,
        trusted_ratio=trusted_ratio,
        insufficient_reason=insufficient_reason,
    )
    return selected, diagnostics


def plan_weekly_menu(candidates: list[RecipeCandidate], target_count: int = 10) -> list[RankedRecipe]:
    selected, _ = plan_weekly_menu_with_diagnostics(candidates=candidates, target_count=target_count)
    return selected
