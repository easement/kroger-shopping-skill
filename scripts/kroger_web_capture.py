from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import os
import re
import socket
import subprocess
from typing import Callable
from http.cookiejar import CookieJar
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from scripts.ad_capture import AdCaptureResult, SaleItem


FetchText = Callable[[str, dict[str, str]], str]
FetchJson = Callable[[str, dict[str, str]], object]
PlaywrightCapture = Callable[
    [str, str | None, dict[str, str], str | None, bool, int, str | None],
    dict[str, object],
]

USER_AGENT = "Mozilla/5.0 (compatible; GroceryWeeklyMenuSkill/1.0)"
DEFAULT_KROGER_TIMEOUT_SECONDS = 25
DEFAULT_KROGER_FETCH_ATTEMPTS = 2
DEFAULT_BROWSER_FALLBACK_TIMEOUT_SECONDS = 70


def _is_timeout_error(error: Exception) -> bool:
    if isinstance(error, TimeoutError | socket.timeout):
        return True
    if isinstance(error, URLError):
        reason = getattr(error, "reason", None)
        if isinstance(reason, TimeoutError | socket.timeout):
            return True
        if isinstance(reason, str) and "timed out" in reason.lower():
            return True
    message = str(error).lower()
    return "timed out" in message


def _fetch_with_headless_browser(url: str, headers: dict[str, str]) -> str:
    script = r"""
const { chromium } = require('playwright')

async function main() {
  const targetUrl = process.argv[2]
  const headersJson = process.argv[3] || '{}'
  const extraHeaders = JSON.parse(headersJson)

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext()
  await context.setExtraHTTPHeaders(extraHeaders)
  const page = await context.newPage()
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await page.waitForTimeout(1500)
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
        [
            "node",
            "-e",
            script,
            url,
            json.dumps(headers),
        ],
        capture_output=True,
        text=True,
        timeout=DEFAULT_BROWSER_FALLBACK_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "headless_fetch_failed"
        if "Cannot find module 'playwright'" in stderr:
            raise RuntimeError(
                "headless_fetch_failed:playwright_not_installed "
                "(run: npm install playwright && npx playwright install chromium)"
            )
        raise RuntimeError(stderr)
    return completed.stdout


def default_playwright_capture(
    weeklyad_url: str,
    circular_id: str | None,
    headers: dict[str, str],
    user_data_dir: str | None = None,
    headless: bool = True,
    post_load_wait_ms: int = 5000,
    browser_channel: str | None = None,
) -> dict[str, object]:
    script = r"""
const { chromium } = require('playwright')

