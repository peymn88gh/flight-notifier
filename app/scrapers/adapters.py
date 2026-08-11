from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright

from app.core.config import Settings
from app.domain.types import AlertCriteria, SiteSearchResult, SourceName
from app.scrapers.links import build_search_url
from app.scrapers.parser import GenericFlightParser

logger = logging.getLogger(__name__)


class PlaywrightSiteAdapter:
    def __init__(self, source: SourceName, settings: Settings) -> None:
        self.source = source
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> PlaywrightSiteAdapter:
        if not self.settings.scraping_enabled:
            return self
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.settings.scraper_headless
        )
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def search(
        self,
        criteria: AlertCriteria,
        outbound_date: date,
        return_date: date | None,
    ) -> SiteSearchResult:
        search_url = build_search_url(self.source, criteria, outbound_date, return_date)
        observed_at = datetime.now(UTC)
        if not self.settings.scraping_enabled:
            return SiteSearchResult(
                source=self.source,
                searched_at=observed_at,
                search_url=search_url,
                error="Live scraping is disabled",
            )
        if not self._browser:
            raise RuntimeError("Adapter must be used as an async context manager")

        context = await self._browser.new_context(
            locale="fa-IR",
            timezone_id=criteria.timezone,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        payloads: list[Any] = []

        async def capture_response(response) -> None:
            content_type = (response.headers.get("content-type") or "").lower()
            if "json" not in content_type:
                return
            try:
                payloads.append(await response.json())
            except Exception:
                return

        page.on("response", capture_response)
        try:
            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=self.settings.scraper_timeout_seconds * 1000,
            )
            await page.wait_for_timeout(7000)
            cards = await page.locator(
                "[data-testid*='flight'], [class*='flight-card'], [class*='ticket-card'], "
                "[class*='available-flight'], article"
            ).evaluate_all(
                """elements => elements.slice(0, 500).map(element => ({
                  text: element.innerText || '',
                  url: element.querySelector('a[href]')?.href || location.href
                }))"""
            )
            parser = GenericFlightParser(
                self.source,
                criteria,
                outbound_date,
                return_date,
                search_url,
                observed_at,
            )
            itineraries = parser.parse_payloads(payloads)
            if not itineraries:
                itineraries = parser.parse_dom_cards(cards)
            return SiteSearchResult(
                source=self.source,
                itineraries=itineraries,
                searched_at=observed_at,
                search_url=search_url,
            )
        except Exception as exc:
            logger.warning("%s scrape failed: %s", self.source.value, exc)
            return SiteSearchResult(
                source=self.source,
                searched_at=observed_at,
                search_url=search_url,
                error=str(exc)[:500],
            )
        finally:
            await context.close()
            await asyncio.sleep(self.settings.scraper_min_delay_seconds)


def build_adapters(settings: Settings) -> list[PlaywrightSiteAdapter]:
    return [PlaywrightSiteAdapter(source, settings) for source in SourceName]
