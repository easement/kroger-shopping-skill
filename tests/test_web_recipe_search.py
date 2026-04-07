import unittest

from scripts.ad_capture import SaleItem
from scripts.web_recipe_search import (
    PlaywrightRecipeSearchAdapter,
    WebRecipeSearchAdapter,
    WebSearchConfig,
    _extract_rss_links,
    _parse_recipe_heuristic,
    _parse_recipe_microdata,
    _parse_recipe_json_ld,
)


class WebRecipeSearchTests(unittest.TestCase):
    def test_parse_recipe_microdata_parses_valid_recipe(self) -> None:
        html_page = """
        <html><head>
          <title>Skillet Salmon</title>
          <meta itemprop="ratingValue" content="4.5" />
          <meta itemprop="ratingCount" content="120" />
          <meta itemprop="recipeCuisine" content="American" />
          <meta itemprop="totalTime" content="PT25M" />
          <meta itemprop="recipeIngredient" content="salmon fillet" />
          <meta itemprop="recipeIngredient" content="garlic" />
        </head><body></body></html>
        """
        doc = _parse_recipe_microdata(html_page, "https://example.com/recipe/salmon")
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.protein, "salmon")
        self.assertEqual(doc.rating, 4.5)
        self.assertEqual(doc.vote_count, 120)
        self.assertEqual(doc.extraction_method, "microdata")

    def test_parse_recipe_heuristic_parses_rating_and_ingredients(self) -> None:
        html_page = """
        <html><head>
          <title>Garlic Shrimp Pasta</title>
          <script>
            window.__STATE__ = {"ratingValue":"4.4","reviewCount":"245"}
          </script>
        </head>
        <body>
          <li class="ingredients-item">1 lb shrimp</li>
          <li class="ingredients-item">2 cloves garlic</li>
          <li class="ingredients-item">8 oz pasta</li>
        </body></html>
        """
        doc = _parse_recipe_heuristic(html_page, "https://example.com/recipe/shrimp")
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.protein, "shrimp")
        self.assertEqual(doc.vote_count, 245)
        self.assertEqual(doc.extraction_method, "heuristic")

    def test_parse_recipe_json_ld_infers_seafood_protein_from_title(self) -> None:
        payload = {
            "@context": "https://schema.org",
            "@type": "Recipe",
            "name": "The Best Baked Salmon",
            "recipeCuisine": "American",
            "recipeIngredient": ["olive oil", "lemon", "salt"],
            "aggregateRating": {"ratingValue": "4.6", "ratingCount": "970"},
        }
        doc = _parse_recipe_json_ld(payload, "https://foodnetwork.com/recipes/salmon")
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.protein, "salmon")

    def test_parse_recipe_json_ld_infers_tuna_from_ingredients(self) -> None:
        payload = {
            "@context": "https://schema.org",
            "@type": "Recipe",
            "name": "Simple Sandwich",
            "recipeCuisine": "American",
            "recipeIngredient": ["canned tuna", "celery", "mayo"],
            "aggregateRating": {"ratingValue": "4.3", "ratingCount": "239"},
        }
        doc = _parse_recipe_json_ld(payload, "https://foodnetwork.com/recipes/tuna")
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.protein, "tuna")

    def test_extract_rss_links_parses_unique_links(self) -> None:
        xml = """
        <rss><channel>
          <item><link>https://allrecipes.com/r/1</link></item>
          <item><link>https://allrecipes.com/r/1</link></item>
          <item><link>https://foodnetwork.com/r/2</link></item>
        </channel></rss>
        """
        links = _extract_rss_links(xml)
        self.assertEqual(links, ["https://allrecipes.com/r/1", "https://foodnetwork.com/r/2"])

    def test_search_parses_recipe_json_ld_from_mocked_pages(self) -> None:
        xml = """
        <rss><channel>
          <item><link>https://allrecipes.com/recipe/1/test-a</link></item>
          <item><link>https://foodnetwork.com/recipes/test-b</link></item>
        </channel></rss>
        """
        html_page = """
        <html><head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Recipe",
          "name": "Test Chicken Recipe",
          "recipeCuisine": "Italian",
          "recipeIngredient": ["chicken breast", "tomato", "garlic"],
          "totalTime": "PT35M",
          "aggregateRating": {
            "ratingValue": "4.6",
            "ratingCount": "1234"
          }
        }
        </script>
        </head><body></body></html>
        """

        def fake_fetch(url: str) -> str:
            if "bing.com/search?format=rss" in url:
                return xml
            return html_page

        adapter = WebRecipeSearchAdapter(
            config=WebSearchConfig(
                trusted_domains=("allrecipes.com", "foodnetwork.com"),
                random_domain_count=2,
                max_links=10,
            ),
            fetch_text=fake_fetch,
        )
        docs = adapter.search((SaleItem(name="chicken", price_text="$1.99", category="protein"),))
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].title, "Test Chicken Recipe")
        self.assertEqual(docs[0].rating, 4.6)
        self.assertEqual(docs[0].vote_count, 1234)

    def test_search_filters_non_trusted_domains(self) -> None:
        xml = """
        <rss><channel>
          <item><link>https://example.com/not-trusted</link></item>
          <item><link>https://allrecipes.com/recipe/1/test</link></item>
        </channel></rss>
        """
        html_page = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Recipe","name":"Trusted Recipe",
         "recipeCuisine":"Italian","recipeIngredient":["chicken"],
         "aggregateRating":{"ratingValue":"4.4","ratingCount":"10"}}
        </script>
        """

        def fake_fetch(url: str) -> str:
            if "bing.com/search?format=rss" in url:
                return xml
            return html_page

        adapter = WebRecipeSearchAdapter(fetch_text=fake_fetch)
        docs = adapter.search((SaleItem(name="chicken", price_text="$1.99", category="protein"),))
        self.assertEqual(len(docs), 1)

    def test_search_blocks_forum_or_article_paths(self) -> None:
        xml = """
        <rss><channel>
          <item><link>https://allrecipes.com/article/not-a-recipe</link></item>
          <item><link>https://allrecipes.com/recipe/12345/real-recipe</link></item>
        </channel></rss>
        """
        html_page = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Recipe","name":"Trusted Recipe",
         "recipeCuisine":"Italian","recipeIngredient":["chicken"],
         "aggregateRating":{"ratingValue":"4.4","ratingCount":"10"}}
        </script>
        """

        def fake_fetch(url: str) -> str:
            if "bing.com/search?format=rss" in url:
                return xml
            return html_page

        adapter = WebRecipeSearchAdapter(fetch_text=fake_fetch)
        docs = adapter.search((SaleItem(name="chicken", price_text="$1.99", category="protein"),))
        self.assertEqual(len(docs), 1)

    def test_search_uses_relaxed_query_fallback_when_first_query_empty(self) -> None:
        rss_empty = "<rss><channel></channel></rss>"
        rss_relaxed = """
        <rss><channel>
          <item><link>https://allrecipes.com/recipe/12345/real-recipe</link></item>
        </channel></rss>
        """
        html_page = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Recipe","name":"Fallback Recipe",
         "recipeCuisine":"Italian","recipeIngredient":["chicken"],
         "aggregateRating":{"ratingValue":"4.3","ratingCount":"20"}}
        </script>
        """
        calls = {"rss": 0}

        def fake_fetch(url: str) -> str:
            if "bing.com/search?format=rss" in url:
                calls["rss"] += 1
                return rss_empty if calls["rss"] == 1 else rss_relaxed
            return html_page

        adapter = WebRecipeSearchAdapter(
            config=WebSearchConfig(use_relaxed_query_fallback=True, trusted_domains=("allrecipes.com",)),
            fetch_text=fake_fetch,
        )
        docs = adapter.search((SaleItem(name="chicken", price_text="$1.99", category="protein"),))
        self.assertEqual(calls["rss"], 2)
        self.assertEqual(len(docs), 1)
        self.assertTrue(adapter.last_stats["used_relaxed_query"])
        self.assertEqual(adapter.last_stats["rss_queries"], 2)

    def test_playwright_adapter_parses_recipe_json_ld(self) -> None:
        xml = """
        <rss><channel>
          <item><link>https://allrecipes.com/recipe/12345/real-recipe</link></item>
        </channel></rss>
        """
        html_page = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Recipe","name":"Playwright Recipe",
         "recipeCuisine":"Italian","recipeIngredient":["chicken"],
         "aggregateRating":{"ratingValue":"4.8","ratingCount":"200"}}
        </script>
        """

        def fake_fetch(url: str) -> str:
            if "bing.com/search?format=rss" in url:
                return xml
            return "<html></html>"

        def fake_playwright_fetch(url: str) -> str:
            return html_page

        adapter = PlaywrightRecipeSearchAdapter(
            config=WebSearchConfig(trusted_domains=("allrecipes.com",), max_links=5),
            fetch_text=fake_fetch,
            playwright_fetch_text=fake_playwright_fetch,
        )
        docs = adapter.search((SaleItem(name="chicken", price_text="$1.99", category="protein"),))
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].title, "Playwright Recipe")
        self.assertEqual(adapter.last_stats["pages_parsed"], 1)

    def test_search_selects_up_to_configured_random_domains(self) -> None:
        rss_empty = "<rss><channel></channel></rss>"

        def fake_fetch(url: str) -> str:
            return rss_empty

        adapter = WebRecipeSearchAdapter(
            config=WebSearchConfig(
                random_domain_count=2,
                use_relaxed_query_fallback=False,
                trusted_domains=("allrecipes.com", "foodnetwork.com", "eatingwell.com"),
            ),
            fetch_text=fake_fetch,
        )
        adapter.search((SaleItem(name="chicken", price_text="$1.99", category="protein"),))
        selected_domains = adapter.last_stats.get("selected_domains") or []
        self.assertEqual(len(selected_domains), 2)
        self.assertTrue(set(selected_domains).issubset({"allrecipes.com", "foodnetwork.com", "eatingwell.com"}))

    def test_search_uses_microdata_when_json_ld_missing(self) -> None:
        xml = """
        <rss><channel>
          <item><link>https://allrecipes.com/recipe/12345/real-recipe</link></item>
        </channel></rss>
        """
        html_page = """
        <html><head>
          <title>Turkey Skillet</title>
          <meta itemprop="ratingValue" content="4.4" />
          <meta itemprop="ratingCount" content="88" />
          <meta itemprop="recipeIngredient" content="ground turkey" />
          <meta itemprop="recipeIngredient" content="onion" />
        </head><body></body></html>
        """

        def fake_fetch(url: str) -> str:
            if "bing.com/search?format=rss" in url:
                return xml
            return html_page

        adapter = WebRecipeSearchAdapter(
            config=WebSearchConfig(trusted_domains=("allrecipes.com",), max_links=5),
            fetch_text=fake_fetch,
        )
        docs = adapter.search((SaleItem(name="turkey", price_text="$2.99", category="protein"),))
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].protein, "turkey")
        self.assertEqual(docs[0].extraction_method, "microdata")

    def test_search_uses_heuristic_when_json_ld_and_microdata_missing(self) -> None:
        xml = """
        <rss><channel>
          <item><link>https://allrecipes.com/recipe/12345/real-recipe</link></item>
        </channel></rss>
        """
        html_page = """
        <html><head>
          <title>Weeknight Beef Skillet</title>
          <script>var rating={"ratingValue":"4.6","ratingCount":"312"}</script>
        </head><body>
          <li class="ingredients-item">1 lb beef</li>
          <li class="ingredients-item">1 onion</li>
          <li class="ingredients-item">salt</li>
        </body></html>
        """

        def fake_fetch(url: str) -> str:
            if "bing.com/search?format=rss" in url:
                return xml
            return html_page

        adapter = WebRecipeSearchAdapter(
            config=WebSearchConfig(trusted_domains=("allrecipes.com",), max_links=5),
            fetch_text=fake_fetch,
        )
        docs = adapter.search((SaleItem(name="beef", price_text="$4.99", category="protein"),))
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].protein, "beef")
        self.assertEqual(docs[0].extraction_method, "heuristic")


if __name__ == "__main__":
    unittest.main()