function extractCircularId(html) {
  const patterns = [
    /"circularId"\s*:\s*"([0-9a-fA-F-]{36})"/i,
    /'circularId'\s*:\s*'([0-9a-fA-F-]{36})'/i,
    /filter\.circularId=([0-9a-fA-F-]{36})/i,
    /circularId=([0-9a-fA-F-]{36})(?:&|"|'|\s|$)/i
  ]
  for (const pattern of patterns) {
    const match = html.match(pattern)
    if (match && match[1]) return match[1].toLowerCase()
  }
  return null
}

function extractLocationId(headers) {
  if (headers['x-facility-id']) return String(headers['x-facility-id'])
  const cookie = String(headers.Cookie || headers.cookie || '')
  const match = cookie.match(/locationId%22%3A%22(\d+)/) || cookie.match(/"locationId":"(\d+)"/)
  return match && match[1] ? match[1] : '01100459'
}

function extractDivisionId(headers) {
  const locationId = extractLocationId(headers)
  return locationId.slice(0, 3) || '011'
}

function buildApiHeaders(headers) {
  return {
    ...headers,
    Accept: 'application/json',
    Referer: 'https://www.kroger.com/weeklyad',
    Origin: 'https://www.kroger.com'
  }
}

async function fetchDigitalAdPages(context, circularBodies, locationId, headers) {
  const bodies = []
  for (const body of circularBodies) {
    let payload = null
    try {
      payload = JSON.parse(body)
    } catch (_) {
      continue
    }
    const circulars = Array.isArray(payload.data) ? payload.data : []
    const classic =
      circulars.find((item) => item.eventId && item.circularType === 'print') ||
      circulars.find((item) => {
        const tags = Array.isArray(item.tags) ? item.tags : []
        return item.eventId && tags.includes('CLASSIC_VIEW')
      })
    if (!classic) continue

    const eventId = classic.eventId
    const indexUrl = `https://oms-kroger-webapp-da-classic-api-prod.przone.net/api/dacs/${eventId}?location=${locationId}`
    let indexPayload = null
    try {
      const response = await context.request.get(indexUrl, {
        headers: buildApiHeaders(headers),
        timeout: 30000
      })
      indexPayload = await response.json()
    } catch (_) {
      continue
    }
    const pages = Array.isArray(indexPayload.pages) ? indexPayload.pages : []
    for (const pageInfo of pages) {
      if (!pageInfo || !pageInfo.eventPageId) continue
      const pageUrl = `https://oms-kroger-webapp-da-classic-api-prod.przone.net/api/dacs/${eventId}/pages/${pageInfo.eventPageId}?location=${locationId}`
      try {
        const response = await context.request.get(pageUrl, {
          headers: buildApiHeaders(headers),
          timeout: 30000
        })
        bodies.push(await response.text())
      } catch (_) {
        // Continue with other pages if one page request fails.
      }
    }
    if (bodies.length > 0) break
  }
  return bodies
}

async function fetchCircularBodies(context, headers) {
  const divisionId = extractDivisionId(headers)
  try {
    const response = await context.request.get(
      `https://api.kroger.com/digitalads/v1/circulars?filter.div=${divisionId}&filter.tags=SHOPPABLE&filter.tags=CLASSIC_VIEW`,
      {
        headers: buildApiHeaders(headers),
        timeout: 30000
      }
    )
    return [await response.text()]
  } catch (_) {
    return []
  }
}

async function dismissBlockingModals(page) {
  let dismissedAny = false
  const closeLocators = [
    page.getByRole('button', { name: /^dismiss$/i }).first(),
    page.getByRole('button', { name: /^close$/i }).first(),
    page.getByRole('button', { name: /close modal dialog/i }).first(),
    page.getByText('Dismiss', { exact: true }).first(),
    page.locator('button[aria-label="Close"]').first(),
    page.locator('button[aria-label*="Close modal"]').first(),
    page.locator('button').filter({ hasText: '×' }).first(),
    page.locator('button').filter({ hasText: 'x' }).first(),
    page.locator('[role="dialog"] button[aria-label*="Close"]').first(),
    page.locator('[role="dialog"] button').last()
  ]

  for (let attempt = 0; attempt < 4; attempt++) {
    let dismissedThisAttempt = false
    for (const locator of closeLocators) {
      try {
        await locator.click({ timeout: 1500 })
        await page.waitForTimeout(500)
        dismissedAny = true
        dismissedThisAttempt = true
        break
      } catch (_) {
        // Try the next close-button shape.
      }
    }
    if (!dismissedThisAttempt) {
      break
    }
  }

  try {
    await page.keyboard.press('Escape')
    await page.waitForTimeout(500)
    return true
  } catch (_) {
    return dismissedAny
  }
}

async function openWeeklyAdView(page) {
  const viewAdLocators = [
    page.getByRole('button', { name: /view ad weekly ad/i }).first(),
    page.getByRole('button', { name: /^view ad$/i }).first(),
    page.locator('button').filter({ hasText: /^View Ad$/ }).first()
  ]

  for (const locator of viewAdLocators) {
    try {
      await locator.click({ timeout: 2500 })
      await page.waitForTimeout(2500)
      return true
    } catch (_) {
      // The page may already be in ad view.
    }
  }
  return false
}

async function main() {
  const targetUrl = process.env.KROGER_WEEKLYAD_URL || ''
  const circularIdArg = process.env.KROGER_CIRCULAR_ID || ''
  const headersJson = process.env.KROGER_EXTRA_HEADERS_JSON || '{}'
  const userDataDir = process.env.KROGER_PLAYWRIGHT_USER_DATA_DIR || ''
  const headless = process.env.KROGER_PLAYWRIGHT_HEADLESS !== 'false'
  const postLoadWaitMs = Number(process.env.KROGER_PLAYWRIGHT_POST_LOAD_WAIT_MS || '5000')
  const browserChannel = process.env.KROGER_PLAYWRIGHT_BROWSER_CHANNEL || ''
  const extraHeaders = JSON.parse(headersJson)

  let browser = null
  let context = null
  const channelOption = browserChannel ? { channel: browserChannel } : {}
  if (userDataDir) {
    context = await chromium.launchPersistentContext(userDataDir, {
      headless,
      viewport: { width: 1365, height: 900 },
      locale: 'en-US',
      ...channelOption
    })
  } else {
    browser = await chromium.launch({ headless, ...channelOption })
    context = await browser.newContext({
      viewport: { width: 1365, height: 900 },
      locale: 'en-US'
    })
  }
  if (Object.keys(extraHeaders).length > 0) {
    await context.setExtraHTTPHeaders(extraHeaders)
  }
  let interceptedDealsStatus = null
  let interceptedDealsBody = ''
  let interceptedDealsError = ''
  const digitalAdBodies = []
  const circularBodies = []
  const locationId = extractLocationId(extraHeaders)
  const preFetchedCircularBodies = await fetchCircularBodies(context, extraHeaders)
  const preFetchedDigitalAdBodies = await fetchDigitalAdPages(
    context,
    preFetchedCircularBodies,
    locationId,
    extraHeaders
  )
  const page = await context.newPage()

  page.on('response', async (response) => {
    const responseUrl = response.url()
    if (responseUrl.includes('/atlas/v1/shoppable-weekly-deals/deals')) {
      if (interceptedDealsBody) return
      interceptedDealsStatus = response.status()
      try {
        interceptedDealsBody = await response.text()
      } catch (error) {
        interceptedDealsError = String(error)
      }
      return
    }
    if (responseUrl.includes('digitalads/v1/circulars')) {
      try {
        circularBodies.push(await response.text())
      } catch (_) {
        // Fall back to any DACS page responses captured separately.
      }
      return
    }
    if (responseUrl.includes('/api/dacs/') && responseUrl.includes('/pages/')) {
      try {
        digitalAdBodies.push(await response.text())
      } catch (_) {
        // Ignore single-page capture failures; other pages may still contain offers.
      }
    }
  })

  let html = ''
  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(1000)
    await dismissBlockingModals(page)
    await openWeeklyAdView(page)
    await dismissBlockingModals(page)
    await page.waitForTimeout(postLoadWaitMs)
    html = await page.content()
  } catch (error) {
    const message = String(error)
    if (!message.includes('ERR_HTTP2_PROTOCOL_ERROR')) {
      throw error
    }
    // Fallback: use Playwright request context for the same session if page nav
    // fails at HTTP/2 negotiation.
    const response = await context.request.get(targetUrl, {
      headers: extraHeaders,
      timeout: 60000
    })
    html = await response.text()
  }

  let resolvedCircularId = circularIdArg || extractCircularId(html) || ''
  let dealsStatus = interceptedDealsStatus
  let dealsBody = interceptedDealsBody
  let dealsError = interceptedDealsError
  let resolvedDigitalAdBodies = preFetchedDigitalAdBodies.length > 0 ? preFetchedDigitalAdBodies : digitalAdBodies

  if (resolvedCircularId && !dealsBody) {
    const dealsUrl = `https://www.kroger.com/atlas/v1/shoppable-weekly-deals/deals?filter.circularId=${resolvedCircularId}`
    try {
      const response = await context.request.get(dealsUrl, {
        headers: { ...extraHeaders, Accept: 'application/json' },
        timeout: 40000
      })
      dealsStatus = response.status()
      dealsBody = await response.text()
    } catch (error) {
      dealsError = String(error)
    }
  }

  if (resolvedDigitalAdBodies.length === 0 && circularBodies.length > 0) {
    resolvedDigitalAdBodies = await fetchDigitalAdPages(context, circularBodies, locationId, extraHeaders)
  }
  if (resolvedDigitalAdBodies.length === 0) {
    const fetchedCircularBodies = preFetchedCircularBodies.length > 0
      ? preFetchedCircularBodies
      : await fetchCircularBodies(context, extraHeaders)
    resolvedDigitalAdBodies = await fetchDigitalAdPages(
      context,
      fetchedCircularBodies,
      locationId,
      extraHeaders
    )
  }

  await context.close()
  if (browser) await browser.close()
  process.stdout.write(JSON.stringify({
    html,
    circular_id: resolvedCircularId || null,
    deals_status: dealsStatus,
    deals_body: dealsBody,
    deals_error: dealsError,
    digital_ad_bodies: resolvedDigitalAdBodies
  }))
}

