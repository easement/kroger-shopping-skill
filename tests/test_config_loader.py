import json
import tempfile
import unittest
from pathlib import Path

from scripts.config_loader import load_planner_config


class ConfigLoaderTests(unittest.TestCase):
    def test_loads_default_config_when_path_missing(self) -> None:
        config = load_planner_config(None)
        self.assertEqual(config.min_rating, 4.0)
        self.assertEqual(config.max_prep_minutes, 45)

    def test_loads_config_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "planner.json"
            path.write_text(
                json.dumps(
                    {
                        "min_rating": 4.2,
                        "max_prep_minutes": 35,
                        "max_per_protein": 2,
                        "max_per_cuisine": 3,
                        "min_trusted_ratio": 0.5,
                    }
                )
            )
            config = load_planner_config(str(path))
            self.assertEqual(config.min_rating, 4.2)
            self.assertEqual(config.max_prep_minutes, 35)
            self.assertEqual(config.max_per_protein, 2)
            self.assertEqual(config.max_per_cuisine, 3)
            self.assertEqual(config.max_foodnetwork_per_protein, 2)
            self.assertEqual(config.min_non_foodnetwork_count, 4)
            self.assertEqual(config.min_trusted_ratio, 0.5)


if __name__ == "__main__":
    unittest.main()
