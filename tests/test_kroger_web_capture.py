import json
from pathlib import Path
import unittest

from scripts.kroger_web_capture import (
    KrogerPlaywrightAdCaptureAdapter,
    KrogerWebAdCaptureAdapter,
    KrogerWebCaptureConfig,
    build_x_active_modality_cookie,
)


class KrogerWebCaptureTests(unittest.TestCase):
    def test_build_cookie_contains_location_id(self) -> None:
        cookie = build_x_active_modality_cookie("01100459")
        self.assertIn('"locationId":"01100459"', cookie)
        self.assertIn('"type":"PICKUP"', cookie)

    def test_adapter_uses_provided_cookie_header_verbatim(self) -> None:
        html = "<html><body>no items</body></html>"

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            self.assertIn("User-Agent", headers)
            self.assertEqual(headers.get("Cookie"), "a=b; c=d")
            return html

        adapter = KrogerWebAdCaptureAdapter(
            config=KrogerWebCaptureConfig(cookie_header="a=b; c=d"),
            fetch_text=fake_fetch,
        )
        adapter.capture_weekly_ad(location_id="01100459")

    def test_adapter_merges_extra_headers(self) -> None:
        html = "<html><body>no items</body></html>"

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            self.assertEqual(headers.get("Cookie"), "a=b; c=d")
            self.assertEqual(headers.get("X-Test-Header"), "yes")
            return html

        adapter = KrogerWebAdCaptureAdapter(
            config=KrogerWebCaptureConfig(
                cookie_header="a=b; c=d",
                extra_headers={"X-Test-Header": "yes"},
            ),
            fetch_text=fake_fetch,
        )
        adapter.capture_weekly_ad(location_id="01100459")

    def test_capture_parses_sale_items_from_mocked_html(self) -> None:
        html = """
        <div>Chicken Breast - $1.99/lb</div>
        <div>Ground Beef - $3.49/lb</div>
        <div>Bell Peppers - $2.00/lb</div>
        """

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            self.assertIn("x-active-modality=", headers.get("Cookie", ""))
            self.assertIn("kroger.com/weeklyad", url)
            return html

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch)
        result = adapter.capture_weekly_ad(location_id="01100459")

        self.assertTrue(result.success)
        self.assertEqual(result.source, "kroger-web")
        self.assertGreaterEqual(len(result.sale_items), 3)

    def test_capture_returns_failure_when_no_items_found(self) -> None:
        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return "<html><body>No promo cards found</body></html>"

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch)
        result = adapter.capture_weekly_ad(location_id="01100459")

        self.assertFalse(result.success)
        self.assertEqual(result.message, "no_sale_items_parsed")

    def test_capture_parses_json_like_sale_items(self) -> None:
        html = """
        <script>
        window.__INITIAL_STATE__ = {
          "saleItems": [
            {"name":"Chicken Breast","salePrice":"$1.99/lb"},
            {"name":"Ground Beef","salePrice":"$3.49/lb"}
          ]
        }
        </script>
        """

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return html

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch)
        result = adapter.capture_weekly_ad(location_id="01100459")
        self.assertTrue(result.success)
        names = [item.name for item in result.sale_items]
        self.assertIn("Chicken Breast", names)
        self.assertIn("Ground Beef", names)

    def test_capture_parses_escaped_json_snippets(self) -> None:
        html = r"""
        <script>
        var payload = "{\"name\":\"Chicken Breast\",\"promoPrice\":\"$1.99/lb\"}";
        </script>
        """

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return html

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch)
        result = adapter.capture_weekly_ad(location_id="01100459")
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.sale_items), 1)

    def test_capture_parses_initial_state_like_escaped_content(self) -> None:
        html = r"""
        <script>
        window.__INITIAL_STATE__ = JSON.parse("{\"name\":\"Ground Beef\",\"offerPrice\":\"$3.49/lb\"}");
        </script>
        """

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return html

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch)
        result = adapter.capture_weekly_ad(location_id="01100459")
        self.assertTrue(result.success)
        names = [item.name for item in result.sale_items]
        self.assertIn("Ground Beef", names)
        self.assertTrue(adapter.last_stats["has_initial_state_signal"])
        self.assertGreaterEqual(adapter.last_stats["parsed_from_initial_state_items"], 1)

    def test_capture_falls_back_to_api_probe_when_html_has_no_items(self) -> None:
        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return "<html><body>weeklyad shell only</body></html>"

        def fake_fetch_json(url: str, headers: dict[str, str]) -> object:
            return {
                "data": {
                    "products": [
                        {"description": "Chicken Breast", "salePrice": 1.99},
                        {"description": "Ground Beef", "salePrice": "$3.49/lb"},
                    ]
                }
            }

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch, fetch_json=fake_fetch_json)
        result = adapter.capture_weekly_ad(location_id="01100459")
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.sale_items), 2)
        self.assertGreaterEqual(adapter.last_stats["api_endpoints_attempted"], 1)
        self.assertGreaterEqual(adapter.last_stats["parsed_from_api_items"], 2)

    def test_shoppable_weekly_deals_probed_first_when_circular_id_in_config(self) -> None:
        requested_urls: list[str] = []

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return "<html><body>empty</body></html>"

        def fake_fetch_json(url: str, headers: dict[str, str]) -> object:
            requested_urls.append(url)
            if "shoppable-weekly-deals" in url:
                return {
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
            return {}

        circular = "63b9590c-dbd9-44a3-b0cc-abb35d99690e"
        adapter = KrogerWebAdCaptureAdapter(
            config=KrogerWebCaptureConfig(circular_id=circular),
            fetch_text=fake_fetch,
            fetch_json=fake_fetch_json,
        )
        result = adapter.capture_weekly_ad("01100459")
        self.assertTrue(result.success)
        names = [item.name for item in result.sale_items]
        self.assertTrue(any(name.startswith("Whole Chicken") for name in names))
        self.assertIn("shoppable-weekly-deals", requested_urls[0])
        self.assertIn(f"filter.circularId={circular}", requested_urls[0])
        self.assertEqual(adapter.last_stats["circular_id_source"], "config")
        self.assertTrue(adapter.last_stats["shoppable_weekly_deals_attempted"])

    def test_circular_id_from_html_triggers_shoppable_deals_first(self) -> None:
        html = '<html><script>{"circularId":"63b9590c-dbd9-44a3-b0cc-abb35d99690e"}</script></html>'
        requested_urls: list[str] = []

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return html

        def fake_fetch_json(url: str, headers: dict[str, str]) -> object:
            requested_urls.append(url)
            if "shoppable-weekly-deals" in url:
                return {
                    "data": {
                        "shoppableWeeklyDeals": {
                            "ads": [
                                {
                                    "mainlineCopy": "Pork Chops",
                                    "underlineCopy": "16 oz Package",
                                    "salePrice": 4.99,
                                    "retailPrice": 5.99,
                                }
                            ]
                        }
                    }
                }
            return {}

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch, fetch_json=fake_fetch_json)
        result = adapter.capture_weekly_ad("01100459")
        self.assertTrue(result.success)
        self.assertTrue(any(item.name.startswith("Pork Chops") for item in result.sale_items))
        self.assertEqual(adapter.last_stats["circular_id_source"], "html")
        self.assertIn("shoppable-weekly-deals", requested_urls[0])

    def test_shoppable_weekly_deals_parses_from_fixture(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent.parent / "fixtures" / "shoppable-weekly-deals.sample.json"
        )
        fixture = json.loads(fixture_path.read_text())

        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return "<html><body>empty</body></html>"

        def fake_fetch_json(url: str, headers: dict[str, str]) -> object:
            if "shoppable-weekly-deals" in url:
                return fixture
            return {}

        circular = "63b9590c-dbd9-44a3-b0cc-abb35d99690e"
        adapter = KrogerWebAdCaptureAdapter(
            config=KrogerWebCaptureConfig(circular_id=circular),
            fetch_text=fake_fetch,
            fetch_json=fake_fetch_json,
        )
        result = adapter.capture_weekly_ad("01100459")
        self.assertTrue(result.success)
        self.assertEqual(len(result.sale_items), 2)

        by_name = {item.name: item.price_text for item in result.sale_items}
        self.assertEqual(
            by_name.get("Kroger 85% Lean Ground Beef - 16 oz Package"),
            "$5.99",
        )
        self.assertEqual(
            by_name.get("Chicken Breast - 2 lb Package"),
            "$1.99",
        )
        self.assertEqual(adapter.last_stats["circular_id_source"], "config")

    def test_capture_falls_back_to_heuristic_anchors(self) -> None:
        def fake_fetch(url: str, headers: dict[str, str]) -> str:
            return "<html><meta name='description' content='Weekly Ad deals on meat and seafood, produce and dairy.'/></html>"

        def fake_fetch_json(url: str, headers: dict[str, str]) -> object:
            return {"data": {}}

        adapter = KrogerWebAdCaptureAdapter(fetch_text=fake_fetch, fetch_json=fake_fetch_json)
        result = adapter.capture_weekly_ad(location_id="01100459")
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(result.sale_items), 3)
        self.assertGreaterEqual(adapter.last_stats["parsed_from_heuristic_items"], 1)


