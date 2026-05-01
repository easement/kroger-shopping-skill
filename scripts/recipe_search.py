from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Protocol
from urllib.parse import urlparse

from scripts.ad_capture import SaleItem
from scripts.menu_planner import RecipeCandidate

SALE_MATCH_ANCHORS = (
    "chicken breast",
    "chicken breasts",
    "chicken wing",
    "chicken wings",
    "ground beef",
    "beef patties",
    "beef patty",
    "pork butt",
    "pork shoulder",
    "pork tenderloin",
    "pork chop",
    "pork chops",
    "ribs",
    "shrimp",
    "tuna",
    "salmon",
    "sausage",
    "chorizo",
    "ham",
    "turkey",
    "lamb",
)

BROAD_SALE_MATCH_ANCHORS = {
    "beef",
    "chicken",
    "pork",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def sale_item_recipe_anchors(sale_item_name: str) -> tuple[str, ...]:
    normalized = _normalize_text(sale_item_name)
    normalized = normalized.replace("chicken of the sea", "")
    anchors = [anchor for anchor in SALE_MATCH_ANCHORS if _contains_phrase(normalized, anchor)]
    if _contains_phrase(normalized, "chicken") and _contains_phrase(normalized, "wings"):
        anchors.append("chicken wings")
    if _contains_phrase(normalized, "beef") and (
        _contains_phrase(normalized, "patties") or _contains_phrase(normalized, "patty")
    ):
        anchors.extend(["beef patties", "ground beef"])
    if _contains_phrase(normalized, "pork") and _contains_phrase(normalized, "butt"):
        anchors.append("pork butt")
    if _contains_phrase(normalized, "pork") and _contains_phrase(normalized, "shoulder"):
        anchors.append("pork shoulder")

    # Only use broad protein anchors when the ad did not identify a different cut.
    for anchor in BROAD_SALE_MATCH_ANCHORS:
        has_specific_anchor = any(item.startswith(anchor) for item in anchors)
        if not has_specific_anchor and _contains_phrase(normalized, anchor):
            anchors.append(anchor)

    return tuple(dict.fromkeys(anchors))


@dataclass(frozen=True)
class RecipeDocument:
    title: str
    url: str
    cuisine: str
    protein: str
    ingredients: tuple[str, ...]
    rating: float
    vote_count: int
    prep_minutes: int
    healthy: bool
    extraction_method: str = "unknown"
    extraction_confidence: float = 1.0


class RecipeSearchAdapter(Protocol):
    def search(self, sale_items: tuple[SaleItem, ...]) -> list[RecipeDocument]:
        ...


def _extract_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        return netloc[4:]
    return netloc


def _sale_matches_for_doc(doc: RecipeDocument, sale_item_names: list[str]) -> tuple[str, ...]:
    joined = _normalize_text(" | ".join([doc.title, *doc.ingredients]))
    matches: list[str] = []
    for item in sale_item_names:
        normalized_item = _normalize_text(item)
        if normalized_item and normalized_item in joined:
            matches.append(item)
            continue
        sale_anchor_matches = [anchor for anchor in sale_item_recipe_anchors(item) if _contains_phrase(joined, anchor)]
        if sale_anchor_matches:
            matches.append(item)
    return tuple(dict.fromkeys(matches))


def documents_to_candidates(
    docs: list[RecipeDocument],
    sale_items: tuple[SaleItem, ...],
) -> list[RecipeCandidate]:
    sale_item_names = [item.name for item in sale_items]
    candidates: list[RecipeCandidate] = []

    for doc in docs:
        sale_matches = _sale_matches_for_doc(doc, sale_item_names)
        candidates.append(
            RecipeCandidate(
                title=doc.title,
                url=doc.url,
                source_domain=_extract_domain(doc.url),
                cuisine=doc.cuisine,
                protein=doc.protein,
                ingredients=doc.ingredients,
                rating=doc.rating,
                vote_count=doc.vote_count,
                prep_minutes=doc.prep_minutes,
                healthy=doc.healthy,
                sale_item_matches=sale_matches,
                extraction_confidence=doc.extraction_confidence,
            )
        )

    return candidates


class StaticRecipeSearchAdapter:
    """
    Fixture-based adapter for deterministic local tests.
    """

    def __init__(self, docs: list[RecipeDocument]) -> None:
        self._docs = docs

    def search(self, sale_items: tuple[SaleItem, ...]) -> list[RecipeDocument]:
        return self._docs


class JsonFixtureRecipeSearchAdapter:
    """
    Loads recipe documents from a JSON fixture file.
    """

    def __init__(self, fixture_path: str) -> None:
        self._fixture_path = Path(fixture_path)

    def _validate_item(self, item: object, index: int) -> dict[str, object]:
        if not isinstance(item, dict):
            raise ValueError(f"Recipe fixture item at index {index} must be an object")
        required_fields = [
            "title",
            "url",
            "cuisine",
            "protein",
            "rating",
            "vote_count",
            "prep_minutes",
            "healthy",
        ]
        missing = [field for field in required_fields if field not in item]
        if missing:
            raise ValueError(f"Recipe fixture item at index {index} missing fields: {missing}")
        return item

    def search(self, sale_items: tuple[SaleItem, ...]) -> list[RecipeDocument]:
        payload = json.loads(self._fixture_path.read_text())
        if not isinstance(payload, list):
            raise ValueError("Recipe fixture must be a JSON list")
        docs: list[RecipeDocument] = []

        for index, raw_item in enumerate(payload):
            item = self._validate_item(raw_item, index)
            docs.append(
                RecipeDocument(
                    title=str(item["title"]),
                    url=str(item["url"]),
                    cuisine=str(item["cuisine"]),
                    protein=str(item["protein"]),
                    ingredients=tuple(item.get("ingredients", [])),
                    rating=float(item["rating"]),
                    vote_count=int(item["vote_count"]),
                    prep_minutes=int(item["prep_minutes"]),
                    healthy=bool(item["healthy"]),
                    extraction_method=str(item.get("extraction_method") or "fixture"),
                    extraction_confidence=float(item.get("extraction_confidence", 1.0)),
                )
            )

        return docs
