import json
import tempfile
import unittest
from pathlib import Path

from scripts.refresh_live_deals_fixture import convert_live_deals_to_ad_fixture


class RefreshLiveDealsFixtureTests(unittest.TestCase):
    def test_convert_live_deals_to_ad_fixture(self) -> None:
        payload = {
            "data": {
                "shoppableWeeklyDeals": {
                    "ads": [
                        {
                            "mainlineCopy": "Chicken Breast",
                            "underlineCopy": "2 lb Package",
                            "salePrice": 1.99,
                            "retailPrice": 3.99,
                        },
                        {
                            "mainlineCopy": "Ground Beef",
                            "underlineCopy": "16 oz Package",
                            "salePrice": None,
                            "retailPrice": 5.99,
                        },
                        {
                            "mainlineCopy": "Chicken Breast",
                            "underlineCopy": "2 lb Package",
                            "salePrice": 1.99,
                            "retailPrice": 3.99,
                        },
                    ]
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            src = Path(tmp_dir) / "live-deals.json"
            out = Path(tmp_dir) / "ad-live.json"
            src.write_text(json.dumps(payload))

            count = convert_live_deals_to_ad_fixture(src=src, dest=out)
            self.assertEqual(count, 2)

            fixture = json.loads(out.read_text())
            self.assertEqual(len(fixture), 2)
            self.assertEqual(fixture[0]["name"], "Chicken Breast - 2 lb Package")
            self.assertEqual(fixture[0]["price_text"], "$1.99")
            self.assertEqual(fixture[0]["category"], "shoppable-weekly-deals")


if __name__ == "__main__":
    unittest.main()
