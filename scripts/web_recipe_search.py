from __future__ import annotations

from dataclasses import dataclass
import html
import json
import os
import random
import re
import subprocess
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from scripts.ad_capture import SaleItem
from scripts.recipe_search import RecipeDocument, RecipeSearchAdapter, sale_item_recipe_anchors


FetchText = Callable[[str], str]
PlaywrightFetchText = Callable[[str], str]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def default_fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=12) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="ignore")


def default_playwright_fetch_text(url: str) -> str:
    script = r"""
const { chromium } = require('playwright')

async function main() {
  const targetUrl = process.env.RECIPE_TARGET_URL || ''
  const browser = await chromium.launch({ headless: true, args: ['--disable-http2'] })
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1000)
  const html = await page.content()
  await browser.close()
  process.stdout.write(html)
}

main().catch((error) => {
  process.stderr.write(String(error))
  process.exit(1)
})
"""
    completed = subprocess.run(
        ["node", "-e", script],
        env={**dict(os.environ), "RECIPE_TARGET_URL": url},
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "playwright_recipe_fetch_failed"
        if "Cannot find module 'playwright'" in stderr:
            raise RuntimeError(
                "playwright_recipe_fetch_failed:playwright_not_installed "
                "(run: npm install playwright && npx playwright install chromium)"
            )
        raise RuntimeError(stderr)
    return completed.stdout


def _extract_rss_links(xml: str) -> list[str]:
    links = re.findall(r"<link>(https?://[^<]+)</link>", xml)
    unique: list[str] = []
    for link in links:
        normalized = html.unescape(link).strip()
        parsed = urlparse(normalized)
        # Bing RSS results sometimes include links back to Bing's own search pages
        # (often with a port like `www.bing.com:80/search?...`), which will never be
        # valid recipe pages.
        if parsed.hostname and parsed.hostname.lower().endswith("bing.com"):
            if parsed.path.lower().startswith("/search"):
                continue
        if "bing.com/search" in normalized.lower():
            continue
        if normalized not in unique:
            unique.append(normalized)
    return unique


def _extract_json_ld_blocks(html: str) -> list[str]:
    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    return re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL)


def _extract_meta_content(html_text: str, *, attr: str, value: str) -> str | None:
    pattern = rf'<meta[^>]*{attr}=["\']{re.escape(value)}["\'][^>]*content=["\']([^"\']+)["\'][^>]*>'
    match = re.search(pattern, html_text, flags=re.IGNORECASE)
    if match:
        return html.unescape(match.group(1)).strip()
    return None


def _extract_title_from_html(html_text: str) -> str:
    og_title = _extract_meta_content(html_text, attr="property", value="og:title")
    if og_title:
        return og_title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if title_match:
        raw = re.sub(r"\s+", " ", title_match.group(1)).strip()
        if raw:
            return html.unescape(raw)
    return "Unknown Recipe"


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


def _infer_protein(ingredients: tuple[str, ...], title: str) -> str:
    joined = " | ".join([title.lower(), *[item.lower() for item in ingredients]])
    protein_tokens = (
        "chicken",
        "beef",
        "pork",
        "turkey",
        "lamb",
        "salmon",
        "tuna",
        "shrimp",
        "cod",
        "tilapia",
    )
    for token in protein_tokens:
        if token in joined:
            return token
    return "unknown"


def _query_anchor_for_sale_anchor(anchor: str) -> str:
    normalized = anchor.strip().lower()
    replacements = {
        "chicken breasts": "chicken breast",
        "chicken wings": "chicken wings",
        "beef patties": "ground beef",
        "beef patty": "ground beef",
        "pork butt": "pork shoulder",
        "ribs": "ribs",
    }
    return replacements.get(normalized, normalized)


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
    protein = _infer_protein(ingredients, title)

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
        extraction_method="json-ld",
        extraction_confidence=1.0,
    )


