import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.run_weekly_plan import _build_ad_adapter, _group_meals_by_protein, _meal_prefix_and_price


class RunWeeklyPlanCliTests(unittest.TestCase):
    def test_group_meals_by_protein_clusters_same_proteins(self) -> None:
        meal1 = SimpleNamespace(candidate=SimpleNamespace(protein="chicken"))
        meal2 = SimpleNamespace(candidate=SimpleNamespace(protein="beef"))
        meal3 = SimpleNamespace(candidate=SimpleNamespace(protein="chicken"))
        meal4 = SimpleNamespace(candidate=SimpleNamespace(protein="beef"))
        result = SimpleNamespace(meals=[meal1, meal2, meal3, meal4])
        grouped = _group_meals_by_protein(result)
        proteins = [meal.candidate.protein for meal in grouped]
        self.assertEqual(proteins, ["chicken", "chicken", "beef", "beef"])

    def test_meal_prefix_prefers_protein_aligned_sale_match(self) -> None:
        candidate = SimpleNamespace(
            sale_item_matches=("tomato", "turkey"),
            protein="turkey",
        )
        item = SimpleNamespace(candidate=candidate)
        main, price = _meal_prefix_and_price(
            result=SimpleNamespace(),
            item=item,
            sale_price_lookup={"tomato": "2 for $4", "turkey breast": "$12.49", "turkey": "$12.49"},
        )
        self.assertEqual(main, "Turkey")
        self.assertEqual(price, "$12.49")

    def test_build_playwright_ad_adapter_accepts_browser_session_options(self) -> None:
        adapter = _build_ad_adapter(
            location_id="01100459",
            use_failed_capture=False,
            ad_fixture_path=None,
            ad_mode="playwright",
            kroger_browser_profile_dir="/tmp/kroger-profile",
            kroger_browser_headless=False,
            kroger_browser_post_load_wait_ms=9000,
            kroger_browser_channel="chrome",
        )

        config = adapter._config
        self.assertEqual(config.browser_profile_dir, "/tmp/kroger-profile")
        self.assertFalse(config.browser_headless)
        self.assertEqual(config.browser_post_load_wait_ms, 9000)
        self.assertEqual(config.browser_channel, "chrome")

    def test_cli_replay_captures_dir_returns_stats(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            captures_root = Path(tmp_dir)
            (captures_root / "ad").mkdir(parents=True, exist_ok=True)
            (captures_root / "recipe").mkdir(parents=True, exist_ok=True)
            (captures_root / "ad" / "ad1.txt").write_text("Chicken Breast - $1.99/lb")
            (captures_root / "recipe" / "r1.txt").write_text(
                """
                <script type="application/ld+json">
                {"@context":"https://schema.org","@type":"Recipe","name":"Replay",
                "recipeCuisine":"American","recipeIngredient":["beef"],
                "aggregateRating":{"ratingValue":"4.2","ratingCount":"80"}}
                </script>
                """
            )
            cmd = [
                "python3",
                "-m",
                "scripts.run_weekly_plan",
                "--replay-captures-dir",
                str(captures_root),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["replay_only"])
            self.assertEqual(payload["ad"]["files_scanned"], 1)
            self.assertEqual(payload["recipe"]["files_scanned"], 1)
            self.assertIn("files_with_non_recipe_jsonld", payload["recipe"])

    def test_cli_validate_only_succeeds_with_fixture_inputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--validate-only",
            "--search-mode",
            "fixture",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["validate_only"])

    def test_cli_validate_only_fails_with_invalid_recipe_fixture(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            invalid_fixture = Path(tmp_dir) / "invalid.json"
            invalid_fixture.write_text(json.dumps({"bad": "shape"}))
            cmd = [
                "python3",
                "-m",
                "scripts.run_weekly_plan",
                "--validate-only",
                "--search-mode",
                "fixture",
                "--recipe-fixture",
                str(invalid_fixture),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Recipe fixture must be a JSON list", completed.stderr + completed.stdout)

    def test_cli_returns_ten_meals_from_fixtures(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "10",
        ]

        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["meal_count"], 10)
        self.assertFalse(payload["used_manual_fallback"])
        self.assertGreaterEqual(len(payload["meals"]), 10)
        self.assertIn("diagnostics", payload)

    def test_cli_uses_manual_fallback_on_simulated_failure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--simulate-ad-failure",
            "--manual-fallback-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "10",
        ]

        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["meal_count"], 10)
        self.assertTrue(payload["used_manual_fallback"])

    def test_cli_pretty_mode_prints_progress_to_stderr(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "10",
            "--pretty",
        ]

        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["meal_count"], 10)
        self.assertIn("[1/5] Preparing adapters", completed.stderr)
        self.assertIn("[5/5] Done", completed.stderr)

    def test_cli_pretty_summary_includes_exclusion_breakdown(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "10",
            "--pretty",
            "--pretty-summary",
        ]

        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)

        self.assertIn("summary", payload)
        self.assertIsNotNone(payload["summary"])
        self.assertIn("excluded_by_reason", payload["summary"])
        self.assertIn("excluded_excluded_ingredient", completed.stderr)

    def test_cli_can_save_run_output_to_runs_dir(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            cmd = [
                "python3",
                "-m",
                "scripts.run_weekly_plan",
                "--recipe-fixture",
                str(root / "fixtures" / "recipes.sample.json"),
                "--ad-fixture",
                str(root / "fixtures" / "ad.sample.json"),
                "--target-count",
                "10",
                "--save-run",
                "--runs-dir",
                tmp_dir,
            ]
            subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
            files = list(Path(tmp_dir).glob("weekly-plan-*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text())
            self.assertEqual(payload["meal_count"], 10)

    def test_cli_requires_recipe_fixture_in_fixture_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--search-mode",
            "fixture",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--recipe-fixture is required", completed.stderr + completed.stdout)

    def test_web_mode_can_fallback_to_fixture_when_enabled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--search-mode",
            "web",
            "--web-fallback-to-fixture",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "10",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)
        self.assertIn("used_recipe_fallback", payload)

    def test_cli_accepts_web_ad_mode_with_simulated_failure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--ad-mode",
            "web",
            "--simulate-ad-failure",
            "--manual-fallback-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--target-count",
            "10",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["used_manual_fallback"])

    def test_cli_accepts_http_recording_flag(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            cmd = [
                "python3",
                "-m",
                "scripts.run_weekly_plan",
                "--recipe-fixture",
                str(root / "fixtures" / "recipes.sample.json"),
                "--ad-fixture",
                str(root / "fixtures" / "ad.sample.json"),
                "--record-http-dir",
                tmp_dir,
                "--target-count",
                "10",
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["meal_count"], 10)

    def test_cli_record_metadata_writes_jsonl_index(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            cmd = [
                "python3",
                "-m",
                "scripts.run_weekly_plan",
                "--search-mode",
                "web",
                "--ad-mode",
                "web",
                "--simulate-ad-failure",
                "--recipe-fixture",
                str(root / "fixtures" / "recipes.sample.json"),
                "--manual-fallback-fixture",
                str(root / "fixtures" / "ad.sample.json"),
                "--record-http-dir",
                tmp_dir,
                "--record-metadata",
                "--target-count",
                "10",
            ]
            subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
            metadata_file = Path(tmp_dir) / "captures.jsonl"
            self.assertTrue(metadata_file.exists())

    def test_cli_meal_lines_output_format(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "3",
            "--output-format",
            "meal-lines",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        self.assertIn("Weeknight Chicken Pasta(allrecipes - 4.7)", completed.stdout)
        self.assertIn("https://allrecipes.com/r/6", completed.stdout)

    def test_cli_meal_markdown_output_format(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "2",
            "--output-format",
            "meal-markdown",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        self.assertIn("- [", completed.stdout)
        self.assertIn("](https://", completed.stdout)

    def test_cli_accepts_custom_planner_config(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "planner.json"
            config_path.write_text(
                json.dumps(
                    {
                        "min_rating": 4.5,
                        "max_prep_minutes": 45,
                        "max_per_protein": 3,
                        "max_per_cuisine": 4,
                        "min_trusted_ratio": 0.3,
                    }
                )
            )
            cmd = [
                "python3",
                "-m",
                "scripts.run_weekly_plan",
                "--recipe-fixture",
                str(root / "fixtures" / "recipes.sample.json"),
                "--ad-fixture",
                str(root / "fixtures" / "ad.sample.json"),
                "--planner-config",
                str(config_path),
                "--target-count",
                "10",
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
            payload = json.loads(completed.stdout)
            self.assertIn("diagnostics", payload)

    def test_cli_quality_gate_passes_with_default_fixture(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "10",
            "--quality-gate",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=root)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["meal_count"], 10)

    def test_cli_quality_gate_fails_when_thresholds_too_strict(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            "python3",
            "-m",
            "scripts.run_weekly_plan",
            "--recipe-fixture",
            str(root / "fixtures" / "recipes.sample.json"),
            "--ad-fixture",
            str(root / "fixtures" / "ad.sample.json"),
            "--target-count",
            "10",
            "--quality-gate",
            "--quality-min-meals",
            "11",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("quality_gate_failed", completed.stderr + completed.stdout)


if __name__ == "__main__":
    unittest.main()
