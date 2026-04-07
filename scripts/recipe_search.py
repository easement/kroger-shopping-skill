from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from scripts.ad_capture import SaleItem
from scripts.menu_planner import RecipeCandidate


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
    joined = " | ".join([doc.title.lower(), *[item.lower() for item in doc.ingredients]])
    matches = [item for item in sale_item_names if item.lower() in joined]
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
