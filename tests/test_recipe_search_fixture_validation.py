import json
import tempfile
import unittest
from pathlib import Path

from scripts.recipe_search import JsonFixtureRecipeSearchAdapter


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


if __name__ == "__main__":
    unittest.main()
