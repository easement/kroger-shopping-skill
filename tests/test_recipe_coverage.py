import unittest

from scripts.ad_capture import SaleItem
from scripts.menu_planner import check_eligibility
from scripts.recipe_coverage import coverage_recipe_docs
from scripts.recipe_search import documents_to_candidates


class RecipeCoverageTests(unittest.TestCase):
    def test_coverage_docs_include_current_sale_mix_anchors(self) -> None:
        sale_items = (
            SaleItem(name="Kroger 80% Lean Ground Beef - Sold in a 3 lb Roll", price_text="N/A", category="ad"),
            SaleItem(name="Kroger Extra Large Cooked Shrimp - 26-30 ct", price_text="N/A", category="ad"),
            SaleItem(name="Pork Boston Butt - Bone-In", price_text="N/A", category="ad"),
            SaleItem(name="Home Chef St. Louis Style Ribs - Fully Cooked", price_text="N/A", category="ad"),
            SaleItem(name="Johnsonville Smoked Sausage", price_text="N/A", category="ad"),
            SaleItem(name="Fresh Heritage Farm Chicken Wings - Bone-In", price_text="N/A", category="ad"),
        )

        candidates = documents_to_candidates(coverage_recipe_docs(), sale_items)
        eligible = [candidate for candidate in candidates if check_eligibility(candidate).eligible]
        matched_sale_names = {
            sale_match
            for candidate in eligible
            for sale_match in candidate.sale_item_matches
        }

        for sale_item in sale_items:
            self.assertIn(sale_item.name, matched_sale_names)

    def test_coverage_docs_are_quick_trusted_and_deduped(self) -> None:
        docs = coverage_recipe_docs()
        urls = [doc.url for doc in docs]

        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(doc.prep_minutes <= 45 for doc in docs))
        self.assertTrue(all(doc.rating >= 4.0 for doc in docs))
        self.assertTrue(all(doc.vote_count > 0 for doc in docs))


if __name__ == "__main__":
    unittest.main()
