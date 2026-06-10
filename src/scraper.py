import asyncio
import re
import browser_cookie3
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


class FragranticaScraper:
    BASE = "https://www.fragrantica.ru"
    # Куки нужны только для обхода Cloudflare, не для авторизации
    CF_COOKIE_NAMES = {"cf_clearance", "_ga", "_ga_69SEWE02QT", "rtyt45gh"}

    def _get_cf_cookies(self) -> list:
        """Берём только CF/аналитические куки из Chrome — без сессионных."""
        try:
            result = []
            for c in browser_cookie3.chrome(domain_name=".fragrantica.ru"):
                if c.name in self.CF_COOKIE_NAMES:
                    result.append({
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain if c.domain else ".fragrantica.ru",
                        "path": c.path or "/",
                    })
            return result
        except Exception:
            return []

    async def get_favorites(self, profile_id: str) -> list:
        """Парсит публичный профиль /chlen/{profile_id}."""
        if not profile_id:
            raise ValueError("profile_id не задан")

        cf_cookies = self._get_cf_cookies()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            if cf_cookies:
                await context.add_cookies(cf_cookies)

            page = await context.new_page()
            try:
                profile_url = f"{self.BASE}/chlen/{profile_id}"
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)

                # Ждём появления wardrobe-секции (загружается через JS ~1с)
                try:
                    await page.wait_for_function(
                        """() => {
                            const h4s = document.querySelectorAll('h4');
                            return Array.from(h4s).some(h => h.textContent.includes('У меня'));
                        }""",
                        timeout=15000,
                    )
                except Exception:
                    await asyncio.sleep(3)
                await asyncio.sleep(0.5)

                content = await page.content()
                await browser.close()
                return self._parse_wardrobe(content)

            except Exception as e:
                try:
                    await page.screenshot(path="error.png", timeout=5000)
                except Exception:
                    pass
                await browser.close()
                raise e

    def _parse_wardrobe(self, html: str) -> list:
        soup = BeautifulSoup(html, "html.parser")
        perfumes = []
        seen = set()

        section_labels = ["У меня есть"]

        for h4 in soup.find_all("h4"):
            if not any(label in h4.get_text(strip=True) for label in section_labels):
                continue
            parent = h4.parent
            for _ in range(8):
                if parent is None:
                    break
                links = parent.find_all("a", href=lambda h: h and "/perfume/" in h)
                if links:
                    for a in links:
                        href = a["href"]
                        if href in seen:
                            continue
                        seen.add(href)
                        m = re.search(r"/perfume/([^/]+)/([^/]+)-(\d+)\.html", href)
                        if not m:
                            continue
                        brand = m.group(1).replace("-", " ")
                        name_raw = m.group(2).replace("-", " ")
                        full_url = f"{self.BASE}{href}" if href.startswith("/") else href
                        perfumes.append({"name": f"{brand} {name_raw}", "link": full_url})
                    break
                parent = parent.parent

        return perfumes
