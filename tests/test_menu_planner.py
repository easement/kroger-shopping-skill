import unittest

from scripts.menu_planner import (
    SERIOUS_EATS_BASE_SCORE,
    PlannerConfig,
    RecipeCandidate,
    check_eligibility,
    plan_weekly_menu,
    plan_weekly_menu_with_diagnostics,
    score_candidate,
)


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

    def test_candidates_without_sale_item_matches_are_excluded(self) -> None:
        candidates = [
            make_candidate(idx=1, cuisine="Italian", protein="chicken", sale_item_matches=()),
            make_candidate(idx=2, cuisine="Mexican", protein="beef", sale_item_matches=("beef",)),
        ]

        result, diagnostics = plan_weekly_menu_with_diagnostics(candidates, target_count=2)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].candidate.url, "https://example.com/meal-2")
        self.assertEqual(diagnostics.insufficient_reason, "insufficient_eligible_candidates")

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

    def test_confidence_boost_prefers_higher_confidence_extraction(self) -> None:
        low_conf = make_candidate(
            idx=30,
            cuisine="Italian",
            protein="chicken",
            rating=4.4,
            vote_count=120,
        )
        high_conf = make_candidate(
            idx=31,
            cuisine="Italian",
            protein="chicken",
            rating=4.4,
            vote_count=120,
        )
        low_conf = RecipeCandidate(**{**low_conf.__dict__, "extraction_confidence": 0.75})
        high_conf = RecipeCandidate(**{**high_conf.__dict__, "extraction_confidence": 1.0})
        self.assertGreater(score_candidate(high_conf).score, score_candidate(low_conf).score)

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
                cuisine=("Italian" if i % 4 == 0 else "Mexican" if i % 4 == 1 else "American" if i % 4 == 2 else "Greek"),
                protein=("chicken" if i % 4 == 0 else "beef" if i % 4 == 1 else "pork" if i % 4 == 2 else "salmon"),
                vote_count=100 + i,
            )
            for i in range(1, 21)
        ]

        result = plan_weekly_menu(candidates, target_count=10)
        self.assertEqual(len(result), 10)
        for item in result:
            self.assertGreaterEqual(item.candidate.rating, 4.0)
            self.assertGreater(item.candidate.vote_count, 0)

    def test_diversity_caps_limit_source_domain_when_alternatives_exist(self) -> None:
        heavy_one_domain = [
            make_candidate(
                idx=i,
                cuisine="Italian",
                protein=("chicken" if i % 2 == 0 else "beef"),
                source_domain="foodnetwork.com",
                vote_count=200 + i,
            )
            for i in range(1, 12)
        ]
        other_domains = [
            make_candidate(idx=101, cuisine="American", protein="pork", source_domain="allrecipes.com"),
            make_candidate(idx=102, cuisine="Greek", protein="lamb", source_domain="seriouseats.com"),
            make_candidate(idx=103, cuisine="Mexican", protein="turkey", source_domain="skinnytaste.com"),
            make_candidate(idx=104, cuisine="Italian", protein="beef", source_domain="food52.com"),
        ]
        config = PlannerConfig(max_per_source_domain=2)
        result, _ = plan_weekly_menu_with_diagnostics(
            heavy_one_domain + other_domains,
            target_count=6,
            config=config,
        )
        domains = [item.candidate.source_domain for item in result]
        self.assertLessEqual(domains.count("foodnetwork.com"), 2)

    def test_selected_order_interleaves_proteins(self) -> None:
        candidates = [
            make_candidate(idx=1, cuisine="Italian", protein="chicken", vote_count=400),
            make_candidate(idx=2, cuisine="Italian", protein="chicken", vote_count=390),
            make_candidate(idx=3, cuisine="Italian", protein="chicken", vote_count=380),
            make_candidate(idx=4, cuisine="American", protein="beef", vote_count=370),
            make_candidate(idx=5, cuisine="American", protein="beef", vote_count=360),
            make_candidate(idx=6, cuisine="Mexican", protein="pork", vote_count=350),
        ]
        result = plan_weekly_menu(candidates, target_count=6)
        proteins = [item.candidate.protein.lower() for item in result]
        # Expect mixed sequence rather than all chicken first.
        self.assertNotEqual(proteins[:3], ["chicken", "chicken", "chicken"])

    def test_caps_foodnetwork_to_two_per_protein(self) -> None:
        candidates = [
            make_candidate(idx=1, cuisine="Italian", protein="chicken", source_domain="foodnetwork.com", vote_count=500),
            make_candidate(idx=2, cuisine="Italian", protein="chicken", source_domain="foodnetwork.com", vote_count=490),
            make_candidate(idx=3, cuisine="Italian", protein="chicken", source_domain="foodnetwork.com", vote_count=480),
            make_candidate(idx=4, cuisine="American", protein="beef", source_domain="foodnetwork.com", vote_count=470),
            make_candidate(idx=5, cuisine="American", protein="beef", source_domain="foodnetwork.com", vote_count=460),
            make_candidate(idx=6, cuisine="American", protein="beef", source_domain="foodnetwork.com", vote_count=450),
            make_candidate(idx=7, cuisine="Greek", protein="lamb", source_domain="allrecipes.com", vote_count=440),
            make_candidate(idx=8, cuisine="Mexican", protein="pork", source_domain="allrecipes.com", vote_count=430),
        ]

        result = plan_weekly_menu(candidates, target_count=8)
        by_domain_protein: dict[tuple[str, str], int] = {}
        for item in result:
            key = (item.candidate.source_domain.lower(), item.candidate.protein.lower())
            by_domain_protein[key] = by_domain_protein.get(key, 0) + 1

        self.assertLessEqual(by_domain_protein.get(("foodnetwork.com", "chicken"), 0), 2)
        self.assertLessEqual(by_domain_protein.get(("foodnetwork.com", "beef"), 0), 2)

    def test_enforces_minimum_non_foodnetwork_quota(self) -> None:
        foodnetwork_heavy = [
            make_candidate(
                idx=i,
                cuisine="American",
                protein=("chicken" if i % 2 == 0 else "beef"),
                source_domain="foodnetwork.com",
                vote_count=400 - i,
            )
            for i in range(1, 11)
        ]
        non_foodnetwork = [
            make_candidate(idx=201, cuisine="Greek", protein="lamb", source_domain="epicurious.com", vote_count=160),
            make_candidate(idx=202, cuisine="American", protein="turkey", source_domain="jocooks.com", vote_count=150),
            make_candidate(idx=203, cuisine="Italian", protein="pork", source_domain="allrecipes.com", vote_count=140),
            make_candidate(idx=204, cuisine="Mexican", protein="beef", source_domain="delish.com", vote_count=130),
        ]
        config = PlannerConfig(
            max_per_source_domain=10,
            max_per_protein=5,
            min_non_foodnetwork_count=4,
        )
        result, _ = plan_weekly_menu_with_diagnostics(
            foodnetwork_heavy + non_foodnetwork,
            target_count=8,
            config=config,
        )
        non_fn_count = len([item for item in result if item.candidate.source_domain != "foodnetwork.com"])
        self.assertGreaterEqual(non_fn_count, 4)


