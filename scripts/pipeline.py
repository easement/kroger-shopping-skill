from __future__ import annotations

from dataclasses import dataclass

from scripts.ad_capture import (
    DEFAULT_LOCATION_ID,
    AdCaptureAdapter,
    AdCaptureResult,
    build_manual_fallback_result,
)
from scripts.menu_planner import (
    PlannerConfig,
    PlanningDiagnostics,
    RankedRecipe,
    plan_weekly_menu_with_diagnostics,
)
from scripts.recipe_search import RecipeDocument, RecipeSearchAdapter, documents_to_candidates


@dataclass(frozen=True)
class PipelineResult:
    meals: tuple[RankedRecipe, ...]
    ad_context: AdCaptureResult
    used_manual_fallback: bool
    diagnostics: PlanningDiagnostics | None = None


def run_menu_pipeline(
    *,
    ad_adapter: AdCaptureAdapter,
    recipe_docs: list[RecipeDocument],
    location_id: str = DEFAULT_LOCATION_ID,
    manual_fallback_items: list[dict[str, str]] | None = None,
    target_count: int = 10,
    planner_config: PlannerConfig | None = None,
) -> PipelineResult:
    ad_context = ad_adapter.capture_weekly_ad(location_id=location_id)
    used_manual_fallback = False

    if not ad_context.success:
        if not manual_fallback_items:
            return PipelineResult(
                meals=(),
                ad_context=ad_context,
                used_manual_fallback=False,
            )

        ad_context = build_manual_fallback_result(
            manual_items=manual_fallback_items,
            location_id=location_id,
        )
        used_manual_fallback = True

    candidates = documents_to_candidates(docs=recipe_docs, sale_items=ad_context.sale_items)
    planned, diagnostics = plan_weekly_menu_with_diagnostics(
        candidates=candidates,
        target_count=target_count,
        config=planner_config,
    )
    return PipelineResult(
        meals=tuple(planned),
        ad_context=ad_context,
        used_manual_fallback=used_manual_fallback,
        diagnostics=diagnostics,
    )


def run_menu_pipeline_with_search(
    *,
    ad_adapter: AdCaptureAdapter,
    recipe_search_adapter: RecipeSearchAdapter,
    location_id: str = DEFAULT_LOCATION_ID,
    manual_fallback_items: list[dict[str, str]] | None = None,
    target_count: int = 10,
    planner_config: PlannerConfig | None = None,
) -> PipelineResult:
    ad_context = ad_adapter.capture_weekly_ad(location_id=location_id)
    used_manual_fallback = False

    if not ad_context.success:
        if not manual_fallback_items:
            return PipelineResult(
                meals=(),
                ad_context=ad_context,
                used_manual_fallback=False,
            )

        ad_context = build_manual_fallback_result(
            manual_items=manual_fallback_items,
            location_id=location_id,
        )
        used_manual_fallback = True

    recipe_docs = recipe_search_adapter.search(ad_context.sale_items)
    candidates = documents_to_candidates(docs=recipe_docs, sale_items=ad_context.sale_items)
    planned, diagnostics = plan_weekly_menu_with_diagnostics(
        candidates=candidates,
        target_count=target_count,
        config=planner_config,
    )

    return PipelineResult(
        meals=tuple(planned),
        ad_context=ad_context,
        used_manual_fallback=used_manual_fallback,
        diagnostics=diagnostics,
    )
