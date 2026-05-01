import json
import tempfile
import unittest
from pathlib import Path

from scripts.ad_capture import SaleItem
from scripts.recipe_search import (
    JsonFixtureRecipeSearchAdapter,
    RecipeDocument,
    documents_to_candidates,
    sale_item_recipe_anchors,
)


class RecipeFixtureValidationTests(unittest.TestCase):
    def test_invalid_fixture_shape_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture = Path(tmp_dir) / "bad.json"
            fixture.write_text(json.dumps({"not": "a-list"}))
            adapter = JsonFixtureRecipeSearchAdapter(str(fixture))
            with self.assertRaises(ValueError):
                adapter.search(())

    def test_missing_required_fields_raise_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture = Path(tmp_dir) / "bad-item.json"
            fixture.write_text(json.dumps([{"title": "Only Title"}]))
            adapter = JsonFixtureRecipeSearchAdapter(str(fixture))
            with self.assertRaises(ValueError):
                adapter.search(())

    def test_sale_matching_uses_protein_anchor_from_long_ad_headline(self) -> None:
        docs = [
            RecipeDocument(
                title="Best Beef Burgers",
                url="https://example.com/beef-burgers",
                cuisine="American",
                protein="beef",
                ingredients=("ground beef", "salt"),
                rating=4.5,
                vote_count=100,
                prep_minutes=30,
                healthy=True,
            )
        ]
        sale_items = (
            SaleItem(
                name="Fresh 80% Lean Homestyle Beef Patties - 8 ct, 1.9 lb",
                price_text="N/A",
                category="digital-ad-offer",
            ),
        )

        candidates = documents_to_candidates(docs=docs, sale_items=sale_items)

        self.assertEqual(candidates[0].sale_item_matches, (sale_items[0].name,))

    def test_sale_matching_does_not_match_different_pork_cut(self) -> None:
        docs = [
            RecipeDocument(
                title="Pork Tenderloin with Seasoned Rub",
                url="https://example.com/pork-tenderloin",
                cuisine="American",
                protein="pork",
                ingredients=("pork tenderloin", "garlic"),
                rating=4.7,
                vote_count=500,
                prep_minutes=30,
                healthy=True,
            )
        ]
        sale_items = (SaleItem(name="Pork Boston Butt - Bone-In", price_text="N/A", category="digital-ad-offer"),)

        candidates = documents_to_candidates(docs=docs, sale_items=sale_items)

        self.assertEqual(candidates[0].sale_item_matches, ())

    def test_sale_item_recipe_anchors_extracts_current_ad_terms(self) -> None:
        anchors = sale_item_recipe_anchors(
            "Fresh Heritage Farm Boneless Chicken Breasts - or Wings, Bone-In, $2.99 lb"
        )

        self.assertIn("chicken breasts", anchors)
        self.assertIn("chicken wings", anchors)

    def test_sale_matching_ignores_chicken_of_the_sea_brand_name(self) -> None:
        docs = [
            RecipeDocument(
                title="Chicken Piccata",
                url="https://example.com/chicken-piccata",
                cuisine="Italian",
                protein="chicken",
                ingredients=("chicken breast", "lemon", "capers"),
                rating=4.7,
                vote_count=1200,
                prep_minutes=35,
                healthy=True,
            )
        ]
        sale_items = (
            SaleItem(
                name="Starkist Tuna Pouch - or Chicken of the Sea Tuna, Select Varieties",
                price_text="N/A",
                category="digital-ad-offer",
            ),
        )

        candidates = documents_to_candidates(docs=docs, sale_items=sale_items)

        self.assertEqual(candidates[0].sale_item_matches, ())


if __name__ == "__main__":
    unittest.main()
