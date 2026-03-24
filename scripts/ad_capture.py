from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


DEFAULT_LOCATION_ID = "01100459"


@dataclass(frozen=True)
class SaleItem:
    name: str
    price_text: str
    category: str


@dataclass(frozen=True)
class AdCaptureResult:
    success: bool
    location_id: str
    sale_items: tuple[SaleItem, ...]
    source: str
    message: str = ""


class AdCaptureAdapter(Protocol):
    def capture_weekly_ad(self, location_id: str) -> AdCaptureResult:
        ...


class StaticAdCaptureAdapter:
    """
    Simple adapter for local development and tests.
    """

    def __init__(self, result: AdCaptureResult) -> None:
        self._result = result

    def capture_weekly_ad(self, location_id: str) -> AdCaptureResult:
        if self._result.location_id != location_id and self._result.location_id:
            return AdCaptureResult(
                success=False,
                location_id=location_id,
                sale_items=(),
                source="static",
                message="No fixture data for requested location",
            )

        return self._result


def build_manual_fallback_result(
    manual_items: list[dict[str, str]],
    location_id: str = DEFAULT_LOCATION_ID,
) -> AdCaptureResult:
    sale_items = tuple(
        SaleItem(
            name=item.get("name", "").strip(),
            price_text=item.get("price_text", "").strip(),
            category=item.get("category", "").strip() or "unknown",
        )
        for item in manual_items
        if item.get("name")
    )

    return AdCaptureResult(
        success=True,
        location_id=location_id,
        sale_items=sale_items,
        source="manual-fallback",
    )
