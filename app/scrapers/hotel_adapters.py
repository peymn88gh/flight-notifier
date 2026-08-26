from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright

from app.core.config import Settings
from app.domain.types import HotelCriteria, HotelSearchResult, HotelSourceName
from app.scrapers.hotel_links import build_hotel_search_url
from app.scrapers.hotel_parser import GenericHotelParser

logger = logging.getLogger(__name__)


class PlaywrightHotelAdapter:
    def __init__(self, source: HotelSourceName, settings: Settings) -> None:
        self.source = source
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> PlaywrightHotelAdapter:
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

    async def search(self, criteria: HotelCriteria, checkin: date) -> HotelSearchResult:
        observed_at = datetime.now(UTC)
        search_url = build_hotel_search_url(self.source, criteria, checkin)
        if not search_url:
            return HotelSearchResult(
                source=self.source,
                searched_at=observed_at,
                search_url=f"https://{self.source.value}.invalid/",
                error=f"No known hotel URL for destination {criteria.destination}",
            )
        if not self.settings.scraping_enabled:
            return HotelSearchResult(
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
            if len(payloads) >= 50:
                return
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
                "[data-testid*='hotel'], [class*='hotel-card'], [class*='hotel-item'], "
                "[class*='accommodation-card'], .hotel-result, article"
            ).evaluate_all(
                """elements => elements.slice(0, 500).map(element => ({
                  text: element.innerText || '',
                  url: element.querySelector('a[href]')?.href || location.href,
                  has_specific_link: Boolean(element.querySelector('a[href]')),
                  unavailable:
                    element.classList.contains('is-disabled') ||
                    element.getAttribute('aria-disabled') === 'true' ||
                    Boolean(element.querySelector(
                      '[class*="disabled" i], [class*="soldout" i], [class*="sold-out" i], ' +
                      '[class*="unavailable" i], [class*="full" i]'
                    )) ||
                    Boolean(
                      Array.from(element.querySelectorAll('button')).find(button =>
                        button.disabled &&
                        /رزرو|انتخاب اتاق|مشاهده اتاق/.test(button.textContent || '')
                      )
                    )
                }))"""
            )
            parser = GenericHotelParser(
                self.source,
                criteria,
                checkin,
                search_url,
                observed_at,
            )
            hotels = parser.parse_payloads(payloads)
            if not hotels:
                hotels = parser.parse_dom_cards(cards)
            return HotelSearchResult(
                source=self.source,
                hotels=hotels,
                searched_at=observed_at,
                search_url=search_url,
            )
        except Exception as exc:
            logger.warning("%s hotel scrape failed: %s", self.source.value, exc)
            return HotelSearchResult(
                source=self.source,
                searched_at=observed_at,
                search_url=search_url,
                error=str(exc)[:500],
            )
        finally:
            await context.close()
            await asyncio.sleep(self.settings.scraper_min_delay_seconds)


def build_hotel_adapters(settings: Settings) -> list[PlaywrightHotelAdapter]:
    return [PlaywrightHotelAdapter(source, settings) for source in HotelSourceName]