main().catch((error) => {
  process.stderr.write(String(error))
  process.exit(1)
})
"""
    completed = subprocess.run(
        [
            "node",
            "-e",
            script,
        ],
        env={
            **dict(os.environ),
            "KROGER_WEEKLYAD_URL": weeklyad_url,
            "KROGER_CIRCULAR_ID": circular_id or "",
            "KROGER_EXTRA_HEADERS_JSON": json.dumps(headers),
            "KROGER_PLAYWRIGHT_USER_DATA_DIR": user_data_dir or "",
            "KROGER_PLAYWRIGHT_HEADLESS": "true" if headless else "false",
            "KROGER_PLAYWRIGHT_POST_LOAD_WAIT_MS": str(post_load_wait_ms),
            "KROGER_PLAYWRIGHT_BROWSER_CHANNEL": browser_channel or "",
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "playwright_capture_failed"
        if "Cannot find module 'playwright'" in stderr:
            raise RuntimeError(
                "playwright_capture_failed:playwright_not_installed "
                "(run: npm install playwright && npx playwright install chromium)"
            )
        raise RuntimeError(stderr)
    return json.loads(completed.stdout)


def default_fetch_text(url: str, headers: dict[str, str]) -> str:
    last_error: Exception | None = None
    for attempt in range(DEFAULT_KROGER_FETCH_ATTEMPTS):
        try:
            browser_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "close",
                **headers,
            }
            request = Request(url, headers=browser_headers)
            opener = build_opener(HTTPCookieProcessor(CookieJar()))
            with opener.open(request, timeout=DEFAULT_KROGER_TIMEOUT_SECONDS) as response:  # noqa: S310
                payload = response.read()
                content_encoding = str(response.headers.get("Content-Encoding", "")).lower()
                if "gzip" in content_encoding:
                    payload = gzip.decompress(payload)
                return payload.decode("utf-8", errors="ignore")
        except Exception as error:
            last_error = error
            is_last_attempt = attempt == DEFAULT_KROGER_FETCH_ATTEMPTS - 1
            if not _is_timeout_error(error):
                raise
            if is_last_attempt:
                break
    if last_error is not None:
        if _is_timeout_error(last_error):
            return _fetch_with_headless_browser(url, headers)
        raise last_error
    raise RuntimeError("default_fetch_text failed without an exception")


def default_fetch_json(url: str, headers: dict[str, str]) -> object:
    last_error: Exception | None = None
    for attempt in range(DEFAULT_KROGER_FETCH_ATTEMPTS):
        try:
            request = Request(url, headers={**headers, "Accept": "application/json"})
            with urlopen(request, timeout=DEFAULT_KROGER_TIMEOUT_SECONDS) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except Exception as error:
            last_error = error
            is_last_attempt = attempt == DEFAULT_KROGER_FETCH_ATTEMPTS - 1
            if not _is_timeout_error(error):
                raise
            if is_last_attempt:
                break
    if last_error is not None:
        raise last_error
    raise RuntimeError("default_fetch_json failed without an exception")


def build_x_active_modality_cookie(location_id: str) -> str:
    payload = {
        "type": "PICKUP",
        "locationId": location_id,
        "source": "FALLBACK_ACTIVE_MODALITY_COOKIE",
        "createdDate": 1774358019738,
    }
    return json.dumps(payload, separators=(",", ":"))


def _extract_sale_items_from_html(html: str) -> tuple[SaleItem, ...]:
    # Heuristic parser for fixture/testing HTML and simple promo cards.
    patterns = [
        # "Chicken Breast - $1.99/lb"
        r"([A-Za-z][A-Za-z0-9\s&'\-]+?)\s*-\s*(\$\d+(?:\.\d{2})?(?:/[A-Za-z]+)?)",
        # "Chicken Breast $1.99/lb"
        r"([A-Za-z][A-Za-z0-9\s&'\-]+?)\s+(\$\d+(?:\.\d{2})?(?:/[A-Za-z]+)?)",
        # JSON-ish snippets: {"name":"Chicken Breast","salePrice":"$1.99/lb"}
        r'"name"\s*:\s*"([^"]+)"[^{}]{0,180}?"salePrice"\s*:\s*"(\$\d+(?:\.\d{2})?(?:/[A-Za-z]+)?)"',
        # Escaped JSON snippets embedded in strings: \"name\":\"Chicken Breast\",\"price\":\"$1.99/lb\"
        r'\\"name\\"\s*:\s*\\"([^"\\]+)\\"[^{}]{0,240}?\\"(?:salePrice|price|promoPrice)\\"\s*:\s*\\"(\$\d+(?:\.\d{2})?(?:/[A-Za-z]+)?)\\"',
    ]

    matches: list[tuple[str, str]] = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, html, flags=re.IGNORECASE))

    seen: set[tuple[str, str]] = set()
    items: list[SaleItem] = []
    for name, price in matches:
        normalized_name = name.strip()
        if not normalized_name:
            continue
        normalized_price = price.strip()
        key = (normalized_name.lower(), normalized_price.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append(
            SaleItem(
                name=normalized_name,
                price_text=normalized_price,
                category="unknown",
            )
        )
    return tuple(items)


def _extract_sale_items_from_initial_state(html: str) -> tuple[SaleItem, ...]:
    # Pull product/price pairs from embedded JSON when available.
    # Handles escaped JSON blobs in __INITIAL_STATE__ style script payloads.
    pattern = (
        r'\\"(?:name|description|itemName)\\"\s*:\s*\\"([^"\\]+)\\"'
        r'[^{}]{0,280}?\\"(?:salePrice|price|promoPrice|offerPrice)\\"\s*:\s*\\"([^"\\]*\$\d+(?:\.\d{2})?(?:/[A-Za-z]+)?)\\"'
    )
    matches = re.findall(pattern, html, flags=re.IGNORECASE)
    items: list[SaleItem] = []
    seen: set[tuple[str, str]] = set()
    for name, price in matches:
        normalized_name = name.strip()
        normalized_price = price.strip()
        if not normalized_name or not normalized_price:
            continue
        key = (normalized_name.lower(), normalized_price.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append(
            SaleItem(
                name=normalized_name,
                price_text=normalized_price,
                category="unknown",
            )
        )
    return tuple(items)


def _try_extract_circular_id_from_html(html: str) -> str | None:
    """Best-effort UUID for the active weekly circular (embedded JSON or query strings)."""
    patterns = (
        r'"circularId"\s*:\s*"([0-9a-fA-F-]{36})"',
        r"'circularId'\s*:\s*'([0-9a-fA-F-]{36})'",
        r"filter\.circularId=([0-9a-fA-F-]{36})",
        r"circularId=([0-9a-fA-F-]{36})(?:&|\"|'|\s|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1).lower()
    return None


def _extract_heuristic_sale_anchors(html: str) -> tuple[SaleItem, ...]:
    lowered = html.lower()
    anchors = [
        "chicken",
        "beef",
        "pork",
        "turkey",
        "seafood",
        "produce",
        "dairy",
    ]
    found = [anchor for anchor in anchors if anchor in lowered]
    return tuple(SaleItem(name=anchor.title(), price_text="N/A", category="heuristic") for anchor in found)


def _as_number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        # Handle values like "$3.99" or "3.99"
        if stripped and stripped[0] in "$€£":
            stripped = stripped[1:].strip()
        if stripped:
            try:
                return float(stripped)
            except ValueError:
                return None
    return None


def _extract_sale_items_from_shoppable_weekly_deals(payload: object) -> tuple[SaleItem, ...]:
    """
    Parse the documented Atlas response shape:
      payload.data.shoppableWeeklyDeals.ads[].{mainlineCopy, underlineCopy, salePrice, retailPrice}
    """
    if not isinstance(payload, dict):
        return tuple()

    data = payload.get("data")
    if not isinstance(data, dict):
        return tuple()

    shoppable = data.get("shoppableWeeklyDeals")
    if not isinstance(shoppable, dict):
        return tuple()

    ads = shoppable.get("ads")
    if not isinstance(ads, list) or not ads:
        return tuple()

    items: list[SaleItem] = []
    seen: set[tuple[str, str]] = set()

    for ad in ads:
        if not isinstance(ad, dict):
            continue

        mainline_copy = ad.get("mainlineCopy")
        underline_copy = ad.get("underlineCopy")
        if not isinstance(mainline_copy, str) or not mainline_copy.strip():
            continue

        name = mainline_copy.strip()
        if isinstance(underline_copy, str) and underline_copy.strip():
            name = f"{name} - {underline_copy.strip()}"

        sale_price = _as_number(ad.get("salePrice"))
        retail_price = _as_number(ad.get("retailPrice"))
        price_value = sale_price if sale_price is not None else retail_price
        if price_value is None:
            continue

        price_text = f"${price_value:.2f}"
        dedupe_key = (name.lower(), price_text.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        items.append(
            SaleItem(
                name=name,
                price_text=price_text,
                category="shoppable-weekly-deals",
            )
        )

    return tuple(items)


def _extract_sale_items_from_digital_ad_page(payload: object) -> tuple[SaleItem, ...]:
    if not isinstance(payload, dict):
        return tuple()
    contents = payload.get("contents")
    if not isinstance(contents, list):
        return tuple()

    items: list[SaleItem] = []
    seen: set[str] = set()
    for item in contents:
        if not isinstance(item, dict):
            continue
        if item.get("contentType") != "Offer":
            continue
        map_config = item.get("mapConfig")
        if not isinstance(map_config, str):
            continue
        try:
            config = json.loads(map_config)
        except json.JSONDecodeError:
            continue
        content = config.get("content")
        if not isinstance(content, dict):
            continue
        headline = str(content.get("headline") or "").strip()
        if not headline:
            continue
        body_copy = str(content.get("bodyCopy") or "").strip()
        name = f"{headline} - {body_copy}" if body_copy else headline
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(SaleItem(name=name, price_text="N/A", category="digital-ad-offer"))

    return tuple(items)


SHOPPABLE_WEEKLY_DEALS_URL_TEMPLATE = (
    "https://www.kroger.com/atlas/v1/shoppable-weekly-deals/deals?filter.circularId={circular_id}"
)


@dataclass(frozen=True)
class KrogerWebCaptureConfig:
    """Kroger weekly ad page + optional Atlas probes (shoppable deals first when circular_id is known)."""

    base_url: str = "https://www.kroger.com/weeklyad"
    max_items: int = 200
    circular_id: str | None = None
    cookie_header: str | None = None
    extra_headers: dict[str, str] | None = None
    browser_profile_dir: str | None = None
    browser_headless: bool = True
    browser_post_load_wait_ms: int = 5000
    browser_channel: str | None = None
    api_endpoints: tuple[str, ...] = (
        "https://www.kroger.com/atlas/v1/product/v2/products?filter.locationId={location_id}&filter.limit=30&filter.term=sale",
        "https://www.kroger.com/atlas/v1/product/v2/products?filter.locationId={location_id}&filter.limit=30&filter.term=weekly%20ad",
    )


class KrogerWebAdCaptureAdapter:
    def __init__(
        self,
        config: KrogerWebCaptureConfig | None = None,
        fetch_text: FetchText | None = None,
        fetch_json: FetchJson | None = None,
    ) -> None:
        self._config = config or KrogerWebCaptureConfig()
        self._fetch_text = fetch_text or default_fetch_text
        self._fetch_json = fetch_json or default_fetch_json
        self.last_stats: dict[str, object] = {
            "request_attempted": False,
            "has_initial_state_signal": False,
            "parsed_from_html_items": 0,
            "parsed_from_initial_state_items": 0,
            "api_endpoints_attempted": 0,
            "parsed_from_api_items": 0,
            "parsed_from_heuristic_items": 0,
            "circular_id_used": None,
            "circular_id_source": None,
            "shoppable_weekly_deals_attempted": False,
        }

    def _build_headers(self, location_id: str) -> dict[str, str]:
        extra = self._config.extra_headers or {}
        if self._config.cookie_header:
            return {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Cookie": self._config.cookie_header,
                **extra,
            }

        cookie_value = build_x_active_modality_cookie(location_id=location_id)
        return {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Cookie": f"x-active-modality={quote_plus(cookie_value)}",
            **extra,
        }

    def capture_weekly_ad(self, location_id: str) -> AdCaptureResult:
        self.last_stats = {
            "request_attempted": True,
            "has_initial_state_signal": False,
            "parsed_from_html_items": 0,
            "parsed_from_initial_state_items": 0,
            "api_endpoints_attempted": 0,
            "parsed_from_api_items": 0,
            "parsed_from_heuristic_items": 0,
            "circular_id_used": None,
            "circular_id_source": None,
            "shoppable_weekly_deals_attempted": False,
        }
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
        self.last_stats["parsed_from_html_items"] = len(parsed)
        if not parsed and "__INITIAL_STATE__" in html:
            self.last_stats["has_initial_state_signal"] = True
            parsed = _extract_sale_items_from_initial_state(html)
            self.last_stats["parsed_from_initial_state_items"] = len(parsed)
        if not parsed:
            resolved_circular_id = self._config.circular_id or _try_extract_circular_id_from_html(html)
            if resolved_circular_id:
                self.last_stats["circular_id_used"] = resolved_circular_id
                self.last_stats["circular_id_source"] = (
                    "config" if self._config.circular_id else "html"
                )
            parsed = self._extract_sale_items_from_api(
                location_id=location_id,
                headers=headers,
                circular_id=resolved_circular_id,
            )
            self.last_stats["parsed_from_api_items"] = len(parsed)
        if not parsed:
            parsed = _extract_heuristic_sale_anchors(html)
            self.last_stats["parsed_from_heuristic_items"] = len(parsed)
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

    def _api_probe_urls(self, location_id: str, circular_id: str | None) -> tuple[str, ...]:
        urls: list[str] = []
        if circular_id:
            urls.append(SHOPPABLE_WEEKLY_DEALS_URL_TEMPLATE.format(circular_id=circular_id))
        for template in self._config.api_endpoints:
            urls.append(template.format(location_id=location_id))
        return tuple(urls)

    def _extract_sale_items_from_api(
        self,
        location_id: str,
        headers: dict[str, str],
        circular_id: str | None,
    ) -> tuple[SaleItem, ...]:
        def walk(obj: object, out: list[SaleItem], seen: set[tuple[str, str]]) -> None:
            if isinstance(obj, dict):
                name = None
                for key in (
                    "description",
                    "name",
                    "itemName",
                    "title",
                    "dealTitle",
                    "offerHeadline",
                    "headline",
                    "productName",
                    "displayName",
                ):
                    value = obj.get(key)
                    if isinstance(value, str) and value.strip():
                        name = value.strip()
                        break

                price_value = None
                for key in (
                    "salePrice",
                    "promoPrice",
                    "offerPrice",
                    "price",
                    "regularPrice",
                    "displayPrice",
                    "formattedSalePrice",
                    "salePriceText",
                    "currentPrice",
                ):
                    value = obj.get(key)
                    if isinstance(value, (str, int, float)):
                        price_value = value
                        break
                    if isinstance(value, dict):
                        nested = value.get("amount")
                        if isinstance(nested, (int, float, str)):
                            price_value = nested
                            break

                if name is not None and price_value is not None:
                    raw_price = str(price_value).strip()
                    if isinstance(price_value, (int, float)):
                        price_text = f"${float(price_value):.2f}"
                    elif raw_price and raw_price[0] in "$€£":
                        price_text = raw_price
                    elif raw_price and re.match(r"^\d", raw_price):
                        price_text = f"${raw_price}"
                    else:
                        price_text = raw_price
                    dedupe_key = (name.lower(), price_text.lower())
                    if dedupe_key not in seen:
                        seen.add(dedupe_key)
                        out.append(SaleItem(name=name, price_text=price_text, category="unknown"))

                for value in obj.values():
                    walk(value, out, seen)
                return

            if isinstance(obj, list):
                for item in obj:
                    walk(item, out, seen)

        extracted: list[SaleItem] = []
        seen: set[tuple[str, str]] = set()
        for url in self._api_probe_urls(location_id=location_id, circular_id=circular_id):
            if "shoppable-weekly-deals" in url:
                self.last_stats["shoppable_weekly_deals_attempted"] = True
            self.last_stats["api_endpoints_attempted"] = int(self.last_stats["api_endpoints_attempted"]) + 1
            try:
                payload = self._fetch_json(url, headers)
            except Exception:
                continue
            if "shoppable-weekly-deals" in url:
                shoppable_items = _extract_sale_items_from_shoppable_weekly_deals(payload)
                for item in shoppable_items:
                    dedupe_key = (item.name.lower(), item.price_text.lower())
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    extracted.append(item)
            else:
                walk(payload, extracted, seen)
            if extracted:
                break

        return tuple(extracted)


class KrogerPlaywrightAdCaptureAdapter:
    def __init__(
        self,
        config: KrogerWebCaptureConfig | None = None,
        playwright_capture: PlaywrightCapture | None = None,
    ) -> None:
        self._config = config or KrogerWebCaptureConfig()
        self._playwright_capture = playwright_capture or default_playwright_capture
        self.last_stats: dict[str, object] = {
            "request_attempted": False,
            "has_initial_state_signal": False,
            "parsed_from_html_items": 0,
            "parsed_from_initial_state_items": 0,
            "api_endpoints_attempted": 0,
            "parsed_from_api_items": 0,
            "parsed_from_heuristic_items": 0,
            "circular_id_used": None,
            "circular_id_source": None,
            "shoppable_weekly_deals_attempted": False,
        }

    def _build_headers(self, location_id: str) -> dict[str, str]:
        extra = self._config.extra_headers or {}
        if self._config.cookie_header:
            return {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Cookie": self._config.cookie_header,
                **extra,
            }

        cookie_value = build_x_active_modality_cookie(location_id=location_id)
        return {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Cookie": f"x-active-modality={quote_plus(cookie_value)}",
            **extra,
        }

    def capture_weekly_ad(self, location_id: str) -> AdCaptureResult:
        self.last_stats = {
            "request_attempted": True,
            "has_initial_state_signal": False,
            "parsed_from_html_items": 0,
            "parsed_from_initial_state_items": 0,
            "api_endpoints_attempted": 0,
            "parsed_from_api_items": 0,
            "parsed_from_heuristic_items": 0,
            "circular_id_used": None,
            "circular_id_source": None,
            "shoppable_weekly_deals_attempted": False,
        }
        headers = self._build_headers(location_id=location_id)
        try:
            capture = self._playwright_capture(
                self._config.base_url,
                self._config.circular_id,
                headers,
                self._config.browser_profile_dir,
                self._config.browser_headless,
                self._config.browser_post_load_wait_ms,
                self._config.browser_channel,
            )
        except Exception as error:
            return AdCaptureResult(
                success=False,
                location_id=location_id,
                sale_items=(),
                source="kroger-playwright",
                message=f"request_failed:{error}",
            )

        html = str(capture.get("html") or "")
        parsed = _extract_sale_items_from_html(html)
        self.last_stats["parsed_from_html_items"] = len(parsed)
        if not parsed and "__INITIAL_STATE__" in html:
            self.last_stats["has_initial_state_signal"] = True
            parsed = _extract_sale_items_from_initial_state(html)
            self.last_stats["parsed_from_initial_state_items"] = len(parsed)

        resolved_circular_id = capture.get("circular_id")
        if not isinstance(resolved_circular_id, str) or not resolved_circular_id.strip():
            resolved_circular_id = self._config.circular_id or _try_extract_circular_id_from_html(html)
        if isinstance(resolved_circular_id, str) and resolved_circular_id.strip():
            self.last_stats["circular_id_used"] = resolved_circular_id.strip()
            self.last_stats["circular_id_source"] = (
                "config"
                if self._config.circular_id and self._config.circular_id.strip() == resolved_circular_id.strip()
                else "html"
            )

        if not parsed:
            deals_body = str(capture.get("deals_body") or "")
            if deals_body:
                self.last_stats["api_endpoints_attempted"] = 1
                self.last_stats["shoppable_weekly_deals_attempted"] = True
                try:
                    payload = json.loads(deals_body)
                except json.JSONDecodeError:
                    payload = None
                if payload is not None:
                    parsed = _extract_sale_items_from_shoppable_weekly_deals(payload)
                    self.last_stats["parsed_from_api_items"] = len(parsed)

        digital_ad_bodies = capture.get("digital_ad_bodies")
        if isinstance(digital_ad_bodies, list):
            extracted: list[SaleItem] = []
            seen: set[tuple[str, str]] = set()
            for body in digital_ad_bodies:
                if not isinstance(body, str) or not body.strip():
                    continue
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    continue
                for item in _extract_sale_items_from_digital_ad_page(payload):
                    key = (item.name.lower(), item.price_text.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    extracted.append(item)
            if extracted:
                parsed = tuple(extracted)
                self.last_stats["api_endpoints_attempted"] = max(
                    int(self.last_stats["api_endpoints_attempted"]),
                    len(digital_ad_bodies),
                )
                self.last_stats["parsed_from_api_items"] = len(parsed)

        if not parsed:
            parsed = _extract_heuristic_sale_anchors(html)
            self.last_stats["parsed_from_heuristic_items"] = len(parsed)

        if not parsed:
            deals_error = str(capture.get("deals_error") or "")
            message = "no_sale_items_parsed"
            if deals_error:
                message = f"no_sale_items_parsed:deals_error:{deals_error}"
            return AdCaptureResult(
                success=False,
                location_id=location_id,
                sale_items=(),
                source="kroger-playwright",
                message=message,
            )

        return AdCaptureResult(
            success=True,
            location_id=location_id,
            sale_items=parsed[: self._config.max_items],
            source="kroger-playwright",
        )