class SeriousEatsTests(unittest.TestCase):
    def _make_se_candidate(self, idx: int, **kwargs: object) -> RecipeCandidate:
        kwargs.setdefault("cuisine", "American")
        kwargs.setdefault("protein", "chicken")
        return make_candidate(idx=idx, source_domain="seriouseats.com", **kwargs)

    def test_serious_eats_eligible_with_zero_votes(self) -> None:
        candidate = self._make_se_candidate(idx=300, vote_count=0)
        result = check_eligibility(candidate)
        self.assertTrue(result.eligible)

    def test_serious_eats_eligible_with_low_rating(self) -> None:
        candidate = self._make_se_candidate(idx=301, rating=3.0, vote_count=0)
        result = check_eligibility(candidate)
        self.assertTrue(result.eligible)

    def test_serious_eats_score_uses_fixed_base(self) -> None:
        se_candidate = self._make_se_candidate(idx=302, rating=3.0, vote_count=0)
        ranked = score_candidate(se_candidate)
        self.assertGreaterEqual(ranked.score, SERIOUS_EATS_BASE_SCORE)

    def test_serious_eats_outscores_typical_recipe(self) -> None:
        se_candidate = self._make_se_candidate(idx=303, rating=3.0, vote_count=0)
        typical = make_candidate(
            idx=304,
            cuisine="Italian",
            protein="beef",
            source_domain="allrecipes.com",
            rating=4.7,
            vote_count=2000,
        )
        se_score = score_candidate(se_candidate).score
        typical_score = score_candidate(typical).score
        self.assertGreater(se_score, typical_score)

    def test_serious_eats_capped_at_three_per_week(self) -> None:
        proteins = ("chicken", "beef", "pork", "turkey", "salmon")
        cuisines = ("American", "Italian", "Mexican", "Greek", "Mediterranean")
        other_domains = ("allrecipes.com", "epicurious.com", "simplyrecipes.com", "budgetbytes.com", "skinnytaste.com")
        se_candidates = [
            self._make_se_candidate(
                idx=i,
                protein=proteins[i % len(proteins)],
                vote_count=0,
                rating=3.5,
            )
            for i in range(310, 316)
        ]
        # Spread other candidates across multiple domains so domain cap doesn't force SE overflow
        other = [
            make_candidate(
                idx=320 + i,
                cuisine=cuisines[i % len(cuisines)],
                protein=proteins[i % len(proteins)],
                source_domain=other_domains[i % len(other_domains)],
                vote_count=200 + i,
            )
            for i in range(15)
        ]
        config = PlannerConfig(max_per_source_domain=3, max_per_protein=5)
        result, _ = plan_weekly_menu_with_diagnostics(
            se_candidates + other,
            target_count=10,
            config=config,
        )
        se_count = sum(1 for item in result if item.candidate.source_domain == "seriouseats.com")
        self.assertLessEqual(se_count, 3)


if __name__ == "__main__":
    unittest.main()
