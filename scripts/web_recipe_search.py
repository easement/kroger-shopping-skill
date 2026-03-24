from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from scripts.ad_capture import SaleItem
from scripts.recipe_search import RecipeDocument, RecipeSearchAdapter


FetchText = Callable[[str], str]

USER_AGENT = "Mozilla/5.0 (compatible; GroceryWeeklyMenuSkill/1.0)"


def default_fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=12) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="ignore")


def _extract_rss_links(xml: str) -> list[str]:
    links = re.findall(r"<link>(https?://[^<]+)</link>", xml)
    unique: list[str] = []
    for link in links:
        if "bing.com/search?" in link:
            continue
        if link not in unique:
            unique.append(link)
    return unique


def _extract_json_ld_blocks(html: str) -> list[str]:
    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    return re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL)


def _to_minutes(total_time: str) -> int:
    if not total_time:
        return 45
    match_hours = re.search(r"(\d+)H", total_time)
    match_minutes = re.search(r"(\d+)M", total_time)
    hours = int(match_hours.group(1)) if match_hours else 0
    minutes = int(match_minutes.group(1)) if match_minutes else 0
    total = hours * 60 + minutes
    return total if total > 0 else 45


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _parse_recipe_json_ld(payload: object, url: str) -> RecipeDocument | None:
    if isinstance(payload, list):
        for item in payload:
            parsed = _parse_recipe_json_ld(item, url)
            if parsed:
                return parsed
        return None

    if not isinstance(payload, dict):
        return None

    node_type = payload.get("@type")
    type_list = node_type if isinstance(node_type, list) else [node_type]
    if "Recipe" not in [str(item) for item in type_list]:
        graph = payload.get("@graph")
        if graph is not None:
            return _parse_recipe_json_ld(graph, url)
        return None

    aggregate = payload.get("aggregateRating") or {}
    try:
        rating = float(aggregate.get("ratingValue"))
        vote_count = int(float(aggregate.get("ratingCount") or aggregate.get("reviewCount") or 0))
    except (TypeError, ValueError):
        return None

    if vote_count <= 0:
        return None

    cuisine_values = _as_list(payload.get("recipeCuisine"))
    cuisine = cuisine_values[0] if cuisine_values else "Unknown"
    ingredients = tuple(_as_list(payload.get("recipeIngredient")))
    title = str(payload.get("name") or "Unknown Recipe")
    total_time = _to_minutes(str(payload.get("totalTime") or ""))

    protein = "unknown"
    joined_ingredients = " | ".join(item.lower() for item in ingredients)
    for token in ("chicken", "beef", "pork", "turkey", "lamb"):
        if token in joined_ingredients:
            protein = token
            break

    return RecipeDocument(
        title=title,
        url=url,
        cuisine=cuisine,
        protein=protein,
        ingredients=ingredients,
        rating=rating,
        vote_count=vote_count,
        prep_minutes=total_time,
        healthy=True,
    )


@dataclass(frozen=True)
class WebSearchConfig:
    max_links: int = 20
    trusted_domains: tuple[str, ...] = (
        "allrecipes.com",
        "foodnetwork.com",
        "eatingwell.com",
        "delish.com",
        "epicurious.com",
    )


class WebRecipeSearchAdapter(RecipeSearchAdapter):
    def __init__(self, config: WebSearchConfig | None = None, fetch_text: FetchText | None = None) -> None:
        self._config = config or WebSearchConfig()
        self._fetch_text = fetch_text or default_fetch_text

    def _build_query(self, sale_items: tuple[SaleItem, ...]) -> str:
        anchors = [item.name for item in sale_items[:3]]
        anchor_text = " ".join(anchors) if anchors else "grocery sale"
        domains = " OR ".join(f"site:{domain}" for domain in self._config.trusted_domains[:3])
        return f"{anchor_text} healthy easy recipe rating reviews {domains}"

    def _search_links(self, query: str) -> list[str]:
        url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"
        xml = self._fetch_text(url)
        links = _extract_rss_links(xml)
        return links[: self._config.max_links]

    def _parse_recipe_page(self, url: str) -> RecipeDocument | None:
        html = self._fetch_text(url)
        for block in _extract_json_ld_blocks(html):
            try:
                payload = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            parsed = _parse_recipe_json_ld(payload, url)
            if parsed:
                return parsed
        return None

    def search(self, sale_items: tuple[SaleItem, ...]) -> list[RecipeDocument]:
        query = self._build_query(sale_items)
        links = self._search_links(query)
        docs: list[RecipeDocument] = []
        for link in links:
            try:
                parsed = self._parse_recipe_page(link)
            except Exception:
                continue
            if parsed:
                docs.append(parsed)
        return docs
