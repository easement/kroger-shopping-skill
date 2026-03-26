from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.kroger_web_capture import _extract_sale_items_from_html, _extract_sale_items_from_initial_state
from scripts.kroger_web_capture import _extract_sale_items_from_shoppable_weekly_deals
from scripts.web_recipe_search import _extract_json_ld_blocks, _parse_recipe_json_ld
import json


@dataclass(frozen=True)
class ReplayStats:
    files_scanned: int
    files_parsed: int
    items_extracted: int
    files_with_signal: int = 0
    files_with_non_recipe_jsonld: int = 0


def replay_ad_capture_dir(path: str) -> ReplayStats:
    directory = Path(path)
    files = [file for file in directory.glob("*.txt") if file.is_file()]
    files_parsed = 0
    items_extracted = 0
    files_with_signal = 0

    for file in files:
        html = file.read_text(errors="ignore")
        lowered = html.lower()

        has_weeklyad_signal = "__INITIAL_STATE__" in html or "weeklyad" in lowered
        has_shoppable_deals_signal = "shoppableweeklydeals" in lowered
        if has_weeklyad_signal or has_shoppable_deals_signal:
            files_with_signal += 1

        items = _extract_sale_items_from_html(html)
        if not items and "__INITIAL_STATE__" in html:
            items = _extract_sale_items_from_initial_state(html)

        if not items and has_shoppable_deals_signal:
            try:
                payload = json.loads(html)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                items = _extract_sale_items_from_shoppable_weekly_deals(payload)
        if items:
            files_parsed += 1
            items_extracted += len(items)

    return ReplayStats(
        files_scanned=len(files),
        files_parsed=files_parsed,
        items_extracted=items_extracted,
        files_with_signal=files_with_signal,
        files_with_non_recipe_jsonld=0,
    )


def replay_recipe_capture_dir(path: str) -> ReplayStats:
    directory = Path(path)
    files = [file for file in directory.glob("*.txt") if file.is_file()]
    files_parsed = 0
    items_extracted = 0
    files_with_signal = 0
    files_with_non_recipe_jsonld = 0

    for file in files:
        html = file.read_text(errors="ignore")
        blocks = _extract_json_ld_blocks(html)
        if blocks:
            files_with_signal += 1
        parsed_any = False
        extracted_for_file = 0
        saw_non_recipe = False
        for block in blocks:
            try:
                payload = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            recipe = _parse_recipe_json_ld(payload, f"file://{file.name}")
            if recipe:
                parsed_any = True
                extracted_for_file += 1
            elif isinstance(payload, dict):
                node_type = payload.get("@type")
                type_list = node_type if isinstance(node_type, list) else [node_type]
                if any(t and str(t) != "Recipe" for t in type_list):
                    saw_non_recipe = True
                if payload.get("@graph"):
                    saw_non_recipe = True
        if saw_non_recipe:
            files_with_non_recipe_jsonld += 1
        if parsed_any:
            files_parsed += 1
            items_extracted += extracted_for_file

    return ReplayStats(
        files_scanned=len(files),
        files_parsed=files_parsed,
        items_extracted=items_extracted,
        files_with_signal=files_with_signal,
        files_with_non_recipe_jsonld=files_with_non_recipe_jsonld,
    )
