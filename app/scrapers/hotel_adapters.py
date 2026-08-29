from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright

from app.core.config import Settings
from app.domain.types import HotelCriteria, HotelSearchResult, HotelSourceName
from app.scrapers.hotel_links import (
    build_hotel_search_url,
    destination_city_fa,
    validate_hotel_source_url,
)
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

    async def _run_interactive_search(self, page, criteria: HotelCriteria) -> None:
        """trip.ir has no query-string deep link into results (see hotel_links.py); its
        destination field resolves to an internal numeric city id only through its own
        live autocomplete, so the actual search has to be driven like a real visitor.
        Verified against the live site on 2026-08-26 for several cities. Any failure here
        just leaves the page on its landing state, which parse_payloads/parse_dom_cards
        will correctly find nothing on rather than fabricate a result.
        """
        city_fa = destination_city_fa(criteria.destination)
        if not city_fa:
            return
        destination_input = page.locator(
            "input[placeholder*='مقصد'], input[placeholder*='شهر']"
        ).first
        await destination_input.click(timeout=8000)
        await destination_input.fill(city_fa)
        await page.wait_for_timeout(1500)
        suggestion = page.locator("li, [role='option'], [role='listitem']").filter(
            has_text=city_fa
        )
        if await suggestion.count() == 0:
            return
        await suggestion.first.click(timeout=8000)
        await page.wait_for_timeout(500)
        search_button = page.locator("button:has-text('جستجو')").first
        await search_button.click(timeout=8000)
        await page.wait_for_timeout(4000)

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
            # These sites render a multi-second progressive loading state (a visible
            # "searching..." progress bar) before their real listing API resolves;
            # 2026-08-29 measurement against Snapptrip showed its listing call
            # reliably firing by ~25s but not by 18s. A short wait here silently
            # yields zero results rather than an error, since the page loaded fine.
            await page.wait_for_timeout(25000)
            if self.source == HotelSourceName.TRIP:
                try:
                    await self._run_interactive_search(page, criteria)
                except Exception as exc:
                    logger.warning("trip.ir interactive hotel search failed: %s", exc)
                else:
                    if validate_hotel_source_url(self.source, page.url):
                        search_url = page.url
                        await page.wait_for_timeout(10000)
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
