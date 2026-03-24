import unittest

from scripts.kroger_web_capture import (
    KrogerWebAdCaptureAdapter,
    build_x_active_modality_cookie,
)


class KrogerWebCaptureTests(unittest.TestCase):
    def test_build_cookie_contains_location_id(self) -> None:
        cookie = build_x_active_modality_cookie("01100459")
        self.assertIn('"locationId":"01100459"', cookie)
        self.assertIn('"type":"PICKUP"', cookie)

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


if __name__ == "__main__":
    unittest.main()