def _parse_recipe_microdata(html_text: str, url: str) -> RecipeDocument | None:
    ingredient_meta = re.findall(
        r'<meta[^>]*itemprop=["\']recipeIngredient["\'][^>]*content=["\']([^"\']+)["\'][^>]*>',
        html_text,
        flags=re.IGNORECASE,
    )
    ingredient_text = re.findall(
        r'<[^>]*itemprop=["\']recipeIngredient["\'][^>]*>(.*?)</[^>]+>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    ingredients_raw = [*ingredient_meta, *ingredient_text]
    ingredients = tuple(
        item
        for item in (
            re.sub(r"<[^>]+>", " ", html.unescape(raw)).strip()
            for raw in ingredients_raw
        )
        if item
    )

    rating_raw = None
    rating_count_raw = None
    for token in ("ratingValue",):
        rating_raw = _extract_meta_content(html_text, attr="itemprop", value=token)
        if rating_raw:
            break
    for token in ("ratingCount", "reviewCount"):
        rating_count_raw = _extract_meta_content(html_text, attr="itemprop", value=token)
        if rating_count_raw:
            break

    if not rating_raw:
        rating_match = re.search(
            r'itemprop=["\']ratingValue["\'][^>]*>([^<]+)<',
            html_text,
            flags=re.IGNORECASE,
        )
        if rating_match:
            rating_raw = rating_match.group(1).strip()
    if not rating_count_raw:
        count_match = re.search(
            r'itemprop=["\'](?:ratingCount|reviewCount)["\'][^>]*>([^<]+)<',
            html_text,
            flags=re.IGNORECASE,
        )
        if count_match:
            rating_count_raw = count_match.group(1).strip()

    try:
        rating = float(str(rating_raw or "").strip())
        vote_count = int(float(str(rating_count_raw or "").strip()))
    except (TypeError, ValueError):
        return None

    if vote_count <= 0:
        return None

    cuisine = _extract_meta_content(html_text, attr="itemprop", value="recipeCuisine") or "Unknown"
    total_time = _extract_meta_content(html_text, attr="itemprop", value="totalTime") or ""
    title = _extract_meta_content(html_text, attr="itemprop", value="name") or _extract_title_from_html(html_text)
    protein = _infer_protein(ingredients, title)

    return RecipeDocument(
        title=title,
        url=url,
        cuisine=cuisine,
        protein=protein,
        ingredients=ingredients,
        rating=rating,
        vote_count=vote_count,
        prep_minutes=_to_minutes(total_time),
        healthy=True,
        extraction_method="microdata",
        extraction_confidence=0.9,
    )


def _parse_recipe_heuristic(html_text: str, url: str) -> RecipeDocument | None:
    title = _extract_title_from_html(html_text)

    rating_matchers = [
        r'"ratingValue"\s*:\s*"?(?P<value>[0-9]+(?:\.[0-9]+)?)"?',
        r'data-rating=["\'](?P<value>[0-9]+(?:\.[0-9]+)?)["\']',
    ]
    count_matchers = [
        r'"(?:ratingCount|reviewCount)"\s*:\s*"?(?P<value>[0-9,]+)"?',
        r'(?P<value>[0-9,]+)\s+(?:ratings|reviews)\b',
    ]

    rating_raw = None
    vote_count_raw = None
    for pattern in rating_matchers:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            rating_raw = match.group("value")
            break
    for pattern in count_matchers:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            vote_count_raw = match.group("value")
            break

    if not rating_raw or not vote_count_raw:
        return None

    try:
        rating = float(str(rating_raw).replace(",", "").strip())
        vote_count = int(float(str(vote_count_raw).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    if vote_count <= 0:
        return None

    ingredient_matches = re.findall(
        r"<(?:li|span|div)[^>]*(?:ingredient|recipe-ingredient|ingredients-item)[^>]*>(.*?)</(?:li|span|div)>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    ingredients = tuple(
        item
        for item in (
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(raw))).strip()
            for raw in ingredient_matches
        )
        if item and len(item) > 1
    )

    if len(ingredients) < 2:
        return None

    cuisine = _extract_meta_content(html_text, attr="property", value="og:site_name") or "Unknown"
    total_time = _extract_meta_content(html_text, attr="itemprop", value="totalTime") or ""
    protein = _infer_protein(ingredients, title)
    return RecipeDocument(
        title=title,
        url=url,
        cuisine=cuisine,
        protein=protein,
        ingredients=ingredients,
        rating=rating,
        vote_count=vote_count,
        prep_minutes=_to_minutes(total_time),
        healthy=True,
        extraction_method="heuristic",
        extraction_confidence=0.75,
    )


@dataclass(frozen=True)
class WebSearchConfig:
    max_links: int = 20
    random_domain_count: int = 7
    max_query_anchors: int = 5
    use_relaxed_query_fallback: bool = True
    trusted_domains: tuple[str, ...] = (
        "allrecipes.com",
        "foodnetwork.com",
        "eatingwell.com",
        "delish.com",
        "epicurious.com",
        "pinchofyum.com",
        "cookieandkate.com",
        "loveandlemons.com",
        "seriouseats.com",
        "budgetbytes.com",
        "smittenkitchen.com",
        "minimalistbaker.com",
        "halfbakedharvest.com",
        "sallysbakingaddiction.com",
        "damndelicious.net",
        "thepioneerwoman.com",
        "skinnytaste.com",
        "simplyrecipes.com",
        "gimmesomeoven.com",
        "natashaskitchen.com",
        "jocooks.com",
        "food52.com",
    )
    allowed_path_tokens: tuple[str, ...] = (
        "/r/",
        "/recipe/",
        "/recipes/",
        "/food-recipes/",
    )
    blocked_path_tokens: tuple[str, ...] = (
        "/forum",
        "/forums",
        "/article",
        "/articles",
        "/news",
        "/photos/",
        "/videos/",
        "/collections/",
    )


class WebRecipeSearchAdapter(RecipeSearchAdapter):
    def __init__(self, config: WebSearchConfig | None = None, fetch_text: FetchText | None = None) -> None:
        self._config = config or WebSearchConfig()
        self._fetch_text = fetch_text or default_fetch_text
        self.last_stats: dict[str, object] = {
            "used_relaxed_query": False,
            "selected_domains": [],
            "rss_queries": 0,
            "raw_links": 0,
            "allowed_links": 0,
            "rejected_domain": 0,
            "rejected_path": 0,
            "pages_fetched": 0,
            "pages_parsed": 0,
            "pages_failed_http": 0,
            "pages_failed_403": 0,
            "pages_failed_timeout": 0,
            "pages_no_jsonld": 0,
            "pages_non_recipe_jsonld": 0,
            "pages_recipe_without_rating": 0,
        }

    def _pick_query_anchors(self, sale_items: tuple[SaleItem, ...], *, max_anchors: int) -> list[str]:
        picked: list[str] = []
        for item in sale_items:
            for anchor in sale_item_recipe_anchors(item.name):
                query_anchor = _query_anchor_for_sale_anchor(anchor)
                if query_anchor not in picked:
                    picked.append(query_anchor)
            if len(picked) >= max_anchors:
                break

        if picked:
            return picked[:max_anchors]

        # Fallback: use a deterministic protein set to keep search on track.
        return ["chicken breast", "ground beef", "shrimp", "tuna", "sausage"][:max_anchors]

    def _build_query_for_domain(self, sale_items: tuple[SaleItem, ...], domain: str) -> str:
        anchors = self._pick_query_anchors(sale_items, max_anchors=1)
        anchor_text = anchors[0] if anchors else "chicken"
        # Keep query syntax simple so Bing RSS reliably returns results from the targeted domain.
        return f"site:{domain} {anchor_text} recipe"

    def _build_query_for_anchor_and_domain(self, anchor: str, domain: str) -> str:
        return f"site:{domain} {anchor} recipe"

    def _build_relaxed_query_for_domain(self, sale_items: tuple[SaleItem, ...], domain: str) -> str:
        anchors = self._pick_query_anchors(sale_items, max_anchors=1)
        anchor_text = anchors[0] if anchors else "chicken"
        return f"site:{domain} {anchor_text} recipe"

    def _is_allowed_link(self, link: str, *, domain_filter: str | None = None) -> bool:
        parsed = urlparse(link)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]

        allowed_domains = (domain_filter,) if domain_filter else self._config.trusted_domains
        if not any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
            self.last_stats["rejected_domain"] = int(self.last_stats["rejected_domain"]) + 1
            return False

        path = parsed.path.lower()
        if any(token in path for token in self._config.blocked_path_tokens):
            self.last_stats["rejected_path"] = int(self.last_stats["rejected_path"]) + 1
            return False
        if any(token in path for token in self._config.allowed_path_tokens):
            return True
        self.last_stats["rejected_path"] = int(self.last_stats["rejected_path"]) + 1
        return False

    def _search_links(self, query: str, *, max_links: int, domain_filter: str | None = None) -> list[str]:
        self.last_stats["rss_queries"] = int(self.last_stats["rss_queries"]) + 1
        url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"
        try:
            xml = self._fetch_text(url)
        except HTTPError as error:
            self.last_stats["pages_failed_http"] = int(self.last_stats["pages_failed_http"]) + 1
            if int(error.code) == 403:
                self.last_stats["pages_failed_403"] = int(self.last_stats["pages_failed_403"]) + 1
            return []
        except (TimeoutError, URLError):
            self.last_stats["pages_failed_timeout"] = int(self.last_stats["pages_failed_timeout"]) + 1
            return []
        except Exception:
            self.last_stats["pages_failed_http"] = int(self.last_stats["pages_failed_http"]) + 1
            return []
        links = _extract_rss_links(xml)
        self.last_stats["raw_links"] = int(self.last_stats["raw_links"]) + len(links)
        gated = [link for link in links if self._is_allowed_link(link, domain_filter=domain_filter)]
        self.last_stats["allowed_links"] = int(self.last_stats["allowed_links"]) + len(gated)
        return gated[:max_links]

    def _parse_recipe_page(self, url: str) -> RecipeDocument | None:
        self.last_stats["pages_fetched"] = int(self.last_stats["pages_fetched"]) + 1
        try:
            html = self._fetch_text(url)
        except HTTPError as error:
            self.last_stats["pages_failed_http"] = int(self.last_stats["pages_failed_http"]) + 1
            if int(error.code) == 403:
                self.last_stats["pages_failed_403"] = int(self.last_stats["pages_failed_403"]) + 1
            return None
        except (TimeoutError, URLError):
            self.last_stats["pages_failed_timeout"] = int(self.last_stats["pages_failed_timeout"]) + 1
            return None
        except Exception:
            self.last_stats["pages_failed_http"] = int(self.last_stats["pages_failed_http"]) + 1
            return None

        blocks = _extract_json_ld_blocks(html)
        if not blocks:
            parsed_microdata = _parse_recipe_microdata(html, url)
            if parsed_microdata:
                self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
                return parsed_microdata
            parsed_heuristic = _parse_recipe_heuristic(html, url)
            if parsed_heuristic:
                self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
                return parsed_heuristic
            self.last_stats["pages_no_jsonld"] = int(self.last_stats["pages_no_jsonld"]) + 1
            return None

        saw_non_recipe = False
        for block in blocks:
            try:
                payload = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            parsed = _parse_recipe_json_ld(payload, url)
            if parsed:
                self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
                return parsed
            if isinstance(payload, dict):
                node_type = payload.get("@type")
                type_list = node_type if isinstance(node_type, list) else [node_type]
                if "Recipe" not in [str(item) for item in type_list] and payload.get("@graph") is None:
                    saw_non_recipe = True
                else:
                    self.last_stats["pages_recipe_without_rating"] = int(
                        self.last_stats["pages_recipe_without_rating"]
                    ) + 1
        if saw_non_recipe:
            self.last_stats["pages_non_recipe_jsonld"] = int(self.last_stats["pages_non_recipe_jsonld"]) + 1
        parsed_microdata = _parse_recipe_microdata(html, url)
        if parsed_microdata:
            self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
            return parsed_microdata
        parsed_heuristic = _parse_recipe_heuristic(html, url)
        if parsed_heuristic:
            self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
            return parsed_heuristic
        return None

    def search(self, sale_items: tuple[SaleItem, ...]) -> list[RecipeDocument]:
        all_domains = list(self._config.trusted_domains)
        domain_count = max(1, int(self._config.random_domain_count))
        if len(all_domains) <= domain_count:
            selected_domains = all_domains
        else:
            selected_domains = random.sample(all_domains, domain_count)

        self.last_stats = {
            "used_relaxed_query": False,
            "selected_domains": selected_domains,
            "rss_queries": 0,
            "raw_links": 0,
            "allowed_links": 0,
            "rejected_domain": 0,
            "rejected_path": 0,
            "pages_fetched": 0,
            "pages_parsed": 0,
            "pages_failed_http": 0,
            "pages_failed_403": 0,
            "pages_failed_timeout": 0,
            "pages_no_jsonld": 0,
            "pages_non_recipe_jsonld": 0,
            "pages_recipe_without_rating": 0,
        }

        links: list[str] = []
        query_anchors = self._pick_query_anchors(
            sale_items,
            max_anchors=max(1, int(self._config.max_query_anchors)),
        )

        # Strict per-domain pass
        for domain in selected_domains:
            for anchor in query_anchors:
                remaining = self._config.max_links - len(links)
                if remaining <= 0:
                    break
                query = self._build_query_for_anchor_and_domain(anchor, domain)
                links.extend(self._search_links(query, max_links=remaining, domain_filter=domain))
            if len(links) >= self._config.max_links:
                break

        # Relaxed fallback if strict pass produced nothing
        if not links and self._config.use_relaxed_query_fallback:
            self.last_stats["used_relaxed_query"] = True
            for domain in selected_domains:
                for anchor in query_anchors:
                    remaining = self._config.max_links - len(links)
                    if remaining <= 0:
                        break
                    relaxed_query = self._build_query_for_anchor_and_domain(anchor, domain)
                    links.extend(
                        self._search_links(relaxed_query, max_links=remaining, domain_filter=domain)
                    )
                if len(links) >= self._config.max_links:
                    break

        # Final permissive pass: if Bing results do not include any allowed links, try parsing
        # JSON-LD from whatever pages are returned. JSON-LD parsing still enforces Recipe + rating.
        if not links:
            anchor_text = " ".join(query_anchors[:3]) if query_anchors else "easy dinner"
            # Permissive query without strict site constraint; still expects Recipe JSON-LD on destination pages.
            permissive_query = f"{anchor_text} easy recipe"
            self.last_stats["rss_queries"] = int(self.last_stats["rss_queries"]) + 1
            url = f"https://www.bing.com/search?format=rss&q={quote_plus(permissive_query)}"
            try:
                xml = self._fetch_text(url)
            except (HTTPError, TimeoutError, URLError):
                xml = ""
                self.last_stats["pages_failed_timeout"] = int(self.last_stats["pages_failed_timeout"]) + 1
            except Exception:
                xml = ""
                self.last_stats["pages_failed_http"] = int(self.last_stats["pages_failed_http"]) + 1
            raw_links = _extract_rss_links(xml) if xml else []
            self.last_stats["raw_links"] = int(self.last_stats["raw_links"]) + len(raw_links)
            # Still gate to trusted domains/paths to reduce noise and avoid fetching pages
            # that never contain Recipe JSON-LD.
            gated = [link for link in raw_links if self._is_allowed_link(link)]
            self.last_stats["allowed_links"] = int(self.last_stats["allowed_links"]) + len(gated)
            links = gated[: self._config.max_links]

        docs: list[RecipeDocument] = []
        for link in links:
            parsed = self._parse_recipe_page(link)
            if parsed:
                docs.append(parsed)
        return docs


