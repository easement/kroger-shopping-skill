from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from scripts.ad_capture import AdCaptureResult, SaleItem


FetchText = Callable[[str, dict[str, str]], str]

USER_AGENT = "Mozilla/5.0 (compatible; GroceryWeeklyMenuSkill/1.0)"


def default_fetch_text(url: str, headers: dict[str, str]) -> str:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=12) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="ignore")


def build_x_active_modality_cookie(location_id: str) -> str:
    payload = {
        "type": "PICKUP",
        "locationId": location_id,
        "source": "FALLBACK_ACTIVE_MODALITY_COOKIE",
        "createdDate": 1774358019738,
    }
    return json.dumps(payload, separators=(",", ":"))


def _extract_sale_items_from_html(html: str) -> tuple[SaleItem, ...]:
    # Heuristic parser for fixture/testing HTML and simple promo cards:
    # "Chicken Breast - $1.99/lb"
    pattern = r"([A-Za-z][A-Za-z0-9\s&'\-]+?)\s*-\s*(\$\d+(?:\.\d{2})?(?:/[A-Za-z]+)?)"
    matches = re.findall(pattern, html)
    items: list[SaleItem] = []
    for name, price in matches:
        normalized_name = name.strip()
        if not normalized_name:
            continue
        items.append(
            SaleItem(
                name=normalized_name,
                price_text=price.strip(),
                category="unknown",
            )
        )
    return tuple(items)


@dataclass(frozen=True)
class KrogerWebCaptureConfig:
    base_url: str = "https://www.kroger.com/weeklyad"
    max_items: int = 25


class KrogerWebAdCaptureAdapter:
    def __init__(
        self,
        config: KrogerWebCaptureConfig | None = None,
        fetch_text: FetchText | None = None,
    ) -> None:
        self._config = config or KrogerWebCaptureConfig()
        self._fetch_text = fetch_text or default_fetch_text

    def _build_headers(self, location_id: str) -> dict[str, str]:
        cookie_value = build_x_active_modality_cookie(location_id=location_id)
        return {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Cookie": f"x-active-modality={quote_plus(cookie_value)}",
        }

    def capture_weekly_ad(self, location_id: str) -> AdCaptureResult:
        headers = self._build_headers(location_id=location_id)
        try:
            html = self._fetch_text(self._config.base_url, headers)
        except Exception as error:
            return AdCaptureResult(
                success=False,
                location_id=location_id,
                sale_items=(),
                source="kroger-web",
                message=f"request_failed:{error}",
            )

        parsed = _extract_sale_items_from_html(html)
        if not parsed:
            return AdCaptureResult(
                success=False,
                location_id=location_id,
                sale_items=(),
                source="kroger-web",
                message="no_sale_items_parsed",
            )

        return AdCaptureResult(
            success=True,
            location_id=location_id,
            sale_items=parsed[: self._config.max_items],
            source="kroger-web",
        )
