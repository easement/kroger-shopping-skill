from __future__ import annotations

import argparse
import json
from pathlib import Path


def _price_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"${float(value):.2f}"
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("$"):
        return text
    try:
        return f"${float(text):.2f}"
    except ValueError:
        return f"${text}"


def convert_live_deals_to_ad_fixture(src: Path, dest: Path) -> int:
    payload = json.loads(src.read_text())
    ads = (((payload.get("data") or {}).get("shoppableWeeklyDeals") or {}).get("ads") or [])

    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ad in ads:
        if not isinstance(ad, dict):
            continue
        main = str(ad.get("mainlineCopy") or "").strip()
        if not main:
            continue
        under = str(ad.get("underlineCopy") or "").strip()
        name = f"{main} - {under}" if under else main

        price = _price_text(ad.get("salePrice"))
        if price is None:
            price = _price_text(ad.get("retailPrice"))
        if price is None:
            continue

        dedupe_key = (name.lower(), price.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        items.append(
            {
                "name": name,
                "price_text": price,
                "category": "shoppable-weekly-deals",
            }
        )

    dest.write_text(json.dumps(items, indent=2))
    return len(items)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Kroger live deals JSON to ad fixture list")
    parser.add_argument("--input", default="fixtures/live-deals.json")
    parser.add_argument("--output", default="fixtures/ad.live.from-deals.json")
    args = parser.parse_args()

    src = Path(args.input)
    dest = Path(args.output)
    if not src.exists():
        raise ValueError(f"Input file not found: {src}")

    item_count = convert_live_deals_to_ad_fixture(src=src, dest=dest)
    print(json.dumps({"status": "ok", "output": str(dest), "items": item_count}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
