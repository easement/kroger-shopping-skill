import unittest

from scripts.ad_capture import AdCaptureResult, SaleItem, StaticAdCaptureAdapter
from scripts.pipeline import run_menu_pipeline
from scripts.recipe_search import RecipeDocument


def make_doc(
    idx: int,
    *,
    cuisine: str,
    protein: str,
    rating: float = 4.4,
    vote_count: int = 180,
    ingredients: tuple[str, ...] = ("chicken breast", "garlic", "tomato"),
    url_domain: str = "allrecipes.com",
) -> RecipeDocument:
    return RecipeDocument(
        title=f"Recipe {idx}",
        url=f"https://{url_domain}/r/{idx}",
        cuisine=cuisine,
        protein=protein,
        ingredients=ingredients,
        rating=rating,
        vote_count=vote_count,
        prep_minutes=30,
        healthy=True,
    )


class PipelineTests(unittest.TestCase):
    def test_pipeline_returns_ranked_meals_when_ad_capture_succeeds(self) -> None:
        ad_result = AdCaptureResult(
            success=True,
            location_id="01100459",
            source="kroger-web",
            sale_items=(
                SaleItem(name="chicken", price_text="$1.99/lb", category="protein"),
                SaleItem(name="beef", price_text="$3.99/lb", category="protein"),
            ),
        )
        adapter = StaticAdCaptureAdapter(ad_result)
        docs = [
            make_doc(1, cuisine="Italian", protein="chicken"),
            make_doc(2, cuisine="Mexican", protein="beef"),
            make_doc(3, cuisine="American", protein="pork"),
            make_doc(4, cuisine="Mediterranean", protein="turkey"),
            make_doc(5, cuisine="Italian", protein="beef"),
            make_doc(6, cuisine="Mexican", protein="chicken"),
            make_doc(7, cuisine="American", protein="pork"),
            make_doc(8, cuisine="Greek", protein="lamb"),
            make_doc(9, cuisine="Italian", protein="turkey"),
            make_doc(10, cuisine="Mexican", protein="beef"),
            make_doc(11, cuisine="American", protein="chicken"),
        ]

        result = run_menu_pipeline(
            ad_adapter=adapter,
            recipe_docs=docs,
            location_id="01100459",
            target_count=10,
        )

        self.assertFalse(result.used_manual_fallback)
        self.assertEqual(result.ad_context.source, "kroger-web")
        self.assertEqual(len(result.meals), 10)
        self.assertIsNotNone(result.diagnostics)
        self.assertEqual(result.diagnostics.selected_meals, 10)

    def test_pipeline_uses_manual_fallback_when_ad_capture_fails(self) -> None:
        failed_ad_result = AdCaptureResult(
            success=False,
            location_id="01100459",
            source="kroger-web",
            sale_items=(),
            message="blocked by anti-bot",
        )
        adapter = StaticAdCaptureAdapter(failed_ad_result)
        docs = [make_doc(i, cuisine="Italian", protein="chicken") for i in range(1, 15)]

        result = run_menu_pipeline(
            ad_adapter=adapter,
            recipe_docs=docs,
            location_id="01100459",
            manual_fallback_items=[
                {"name": "chicken", "price_text": "$1.99/lb", "category": "protein"},
                {"name": "tomato", "price_text": "2 for $3", "category": "produce"},
            ],
            target_count=10,
        )

        self.assertTrue(result.used_manual_fallback)
        self.assertEqual(result.ad_context.source, "manual-fallback")
        self.assertGreater(len(result.ad_context.sale_items), 0)
        self.assertEqual(len(result.meals), 10)

    def test_pipeline_returns_empty_without_fallback_data_on_failed_capture(self) -> None:
        failed_ad_result = AdCaptureResult(
            success=False,
            location_id="01100459",
            source="kroger-web",
            sale_items=(),
            message="timed out",
        )
        adapter = StaticAdCaptureAdapter(failed_ad_result)
        docs = [make_doc(i, cuisine="Italian", protein="chicken") for i in range(1, 6)]

        result = run_menu_pipeline(
            ad_adapter=adapter,
            recipe_docs=docs,
            location_id="01100459",
            target_count=10,
        )

        self.assertFalse(result.used_manual_fallback)
        self.assertEqual(len(result.meals), 0)
        self.assertIn("timed out", result.ad_context.message)

    def test_pipeline_reports_insufficient_reason_when_candidates_too_few(self) -> None:
        ad_result = AdCaptureResult(
            success=True,
            location_id="01100459",
            source="kroger-web",
            sale_items=(SaleItem(name="chicken", price_text="$1.99/lb", category="protein"),),
        )
        adapter = StaticAdCaptureAdapter(ad_result)
        docs = [make_doc(1, cuisine="Italian", protein="chicken")]

        result = run_menu_pipeline(
            ad_adapter=adapter,
            recipe_docs=docs,
            location_id="01100459",
            target_count=10,
        )
        self.assertIsNotNone(result.diagnostics)
        self.assertEqual(result.diagnostics.insufficient_reason, "insufficient_eligible_candidates")


if __name__ == "__main__":
    unittest.main()