class PlaywrightRecipeSearchAdapter(WebRecipeSearchAdapter):
    def __init__(
        self,
        config: WebSearchConfig | None = None,
        fetch_text: FetchText | None = None,
        playwright_fetch_text: PlaywrightFetchText | None = None,
    ) -> None:
        super().__init__(config=config, fetch_text=fetch_text)
        self._playwright_fetch_text = playwright_fetch_text or default_playwright_fetch_text

    def _parse_recipe_page(self, url: str) -> RecipeDocument | None:
        self.last_stats["pages_fetched"] = int(self.last_stats["pages_fetched"]) + 1
        try:
            html = self._playwright_fetch_text(url)
        except Exception:
            self.last_stats["pages_failed_http"] = int(self.last_stats["pages_failed_http"]) + 1
            return None

        blocks = _extract_json_ld_blocks(html)
        if not blocks:
            parsed_microdata = _parse_recipe_microdata(html, url)
            if parsed_microdata:
                self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
                return parsed_microdata
            parsed_heuristic = _parse_recipe_heuristic(html, url)
            if parsed_heuristic:
                self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
                return parsed_heuristic
            self.last_stats["pages_no_jsonld"] = int(self.last_stats["pages_no_jsonld"]) + 1
            return None

        saw_non_recipe = False
        for block in blocks:
            try:
                payload = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            parsed = _parse_recipe_json_ld(payload, url)
            if parsed:
                self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
                return parsed
            if isinstance(payload, dict):
                node_type = payload.get("@type")
                type_list = node_type if isinstance(node_type, list) else [node_type]
                if "Recipe" not in [str(item) for item in type_list] and payload.get("@graph") is None:
                    saw_non_recipe = True
                else:
                    self.last_stats["pages_recipe_without_rating"] = int(
                        self.last_stats["pages_recipe_without_rating"]
                    ) + 1
        if saw_non_recipe:
            self.last_stats["pages_non_recipe_jsonld"] = int(self.last_stats["pages_non_recipe_jsonld"]) + 1
        parsed_microdata = _parse_recipe_microdata(html, url)
        if parsed_microdata:
            self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
            return parsed_microdata
        parsed_heuristic = _parse_recipe_heuristic(html, url)
        if parsed_heuristic:
            self.last_stats["pages_parsed"] = int(self.last_stats["pages_parsed"]) + 1
            return parsed_heuristic
        return None
