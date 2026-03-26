import tempfile
import unittest
from pathlib import Path
import json

from scripts.replay_parsers import replay_ad_capture_dir, replay_recipe_capture_dir


class ReplayParsersTests(unittest.TestCase):
    def test_replay_ad_capture_dir_extracts_sale_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            root.mkdir(parents=True, exist_ok=True)
            (root / "a.txt").write_text("Chicken Breast - $1.99/lb")

            shoppable_payload = {
                "data": {
                    "shoppableWeeklyDeals": {
                        "ads": [
                            {
                                "mainlineCopy": "Whole Chicken",
                                "underlineCopy": "2 lb Package",
                                "salePrice": 0.99,
                                "retailPrice": 1.99,
                            }
                        ]
                    }
                }
            }
            (root / "b.txt").write_text(json.dumps(shoppable_payload))

            stats = replay_ad_capture_dir(str(root))
            self.assertEqual(stats.files_scanned, 2)
            self.assertEqual(stats.files_parsed, 2)
            self.assertGreaterEqual(stats.items_extracted, 2)
            self.assertEqual(stats.files_with_signal, 1)
            self.assertEqual(stats.files_with_non_recipe_jsonld, 0)

    def test_replay_recipe_capture_dir_extracts_recipe_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            html = """
            <script type="application/ld+json">
            {
              "@context":"https://schema.org",
              "@type":"Recipe",
              "name":"Replay Test Recipe",
              "recipeCuisine":"Italian",
              "recipeIngredient":["chicken breast","garlic"],
              "aggregateRating":{"ratingValue":"4.8","ratingCount":"200"}
            }
            </script>
            """
            (root / "r.txt").write_text(html)
            stats = replay_recipe_capture_dir(str(root))
            self.assertEqual(stats.files_scanned, 1)
            self.assertEqual(stats.files_parsed, 1)
            self.assertGreaterEqual(stats.items_extracted, 1)
            self.assertEqual(stats.files_with_signal, 1)

    def test_replay_recipe_capture_counts_non_recipe_jsonld(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            html = """
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Article","name":"Not a recipe"}
            </script>
            """
            (root / "a.txt").write_text(html)
            stats = replay_recipe_capture_dir(str(root))
            self.assertEqual(stats.files_scanned, 1)
            self.assertEqual(stats.files_parsed, 0)
            self.assertEqual(stats.files_with_signal, 1)
            self.assertEqual(stats.files_with_non_recipe_jsonld, 1)


if __name__ == "__main__":
    unittest.main()
