import unittest

from scripts.ad_capture import SaleItem
from scripts.web_recipe_search import WebRecipeSearchAdapter, _extract_rss_links


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
          <item><link>https://allrecipes.com/r/1</link></item>
          <item><link>https://foodnetwork.com/r/2</link></item>
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


if __name__ == "__main__":
    unittest.main()
