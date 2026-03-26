import unittest

from scripts.recipe_search import RecipeDocument
from scripts.refresh_live_recipes_fixture import _select_fresh_docs, _select_with_backfill


class RefreshLiveRecipesFixtureTests(unittest.TestCase):
    def test_select_fresh_docs_excludes_last_week_urls(self) -> None:
        docs = [
            RecipeDocument(
                title=f"Recipe {idx}",
                url=f"https://example.com/r/{idx}",
                cuisine="American",
                protein="chicken",
                ingredients=("chicken",),
                rating=4.5,
                vote_count=100 + idx,
                prep_minutes=30,
                healthy=True,
            )
            for idx in range(1, 8)
        ]
        excluded = {"https://example.com/r/1", "https://example.com/r/2", "https://example.com/r/3"}
        selected = _select_fresh_docs(docs=docs, excluded_urls=excluded, target_count=3)
        self.assertEqual(len(selected), 3)
        self.assertEqual(
            [doc.url for doc in selected],
            ["https://example.com/r/4", "https://example.com/r/5", "https://example.com/r/6"],
        )

    def test_select_fresh_docs_dedupes_urls(self) -> None:
        docs = [
            RecipeDocument(
                title="A",
                url="https://example.com/r/1",
                cuisine="American",
                protein="chicken",
                ingredients=("chicken",),
                rating=4.5,
                vote_count=100,
                prep_minutes=30,
                healthy=True,
            ),
            RecipeDocument(
                title="A2",
                url="https://example.com/r/1",
                cuisine="American",
                protein="chicken",
                ingredients=("chicken",),
                rating=4.4,
                vote_count=90,
                prep_minutes=30,
                healthy=True,
            ),
            RecipeDocument(
                title="B",
                url="https://example.com/r/2",
                cuisine="American",
                protein="beef",
                ingredients=("beef",),
                rating=4.6,
                vote_count=120,
                prep_minutes=35,
                healthy=True,
            ),
        ]
        selected = _select_fresh_docs(docs=docs, excluded_urls=set(), target_count=2)
        self.assertEqual([doc.url for doc in selected], ["https://example.com/r/1", "https://example.com/r/2"])

    def test_select_with_backfill_uses_docs_when_all_excluded(self) -> None:
        docs = [
            RecipeDocument(
                title=f"Recipe {idx}",
                url=f"https://example.com/r/{idx}",
                cuisine="American",
                protein="chicken",
                ingredients=("chicken",),
                rating=4.5,
                vote_count=100 + idx,
                prep_minutes=30,
                healthy=True,
            )
            for idx in range(1, 4)
        ]
        excluded = {doc.url for doc in docs}
        selected, used_backfill = _select_with_backfill(docs=docs, excluded_urls=excluded, target_count=2)
        self.assertTrue(used_backfill)
        self.assertEqual(len(selected), 2)


if __name__ == "__main__":
    unittest.main()