class KrogerPlaywrightCaptureTests(unittest.TestCase):
    def test_playwright_adapter_parses_deals_payload(self) -> None:
        payload = {
            "html": "<html><body>weeklyad</body></html>",
            "circular_id": "63b9590c-dbd9-44a3-b0cc-abb35d99690e",
            "deals_status": 200,
            "deals_body": json.dumps(
                {
                    "data": {
                        "shoppableWeeklyDeals": {
                            "ads": [
                                {
                                    "mainlineCopy": "Chicken Breast",
                                    "underlineCopy": "2 lb Package",
                                    "salePrice": 1.99,
                                    "retailPrice": 3.99,
                                }
                            ]
                        }
                    }
                }
            ),
            "deals_error": "",
        }

        def fake_playwright_capture(
            weeklyad_url: str,
            circular_id: str | None,
            headers: dict[str, str],
            user_data_dir: str | None,
            headless: bool,
            post_load_wait_ms: int,
            browser_channel: str | None,
        ) -> dict[str, object]:
            self.assertIn("kroger.com/weeklyad", weeklyad_url)
            self.assertEqual(circular_id, "63b9590c-dbd9-44a3-b0cc-abb35d99690e")
            self.assertIn("User-Agent", headers)
            self.assertIsNone(user_data_dir)
            self.assertTrue(headless)
            self.assertEqual(post_load_wait_ms, 5000)
            self.assertIsNone(browser_channel)
            return payload

        adapter = KrogerPlaywrightAdCaptureAdapter(
            config=KrogerWebCaptureConfig(circular_id="63b9590c-dbd9-44a3-b0cc-abb35d99690e"),
            playwright_capture=fake_playwright_capture,
        )
        result = adapter.capture_weekly_ad("01100459")

        self.assertTrue(result.success)
        self.assertEqual(result.source, "kroger-playwright")
        self.assertEqual(len(result.sale_items), 1)
        self.assertEqual(result.sale_items[0].name, "Chicken Breast - 2 lb Package")
        self.assertEqual(adapter.last_stats["parsed_from_api_items"], 1)
        self.assertTrue(adapter.last_stats["shoppable_weekly_deals_attempted"])

    def test_playwright_adapter_surfaces_capture_failure(self) -> None:
        def failing_capture(
            weeklyad_url: str,
            circular_id: str | None,
            headers: dict[str, str],
            user_data_dir: str | None,
            headless: bool,
            post_load_wait_ms: int,
            browser_channel: str | None,
        ) -> dict[str, object]:
            raise RuntimeError("playwright unavailable")

        adapter = KrogerPlaywrightAdCaptureAdapter(playwright_capture=failing_capture)
        result = adapter.capture_weekly_ad("01100459")
        self.assertFalse(result.success)
        self.assertEqual(result.source, "kroger-playwright")
        self.assertIn("request_failed:playwright unavailable", result.message)

    def test_playwright_adapter_passes_browser_session_options(self) -> None:
        def fake_playwright_capture(
            weeklyad_url: str,
            circular_id: str | None,
            headers: dict[str, str],
            user_data_dir: str | None,
            headless: bool,
            post_load_wait_ms: int,
            browser_channel: str | None,
        ) -> dict[str, object]:
            self.assertEqual(user_data_dir, "/tmp/kroger-profile")
            self.assertFalse(headless)
            self.assertEqual(post_load_wait_ms, 9000)
            self.assertEqual(browser_channel, "chrome")
            return {
                "html": "<html><body>weeklyad</body></html>",
                "circular_id": "63b9590c-dbd9-44a3-b0cc-abb35d99690e",
                "deals_status": 200,
                "deals_body": json.dumps(
                    {
                        "data": {
                            "shoppableWeeklyDeals": {
                                "ads": [
                                    {
                                        "mainlineCopy": "Fresh Salmon",
                                        "underlineCopy": "Whole Fillet",
                                        "retailPrice": 8.99,
                                    }
                                ]
                            }
                        }
                    }
                ),
                "deals_error": "",
            }

        adapter = KrogerPlaywrightAdCaptureAdapter(
            config=KrogerWebCaptureConfig(
                circular_id="63b9590c-dbd9-44a3-b0cc-abb35d99690e",
                browser_profile_dir="/tmp/kroger-profile",
                browser_headless=False,
                browser_post_load_wait_ms=9000,
                browser_channel="chrome",
            ),
            playwright_capture=fake_playwright_capture,
        )

        result = adapter.capture_weekly_ad("01100459")

        self.assertTrue(result.success)
        self.assertEqual(result.sale_items[0].name, "Fresh Salmon - Whole Fillet")

    def test_playwright_adapter_parses_digital_ad_page_payloads(self) -> None:
        def fake_playwright_capture(
            weeklyad_url: str,
            circular_id: str | None,
            headers: dict[str, str],
            user_data_dir: str | None,
            headless: bool,
            post_load_wait_ms: int,
            browser_channel: str | None,
        ) -> dict[str, object]:
            return {
                "html": "<html><body>weeklyad</body></html>",
                "circular_id": None,
                "deals_status": None,
                "deals_body": "",
                "deals_error": "",
                "digital_ad_bodies": [
                    json.dumps(
                        {
                            "eventPageId": "page-1",
                            "contents": [
                                {
                                    "contentType": "Offer",
                                    "mapConfig": json.dumps(
                                        {
                                            "content": {
                                                "headline": "Fresh 80% Lean Homestyle Beef Patties",
                                                "bodyCopy": "8 ct, 1.9 lb",
                                            }
                                        }
                                    ),
                                }
                            ],
                        }
                    )
                ],
            }

        adapter = KrogerPlaywrightAdCaptureAdapter(playwright_capture=fake_playwright_capture)
        result = adapter.capture_weekly_ad("01100459")

        self.assertTrue(result.success)
        self.assertEqual(result.sale_items[0].name, "Fresh 80% Lean Homestyle Beef Patties - 8 ct, 1.9 lb")
        self.assertEqual(result.sale_items[0].category, "digital-ad-offer")

    def test_playwright_adapter_prefers_digital_ad_payloads_over_promo_html(self) -> None:
        def fake_playwright_capture(
            weeklyad_url: str,
            circular_id: str | None,
            headers: dict[str, str],
            user_data_dir: str | None,
            headless: bool,
            post_load_wait_ms: int,
            browser_channel: str | None,
        ) -> dict[str, object]:
            return {
                "html": "<html><body>Save | $10 New oral GLP-1 medication now available</body></html>",
                "circular_id": None,
                "deals_status": None,
                "deals_body": "",
                "deals_error": "",
                "digital_ad_bodies": [
                    json.dumps(
                        {
                            "eventPageId": "page-1",
                            "contents": [
                                {
                                    "contentType": "Offer",
                                    "mapConfig": json.dumps(
                                        {
                                            "content": {
                                                "headline": "Tyson Family Pack Frozen Chicken",
                                                "bodyCopy": "Select Varieties, 40-64 oz",
                                            }
                                        }
                                    ),
                                }
                            ],
                        }
                    )
                ],
            }

        adapter = KrogerPlaywrightAdCaptureAdapter(playwright_capture=fake_playwright_capture)
        result = adapter.capture_weekly_ad("01100459")

        self.assertTrue(result.success)
        self.assertEqual(
            result.sale_items[0].name,
            "Tyson Family Pack Frozen Chicken - Select Varieties, 40-64 oz",
        )
        self.assertEqual(adapter.last_stats["parsed_from_api_items"], 1)


if __name__ == "__main__":
    unittest.main()
