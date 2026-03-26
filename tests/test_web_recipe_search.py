import unittest

from scripts.ad_capture import SaleItem
from scripts.web_recipe_search import (
    PlaywrightRecipeSearchAdapter,
    WebRecipeSearchAdapter,
    WebSearchConfig,
    _extract_rss_links,
)


class WebRecipeSearchTests(unittest.TestCase):
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

        adapter = WebRecipeSearchAdapter(fetch_text=fake_fetch)
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


if __name__ == "__main__":
    unittest.main()
