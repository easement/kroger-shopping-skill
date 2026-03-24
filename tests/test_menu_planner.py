import unittest

from scripts.menu_planner import RecipeCandidate, plan_weekly_menu, score_candidate


def make_candidate(
    *,
    idx: int,
    cuisine: str,
    protein: str,
    rating: float = 4.4,
    vote_count: int = 120,
    healthy: bool = True,
    prep_minutes: int = 30,
    ingredients: tuple[str, ...] = ("chicken breast", "tomato", "garlic"),
    source_domain: str = "allrecipes.com",
    sale_item_matches: tuple[str, ...] = ("chicken",),
) -> RecipeCandidate:
    return RecipeCandidate(
        title=f"Meal {idx}",
        url=f"https://example.com/meal-{idx}",
        source_domain=source_domain,
        cuisine=cuisine,
        protein=protein,
        ingredients=ingredients,
        rating=rating,
        vote_count=vote_count,
        prep_minutes=prep_minutes,
        healthy=healthy,
        sale_item_matches=sale_item_matches,
    )


class MenuPlannerTests(unittest.TestCase):
    def test_exclusions_and_thresholds_are_enforced(self) -> None:
        candidates = [
            make_candidate(idx=1, cuisine="Italian", protein="chicken"),
            make_candidate(idx=2, cuisine="Asian", protein="beef"),
            make_candidate(
                idx=3,
                cuisine="Mexican",
                protein="beef",
                ingredients=("beef", "black beans", "onion"),
            ),
            make_candidate(
                idx=4,
                cuisine="American",
                protein="pork",
                ingredients=("pork loin", "fennel", "salt"),
            ),
            make_candidate(idx=5, cuisine="American", protein="beef", rating=3.8),
            make_candidate(idx=6, cuisine="American", protein="beef", vote_count=0),
            make_candidate(idx=7, cuisine="American", protein="beef", healthy=False),
            make_candidate(idx=8, cuisine="American", protein="beef", prep_minutes=60),
        ]

        result = plan_weekly_menu(candidates, target_count=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].candidate.url, "https://example.com/meal-1")

    def test_weighted_score_favors_high_vote_count(self) -> None:
        low_votes_high_rating = make_candidate(
            idx=10,
            cuisine="Italian",
            protein="chicken",
            rating=4.9,
            vote_count=7,
            source_domain="smallblog.com",
        )
        high_votes_slightly_lower_rating = make_candidate(
            idx=11,
            cuisine="Italian",
            protein="chicken",
            rating=4.7,
            vote_count=2200,
            source_domain="allrecipes.com",
        )

        low_score = score_candidate(low_votes_high_rating).score
        high_score = score_candidate(high_votes_slightly_lower_rating).score
        self.assertGreater(high_score, low_score)

    def test_diversity_caps_reduce_single_protein_domination(self) -> None:
        chicken_heavy = [
            make_candidate(idx=i, cuisine="Italian", protein="chicken", vote_count=300 + i)
            for i in range(1, 9)
        ]
        mixed = [
            make_candidate(idx=20, cuisine="Mexican", protein="beef", vote_count=250),
            make_candidate(idx=21, cuisine="American", protein="pork", vote_count=240),
            make_candidate(idx=22, cuisine="Mediterranean", protein="turkey", vote_count=230),
            make_candidate(idx=23, cuisine="Italian", protein="beef", vote_count=220),
            make_candidate(idx=24, cuisine="Greek", protein="lamb", vote_count=210),
            make_candidate(idx=25, cuisine="American", protein="turkey", vote_count=205),
            make_candidate(idx=26, cuisine="Mexican", protein="pork", vote_count=200),
        ]

        result = plan_weekly_menu(chicken_heavy + mixed, target_count=10)
        proteins = [item.candidate.protein.lower() for item in result]
        self.assertLessEqual(proteins.count("chicken"), 3)
        self.assertIn("beef", proteins)
        self.assertIn("pork", proteins)

    def test_returns_exactly_target_count_when_enough_valid(self) -> None:
        candidates = [
            make_candidate(
                idx=i,
                cuisine=("Italian" if i % 2 == 0 else "Mexican"),
                protein=("chicken" if i % 3 == 0 else "beef" if i % 3 == 1 else "pork"),
                vote_count=100 + i,
            )
            for i in range(1, 21)
        ]

        result = plan_weekly_menu(candidates, target_count=10)
        self.assertEqual(len(result), 10)
        for item in result:
            self.assertGreaterEqual(item.candidate.rating, 4.0)
            self.assertGreater(item.candidate.vote_count, 0)


if __name__ == "__main__":
    unittest.main()
